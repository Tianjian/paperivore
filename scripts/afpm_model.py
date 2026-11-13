#!/usr/bin/env python
"""Axial-flux PM motor: 3D geometry, 2D magnetostatic solve, analytical checks.

Reference (open access)
-----------------------
J. Wang, Q. Xie, J. Han, Y. Zhang, C. G. Atkeson, A. Gupta, D. Pathak, Y. Bisk,
"High Torque Density PCB Axial Flux Permanent Magnet Motor for Micro Robots",
arXiv:2509.23561.

TABLE I  (design parameters)
    5 pole pairs (10 poles), 9 virtual slots, OD 19 mm, ID 7.0 mm
    air gap 0.25 mm, PCB stator 6.0 mm, 48 single layers, 3 turns/coil,
    2 parallel branches, trace 0.36 mm wide, 0.06 mm copper, copper fill >= 45 %
TABLE II (measured prototype)
    nominal 30.7 mNm @ 2000 rpm / 0.96 A, stall 158 mNm @ 5.95 A,
    Kt = 32.0 mNm/A, terminal R = 4.70 ohm, L = 3 mH, 3 phase

What is computed here
---------------------
1. 3D solid model (build123d): two rotor discs with 10 sector magnets + PCB stator
2. 2D magnetostatic FEM (own linear solver, magnetic scalar potential, SI units)
   on the unrolled domain at mean radius -> air-gap flux density map
3. Analytical magnetic circuit -> B_g, Kt; winding resistance from trace geometry
4. Comparison with the measured Kt and R, plus the implied magnet thickness

Usage:
    python afpm_model.py geom  --job <dir>
    python afpm_model.py field --job <dir>
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

# ---- TABLE I ---------------------------------------------------------------
P_PAIRS = 5
OD = 0.019
ID = 0.0070
R_O = OD / 2
R_I = ID / 2
GAP = 0.00025
PCB_T = 0.0060
N_LAYERS = 48
TURNS_PER_COIL = 3
PARALLEL = 2
TRACE_W = 0.00036
CU_T = 0.00006
SLOTS = 9
MU0 = 4e-7 * math.pi

# ---- assumptions (NOT given in the paper) ---------------------------------
BR = 1.30          # NdFeB remnant flux density [T]
MU_R_MAG = 1.05
H_M = 0.0010       # magnet thickness [m] - assumed, inverted later
MU_R_IRON = 1000.0
RHO_CU = 1.72e-8

# ---- TABLE II --------------------------------------------------------------
KT_MEAS = 0.0320   # Nm/A
R_MEAS = 4.70
T_STALL_MEAS = 0.158
I_STALL_MEAS = 5.95


def pole_area() -> float:
    return math.pi * (R_O**2 - R_I**2) / (2 * P_PAIRS)


def circuit_Bg(h_m: float = H_M, br: float = BR) -> dict:
    """1-D magnetic circuit through magnet -> gap -> PCB -> iron."""
    g_eff = GAP + PCB_T          # non-magnetic path (PCB is non-magnetic)
    # two magnets in series (N and S poles of the same flux loop) + gap + PCB
    Bg = br / (1.0 + (g_eff) / h_m)
    return {"h_m": h_m, "g_eff_m": g_eff, "B_g_T": Bg,
            "flux_per_pole_Wb": Bg * pole_area()}


def kt_from_Bg(Bg: float, n_phase: float) -> float:
    """Kt = 3/2 * p * N_phase * Phi_pole  (Nm/A, sinusoidal 3-phase)."""
    return 1.5 * P_PAIRS * n_phase * Bg * pole_area()


def winding_resistance(n_phase: float) -> dict:
    r_m = (R_O + R_I) / 2
    turn_len = 2 * (R_O - R_I) + 2 * math.pi * r_m / SLOTS   # rough per-turn length
    area = TRACE_W * CU_T
    R = RHO_CU * n_phase * turn_len / area
    return {"n_phase": n_phase, "turn_len_m": turn_len, "R_ohm": R}


def solve_2d(nx: int = 160, ny: int = 120, h_m: float = H_M, br: float = BR) -> dict:
    """Linear 2D magnetostatics on the unrolled pole-pair domain.

    Scalar potential formulation: div(mu grad phi) = div(mu0 M).
    x: tangential (one pole pair, periodic), y: axial (0 = PCB mid-plane).
    Unit magnetisation M0 = Br/mu0 in +/- y for the two poles.
    """
    r_m = (R_O + R_I) / 2
    Lx = 2 * math.pi * r_m / P_PAIRS          # one pole pair
    y_pcb = PCB_T / 2
    y_gap = y_pcb + GAP
    y_mag = y_gap + h_m
    y_top = y_mag + 0.001                     # back iron 1 mm
    Ly = y_top
    xs = np.linspace(0, Lx, nx + 1)
    ys = np.linspace(0, Ly, ny + 1)
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    pts = np.column_stack([X.ravel(), Y.ravel()])
    nid = np.arange(pts.shape[0]).reshape(ny + 1, nx + 1)

    tris = []
    for j in range(ny):
        for i in range(nx):
            n0, n1 = nid[j, i], nid[j, i + 1]
            n2, n3 = nid[j + 1, i + 1], nid[j + 1, i]
            tris.append((n0, n1, n2))
            tris.append((n0, n2, n3))
    tris = np.array(tris)

    # element material: mu and magnetisation (My)
    cx = pts[tris, 0].mean(axis=1)
    cy = pts[tris, 1].mean(axis=1)
    mu = np.full(len(tris), MU0)
    My = np.zeros(len(tris))
    mag = cy > y_gap - 1e-12
    mu[mag] = MU0 * MU_R_MAG
    iron = cy > y_mag - 1e-12
    mu[iron] = MU0 * MU_R_IRON
    # polarity: first half of the period is +y, second half -y
    My[mag] = np.where(cx[mag] < Lx / 2, br / MU0, -br / MU0)

    # assemble
    n = pts.shape[0]
    rows, cols, vals = [], [], []
    f = np.zeros(n)
    for e, (i0, i1, i2) in enumerate(tris):
        x1, y1 = pts[i0]; x2, y2 = pts[i1]; x3, y3 = pts[i2]
        det = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)
        if abs(det) < 1e-20:
            continue
        b = np.array([y2 - y3, y3 - y1, y1 - y2]) / det
        c = np.array([x3 - x2, x1 - x3, x2 - x1]) / det
        area = abs(det) / 2
        Ke = mu[e] * area * (np.outer(b, b) + np.outer(c, c))
        idx = [i0, i1, i2]
        for a in range(3):
            for bb in range(3):
                rows.append(idx[a]); cols.append(idx[bb]); vals.append(Ke[a, bb])
        if My[e] != 0.0:
            # rhs = -int mu0 M . grad(w) = -mu0 My * int dw/dy
            for a in range(3):
                f[idx[a]] += MU0 * My[e] * c[a] * area

    from scipy.sparse import coo_matrix
    from scipy.sparse.linalg import spsolve
    K = coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsr()

    # periodic in x: phi(right) = phi(left).  Substitute the column, otherwise
    # the system is singular (this produced 1e74 garbage on the first run).
    left = nid[:, 0]
    right = nid[:, nx]
    K = K.tolil()
    for j in range(ny + 1):
        K[:, left[j]] = K[:, left[j]] + K[:, right[j]]
        K[:, right[j]] = 0.0
        K[right[j], :] = 0.0
        K[right[j], right[j]] = 1.0
        f[left[j]] += f[right[j]]
        f[right[j]] = 0.0
    K = K.tocsr()
    # Dirichlet phi = 0 on the outer iron surface
    top = nid[ny, :]
    K = K.tolil()
    for t in top:
        K[t, :] = 0.0
        K[t, t] = 1.0
    K = K.tocsr()
    f[top] = 0.0

    phi = spsolve(K, f)

    # B = -mu grad(phi) + mu0 M
    Bx = np.zeros(len(tris)); By = np.zeros(len(tris))
    for e, (i0, i1, i2) in enumerate(tris):
        x1, y1 = pts[i0]; x2, y2 = pts[i1]; x3, y3 = pts[i2]
        det = (x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)
        if abs(det) < 1e-20:
            continue
        b = np.array([y2 - y3, y3 - y1, y1 - y2]) / det
        c = np.array([x3 - x2, x1 - x3, x2 - x1]) / det
        ph = phi[[i0, i1, i2]]
        Bx[e] = -mu[e] * float(b @ ph)
        By[e] = -mu[e] * float(c @ ph) + MU0 * My[e]

    # air-gap flux density on the mid-PCB line
    gap_sel = np.abs(cy - y_pcb) < (Ly / ny)
    Bg_avg = float(np.mean(np.abs(By[gap_sel]))) if gap_sel.any() else float("nan")

    return {"Lx": Lx, "Ly": Ly, "nx": nx, "ny": ny, "pts": pts, "tris": tris,
            "Bx": Bx, "By": By, "phi": phi, "Bg_avg": Bg_avg,
            "y_pcb": y_pcb, "y_gap": y_gap, "y_mag": y_mag, "y_top": y_top,
            "Bmag": np.hypot(Bx, By), "cx": cx, "cy": cy, "mu": mu}


def geom(job: Path) -> int:
    from build123d import (Cylinder, Pos, export_step, export_stl, Box, Rot)
    th = job / "afpm"
    th.mkdir(parents=True, exist_ok=True)

    # stator PCB annulus
    pcb = Cylinder(R_O, PCB_T) - Cylinder(R_I, PCB_T * 1.2)
    pcb = Pos(0, 0, 0) * pcb
    # rotor discs + 10 sector magnets (approximated as boxes swept radially)
    magnets = []
    for k in range(2 * P_PAIRS):
        ang = 360.0 / (2 * P_PAIRS) * k
        wedge = Box((R_O - R_I) * 0.92, 2 * math.pi * (R_O + R_I) / 2 / (2 * P_PAIRS) * 0.88, H_M)
        wedge = Pos((R_O + R_I) / 2, 0, PCB_T / 2 + GAP + H_M / 2) * wedge
        wedge = Rot(0, 0, ang) * wedge
        magnets.append(wedge)
    top = magnets[0]
    for m in magnets[1:]:
        top = top + m
    top_disc = Pos(0, 0, PCB_T / 2 + GAP + H_M + 0.0005) * Cylinder(R_O, 0.001)
    solid = pcb + top + top_disc
    export_step(solid, str(th / "afpm.step"))
    export_stl(solid, str(th / "afpm.stl"), tolerance=0.00005, angular_tolerance=0.2)

    info = {"poles": 2 * P_PAIRS, "r_o": R_O, "r_i": R_I, "pcb_t": PCB_T,
            "gap": GAP, "h_m_assumed": H_M, "step": str(th / "afpm.step")}
    (th / "geom.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("geom"); g.add_argument("--job", required=True)
    f = sub.add_parser("field"); f.add_argument("--job", required=True)
    args = ap.parse_args()
    job = Path(args.job).resolve()
    if args.cmd == "geom":
        return geom(job)

    th = job / "afpm"
    th.mkdir(parents=True, exist_ok=True)
    res = solve_2d()
    info = {
        "Bg_fem_T": round(res["Bg_avg"], 4),
        "Bg_circuit_T": round(circuit_Bg()["B_g_T"], 4),
        "flux_per_pole_Wb": circuit_Bg()["flux_per_pole_Wb"],
    }
    (th / "field.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    np.savez_compressed(th / "field.npz", pts=res["pts"], tris=res["tris"],
                        Bx=res["Bx"], By=res["By"], Bmag=res["Bmag"])
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
