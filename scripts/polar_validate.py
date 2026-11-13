#!/usr/bin/env python
"""Second-round validation: NACA 2412 / 4412 polars against a peer-reviewed CFD paper.

Ground truth
------------
Kılıç & Gümuş(?), "Performance analysis of NACA 2412 and NACA 4412 airfoils ...",
J. Thermal Engineering 10(6): 1524-1538, 2024, DOI 10.14744/thermal.0000892 (CC BY-NC).
Tables 2-3 (geometry and test conditions), Table 9 (CL), Table 10 (CD).

Design parameters from the paper:
    NACA 2412: 12% thickness at 30% chord, 2% camber at 40% chord
    NACA 4412: 12% thickness at 30% chord, 4% camber at 40% chord
    chord 0.1 m (test-parameter table), V = 43 m/s, air at 1.225 kg/m3
    AOA = 0, 5, 10, 15, 20 deg

What the local toolchain can and cannot do
------------------------------------------
* Geometry: exact NACA 4-digit generation -> compare thickness/camber.
* Lift: thin-airfoil theory on the generated camber line -> compare with Table 9.
  Inviscid theory has no stall, so agreement is expected pre-stall and divergence
  is expected at/post stall - that is the physically correct outcome, not a bug.
* Drag: needs a viscous CFD solver; this toolchain has none. Table 10 is therefore
  only checked for physical plausibility (order of magnitude), not reproduced.

Usage: python polar_validate.py --job <dir>
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

# ---- ground truth transcribed from the paper -------------------------------- #
PAPER = {
    "title": "Characterization of NACA 2412 and NACA 4412 airfoils: Effects of angle of attack on aerodynamics coefficients",
    "authors": "D. Akgumus Gok, K. N. M. Al-Nimer",
    "journal": "Journal of Thermal Engineering 10(6): 1524-1538, 2024",
    "doi": "10.14744/thermal.0000892",
    "license": "CC BY-NC",
    "cl": {  # Table 9
        "NACA 4412": {0.0: 0.412, 5.0: 0.912, 10.0: 1.26, 15.0: 1.24, 20.0: 0.908},
        "NACA 2412": {0.0: 0.0589, 5.0: 0.7429, 10.0: 1.1591, 15.0: 0.8412, 20.0: 0.435},
    },
    "cd": {  # Table 10
        "NACA 4412": {0.0: 0.107, 5.0: 0.0421, 10.0: 0.0685, 15.0: 0.172, 20.0: 0.2},
        "NACA 2412": {0.0: 0.2316, 5.0: 0.03056, 10.0: 0.05124, 15.0: 0.1522, 20.0: 0.348},
    },
    "conditions": {"V_m_s": 43.0, "rho": 1.225, "chord_m": 0.1, "alpha_deg": [0, 5, 10, 15, 20]},
}


def naca4(m: float, p: float, t: float, n: int = 240):
    beta = np.linspace(0.0, math.pi, n)
    x = 0.5 * (1.0 - np.cos(beta))
    yt = 5.0 * t * (0.2969 * np.sqrt(x) - 0.1260 * x - 0.3516 * x**2 + 0.2843 * x**3 - 0.1015 * x**4)
    yc = np.where(x < p, m / p**2 * (2 * p * x - x**2),
                  m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * x - x**2))
    dy = np.where(x < p, 2 * m / p**2 * (p - x), 2 * m / (1 - p) ** 2 * (p - x))
    th = np.arctan(dy)
    upper = np.column_stack([x - yt * np.sin(th), yc + yt * np.cos(th)])[::-1]
    lower = np.column_stack([x + yt * np.sin(th), yc - yt * np.cos(th)])
    return upper, lower


def thin_airfoil(m: float, p: float) -> dict:
    """alpha_L0 and the ideal lift slope from thin-airfoil theory."""
    th = np.linspace(0.0, math.pi, 200001)[1:-1]
    x = 0.5 * (1.0 - np.cos(th))
    dy = np.where(x < p, 2.0 * m / p**2 * (p - x), 2.0 * m / (1.0 - p) ** 2 * (p - x))
    a0 = -abs(float(np.trapezoid(dy * (np.cos(th) - 1.0), th) / math.pi))
    return {"alpha_L0_deg": math.degrees(a0), "slope_per_rad": 2.0 * math.pi}


def cl_thin(alpha_deg: float, a0_rad: float) -> float:
    return 2.0 * math.pi * (math.radians(alpha_deg) - a0_rad)


def geometry_check(name: str, m: float, p: float, t: float) -> dict:
    up, lo = naca4(m, p, t, 240)
    x = lo[:, 0]
    camber = 0.5 * (up[::-1, 1] + lo[:, 1])
    thick = up[::-1, 1] - lo[:, 1]
    i_t, i_c = int(np.argmax(thick)), int(np.argmax(camber))
    return {
        "airfoil": name, "m": m, "p": p, "t": t,
        "max_thickness_ratio": round(float(thick[i_t]), 6),
        "max_thickness_x": round(float(x[i_t]), 6),
        "max_camber_ratio": round(float(camber[i_c]), 6),
        "max_camber_x": round(float(x[i_c]), 6),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    args = ap.parse_args()

    job = Path(args.job).resolve()
    out = job / "polar"
    out.mkdir(parents=True, exist_ok=True)

    airfoils = {"NACA 2412": (0.02, 0.40, 0.12), "NACA 4412": (0.04, 0.40, 0.12)}
    geo, aero = {}, {}
    for name, (m, p, t) in airfoils.items():
        geo[name] = geometry_check(name, m, p, t)
        thin = thin_airfoil(m, p)
        a0 = math.radians(thin["alpha_L0_deg"])
        rows = []
        for a in PAPER["conditions"]["alpha_deg"]:
            cl_t = cl_thin(a, a0)
            cl_p = PAPER["cl"][name][a]
            rows.append({
                "alpha_deg": a,
                "cl_paper": cl_p,
                "cl_thin": round(cl_t, 4),
                "abs_err": round(abs(cl_t - cl_p), 4),
                "rel_err_pct": round((cl_t - cl_p) / cl_p * 100.0, 1),
            })
        aero[name] = {**thin, "rows": rows}

    # lift-curve slope from the paper (linear part 0-10 deg) vs theory
    slopes = {}
    for name in airfoils:
        c0, c10 = PAPER["cl"][name][0.0], PAPER["cl"][name][10.0]
        slopes[name] = round((c10 - c0) / 10.0, 5)
    theory_slope = round(2.0 * math.pi / 180.0 * 180.0 / math.pi, 5)  # per degree
    theory_slope = round(2.0 * math.pi * math.pi / 180.0, 5)

    # drag plausibility: the toolchain cannot compute CD; record only the check
    drag = {}
    for name in airfoils:
        cds = PAPER["cd"][name]
        drag[name] = {
            "cd_min": min(cds.values()),
            "cd_min_alpha": min(cds, key=cds.get),
            "plausible_order": bool(1e-3 < min(cds.values()) < 0.05),
            "note": "viscous quantity: not computable by this inviscid toolchain",
        }

    info = {
        "paper": PAPER,
        "geometry": geo,
        "aerodynamics": aero,
        "lift_slope_per_deg": {"paper": slopes, "thin_airfoil": theory_slope,
                               "rel_err_pct": {k: round((slopes[k] - theory_slope) / theory_slope * 100, 1)
                                               for k in slopes}},
        "drag": drag,
        "scope_note": "CL compared; CD only screened for plausibility (no viscous solver locally)",
    }
    (out / "polar.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(info, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
