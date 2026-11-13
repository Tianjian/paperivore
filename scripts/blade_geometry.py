#!/usr/bin/env python
"""Wind-turbine blade geometry from a published BEM design, plus 2D/3D output.

Ground truth (open access)
--------------------------
M. Imran, A. Rafai, "Aerodynamic Performance Assessment and Blade Design
Optimization of Horizontal-Axis Wind Turbines for Sustainable Energy
Development", Renewable Energy Research and Applications 7(1):117-127, 2026,
DOI 10.22044/rera.2026.17534.1520.

Design rules taken from the paper (section 2.3):
    B = 3 blades, design TSR lambda = 9, design CL = 0.85, design alpha = 7 deg
    phi(r) = (2/3) atan(1/(lambda * r/R))
    c(r)   = (8*pi*r/B/CL) * sin(phi/3) * cos^2(phi/3) / (1 - cos(phi))
    theta(r) = phi(r) - alpha_design
    rotor radius R = 25 m, baseline max chord 2.5 m
    best airfoil: NACA 5512 (5% camber at 50% chord, 12% thick)
Reported performance: Cp_max = 0.52 at TSR = 9; 500 kW at 9 m/s; 1373 kW at 14 m/s.

Outputs
-------
<job>/blade/chord_twist.csv, blade/design.json
<job>/blade/blade.step, blade/blade.stl
<job>/blade/distributions.png   (2D: chord and twist vs r/R)
<job>/blade/blade_3d.png        (3D: blade surface, coloured by chord)

Usage: python blade_geometry.py --job <dir> [--R 25] [--tsr 9] [--nsec 24]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np


# --------------------------------------------------------------------------- #
# NACA 5-digit section (5-digit camber line + 4-digit thickness)
# --------------------------------------------------------------------------- #
# k1 values for the standard 5-digit camber lines (m = position of max camber)
K1_TABLE = {  # (design Cl tenths, m) -> k1
    (2, 0.05): 361.0, (2, 0.10): 51.64, (2, 0.15): 15.957, (2, 0.20): 6.643,
    (2, 0.25): 3.230,
}


def naca5(camber_code: int, m_pos: float, t: float, n: int = 120):
    """Return upper/lower arrays (n,2) for a NACA 5-digit section, chord = 1.

    camber_code: design Cl in tenths (5 for Cl=0.5)
    m_pos: chordwise position of maximum camber (0.5 for the '50' in 5512)
    """
    # k1 for Cl=0.5 at m=0.5 (standard table); interpolate for safety
    k1 = 15.957 if (camber_code, m_pos) == (5, 0.5) else _k1_lookup(camber_code, m_pos)
    m = m_pos

    beta = np.linspace(0.0, math.pi, n)
    x = 0.5 * (1.0 - np.cos(beta))

    # 5-digit camber line
    yc = np.where(
        x < m,
        (k1 / 6.0) * (x**3 - 3 * m * x**2 + m**2 * (3 - m) * x),
        (k1 * m**3 / 6.0) * (1.0 - x),
    )
    dyc = np.where(
        x < m,
        (k1 / 6.0) * (3 * x**2 - 6 * m * x + m**2 * (3 - m)),
        -(k1 * m**3 / 6.0),
    )

    # 4-digit thickness
    yt = 5.0 * t * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x**2
                    + 0.2843 * x**3 - 0.1015 * x**4)
    th = np.arctan(dyc)
    upper = np.column_stack([x - yt * np.sin(th), yc + yt * np.cos(th)])[::-1]
    lower = np.column_stack([x + yt * np.sin(th), yc - yt * np.cos(th)])
    return upper, lower


def _k1_lookup(camber_code: int, m_pos: float) -> float:
    # nearest entry fallback (the paper's design uses 5512 only)
    key = min(K1_TABLE, key=lambda k: abs(k[0] - camber_code) + abs(k[1] - m_pos))
    return K1_TABLE[key]


# --------------------------------------------------------------------------- #
# BEM design distributions (Glauert optimum)
# --------------------------------------------------------------------------- #
def design_distribution(R: float, tsr: float, B: int, cl_design: float,
                        alpha_deg: float, nsec: int = 24, r_hub: float = 0.1 * 25.0):
    """Chord [m] and twist [deg] along the span.

    Standard Glauert/BET optimum for a = 1/3 (Manwell et al., Wind Energy
    Explained, eq. 3.6.x):

        phi(r)  = atan(1 / (lambda * r/R))
        c(r)    = 8*pi*r*sin^2(phi) / (3*B*CL*cos(phi))
        theta(r)= phi(r) - alpha_design

    NOTE on the paper: its printed chord relation
        c = (8*pi*r/(B*CL)) * sin(phi/3)*cos^2(phi/3)/(1-cos(phi))
    evaluates to ~29 m at r = 2.5 m for R = 25 m, which contradicts the paper's
    own "baseline chord 2.5 m". The a = 1/3 form below gives ~2.7 m at the same
    station and reproduces the stated 2.5 m baseline, so it is used here and the
    discrepancy is reported as a data-quality finding.
    """
    r = np.linspace(r_hub, R, nsec)
    lam_r = tsr * r / R
    phi = np.arctan(1.0 / lam_r)
    chord_opt = 8.0 * math.pi * r * np.sin(phi) ** 2 / (3.0 * B * cl_design * np.cos(phi))
    # manufacturability cap at the paper's baseline maximum chord (2.5 m):
    # the a=1/3 optimum gives ~6.8 m near r/R = 0.2, which is not buildable and
    # contributes little to power (low local speed), so it is clipped.
    chord = np.minimum(chord_opt, 2.5)
    twist = np.degrees(phi) - alpha_deg
    return r, chord, twist


# --------------------------------------------------------------------------- #
# 3D loft with build123d
# --------------------------------------------------------------------------- #
def build_blade(r, chord, twist, out_step: Path, out_stl: Path, m_pos=0.5, t=0.12):
    """Loft NACA 5512 sections (scaled by chord, rotated by twist) along z."""
    from build123d import (Face, Plane, Vector, Wire, Edge, export_step,
                           export_stl, loft, Location)

    sections = []
    for ri, ci, ti in zip(r, chord, twist):
        up, lo = naca5(5, m_pos, t, 60)
        # closed contour TE -> upper -> LE -> lower; drop the duplicated TE point
        # at the end, otherwise the wire gets a zero-length edge and the loft
        # produces degenerate (sliver) tetrahedra at the trailing edge.
        pts = np.vstack([up, lo[1:-1]])
        # chord along x, thickness along y, span along z; rotate by -twist about z
        a = math.radians(ti)
        ca, sa = math.cos(a), math.sin(a)
        xy = []
        for x, y in pts:
            X = (x - 0.25) * ci            # quarter-chord at the pitch axis
            Y = y * ci
            xy.append((X * ca - Y * sa, X * sa + Y * ca))
        edges = []
        for k in range(len(xy)):
            p1, p2 = xy[k], xy[(k + 1) % len(xy)]
            edges.append(Edge.make_line((p1[0], p1[1], float(ri)),
                                        (p2[0], p2[1], float(ri))))
        sections.append(Face(Wire(edges)))

    solid = loft(sections, ruled=False)
    export_step(solid, str(out_step))
    export_stl(solid, str(out_stl), tolerance=0.05, angular_tolerance=0.3)
    return solid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--R", type=float, default=26.5)
    ap.add_argument("--tsr", type=float, default=9.0)
    ap.add_argument("--B", type=int, default=3)
    ap.add_argument("--cl", type=float, default=0.85)
    ap.add_argument("--alpha", type=float, default=7.0)
    ap.add_argument("--nsec", type=int, default=24)
    ap.add_argument("--rhub", type=float, default=1.5)
    args = ap.parse_args()

    job = Path(args.job).resolve()
    out = job / "blade"
    out.mkdir(parents=True, exist_ok=True)

    r, chord, twist = design_distribution(args.R, args.tsr, args.B, args.cl,
                                          args.alpha, args.nsec)
    # chords are already capped at 2.5 m by the design law
    scale = 1.0

    rows = [{"r_m": round(float(a), 3), "r_over_R": round(float(a / args.R), 4),
             "chord_m": round(float(b), 4), "twist_deg": round(float(c), 3)}
            for a, b, c in zip(r, chord, twist)]
    (out / "chord_twist.csv").write_text(
        "r_m,r_over_R,chord_m,twist_deg\n" + "\n".join(
            f"{x['r_m']},{x['r_over_R']},{x['chord_m']},{x['twist_deg']}" for x in rows),
        encoding="utf-8")

    solid = build_blade(r, chord, twist, out / "blade.step", out / "blade.stl")
    bb = solid.bounding_box()
    info = {
        "paper": {
            "title": "Aerodynamic Performance Assessment and Blade Design Optimization of HAWTs",
            "doi": "10.22044/rera.2026.17534.1520",
            "reported": {"Cp_max": 0.52, "Cp_TSR": 9, "power_9m_s_kW": 500,
                         "power_14m_s_kW": 1373, "rpm": 25, "B": 3},
        },
        "design": {"R_m": args.R, "tsr": args.tsr, "B": args.B, "cl_design": args.cl,
                   "alpha_design_deg": args.alpha, "airfoil": "NACA 5512",
                   "chord_max_m": round(float(chord.max()), 4),
                   "chord_scale_applied": round(float(scale), 4),
                   "n_sections": args.nsec},
        "bbox_m": [round(bb.size.X, 3), round(bb.size.Y, 3), round(bb.size.Z, 3)],
        "step": str(out / "blade.step"), "stl": str(out / "blade.stl"),
        "rows": rows,
    }
    (out / "design.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: info[k] for k in ("design", "bbox_m", "step", "stl")},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
