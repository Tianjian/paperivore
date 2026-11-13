#!/usr/bin/env python
"""Visualisation + parameter study for the PCB axial-flux PM motor.

Reads  <job>/afpm/{field.npz, afpm.stl, geom.json}
Writes <job>/viz/{afpm_3d.png, field_2d.png, kt_study.png}, <job>/afpm/result.json

Usage: python afpm_viz.py --job <dir>
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

P_PAIRS = 5
R_O, R_I = 0.0095, 0.0035
GAP, PCB_T = 0.00025, 0.0060
H_M = 0.0010
KT_MEAS = 0.0320
R_MEAS = 4.70
BR = 1.30
MU_R_MAG = 1.05
MU0 = 4e-7 * math.pi


def pole_area() -> float:
    return math.pi * (R_O**2 - R_I**2) / (2 * P_PAIRS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    args = ap.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    job = Path(args.job).resolve()
    th, viz = job / "afpm", job / "viz"
    viz.mkdir(exist_ok=True)

    d = np.load(th / "field.npz")
    pts, tris = d["pts"], d["tris"]
    Bmag, Bx, By = d["Bmag"], d["Bx"], d["By"]
    geom = json.loads((th / "geom.json").read_text(encoding="utf-8"))
    field = json.loads((th / "field.json").read_text(encoding="utf-8"))

    # ---------- 2D: field map + gap profile ----------
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.4))
    tpc = ax[0].tripcolor(pts[:, 0] * 1e3, pts[:, 1] * 1e3, tris, Bmag,
                          shading="flat", cmap="jet", vmin=0, vmax=0.8)
    fig.colorbar(tpc, ax=ax[0], label="|B| [T]")
    ax[0].set_xlabel("tangential x [mm]"); ax[0].set_ylabel("axial y [mm]")
    ax[0].set_title("2D magnetostatic field, one pole pair (unrolled at mean radius)")
    ax[0].set_aspect("equal")

    # gap line: elements closest to the PCB mid-plane
    cy = pts[tris, 1].mean(axis=1)
    cx = pts[tris, 0].mean(axis=1)
    sel = np.abs(cy - PCB_T / 2) < (pts[:, 1].max() / 120)
    order = np.argsort(cx[sel])
    ax[1].plot(cx[sel][order] * 1e3, By[sel][order], ".", ms=4, color="tab:blue", label="By (FEA)")
    ax[1].axhline(0, color="0.7", lw=0.8)
    ax[1].set_xlabel("tangential position [mm]"); ax[1].set_ylabel("$B_y$ [T]")
    ax[1].set_title("Air-gap flux density along one pole pair"); ax[1].grid(alpha=0.3)
    ax[1].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(viz / "field_2d.png", dpi=150); plt.close(fig)

    # ---------- Kt study ----------
    A_pole = pole_area()
    h_m = np.linspace(0.0003, 0.004, 60)
    # dual-rotor (TORUS) 1-D circuit: two magnets in series, two gaps, one PCB
    g_eff = 2.0 * GAP + PCB_T
    Bg_circ = 2.0 * BR * h_m / (2.0 * h_m / MU_R_MAG + g_eff)
    n_ph = np.linspace(50, 900, 60)
    N, H = np.meshgrid(n_ph, h_m)
    Bg_grid = 2.0 * BR * H / (2.0 * H / MU_R_MAG + g_eff)
    Kt_grid = 1.5 * P_PAIRS * N * Bg_grid * A_pole

    fig, ax = plt.subplots(1, 2, figsize=(11.5, 4.2))
    ax[0].plot(h_m * 1e3, Bg_circ, "-", color="tab:red", label="magnetic circuit")
    ax[0].axhline(field["Bg_fem_T"], color="tab:blue", ls="--", label="2D FEA")
    ax[0].set_xlabel("magnet thickness [mm]"); ax[0].set_ylabel("$B_g$ [T]")
    ax[0].set_title("Air-gap flux density vs magnet thickness"); ax[0].grid(alpha=0.3); ax[0].legend(fontsize=8)

    cs = ax[1].contourf(N, H * 1e3, Kt_grid * 1e3, levels=20, cmap="viridis")
    fig.colorbar(cs, ax=ax[1], label="$K_t$ [mNm/A]")
    ax[1].contour(N, H * 1e3, Kt_grid * 1e3, levels=[KT_MEAS * 1e3], colors="red", linewidths=1.6)
    ax[1].set_xlabel("series turns per phase $N_{ph}$"); ax[1].set_ylabel("magnet thickness [mm]")
    ax[1].set_title("$K_t$ map; red line = measured 32 mNm/A")
    fig.tight_layout(); fig.savefig(viz / "kt_study.png", dpi=150); plt.close(fig)

    # implied flux / turns from the measured Kt (FEA and 1-D circuit bases)
    Bg_fem = field["Bg_fem_T"]
    Bg_circuit = field["Bg_circuit_T"]
    n_implied = KT_MEAS / (1.5 * P_PAIRS * Bg_fem * A_pole)
    n_implied_circuit = KT_MEAS / (1.5 * P_PAIRS * Bg_circuit * A_pole)
    n_table = 216.0     # 48 layers x 3 turns x 3 coils/phase / 2 parallel (interpretation)

    # ---------- 2D cross-section (r-z) ----------
    fig, ax = plt.subplots(figsize=(7.6, 3.8))
    layers = [
        ("rotor back-iron (S side)", -2.25 - 1.0, 1.0, "#888888"),
        ("magnet S",                 -2.25,       H_M*1e3, "#3366cc"),
        ("air gap 0.25 mm",          -0.25 - GAP*1e3, GAP*1e3, "#dddddd"),
        ("PCB stator 6 mm",          -3.0,        6.0,     "#3b6ea5"),
        ("air gap 0.25 mm",          3.0,         GAP*1e3, "#dddddd"),
        ("magnet N",                 3.25,        H_M*1e3, "#cc3333"),
        ("rotor back-iron (N side)", 4.25,        1.0,     "#888888"),
    ]
    # draw PCB first so the magnets and gaps sit on top of it
    for name, y0, h, col in sorted(layers, key=lambda L: 0 if "PCB" in L[0] else 1):
        ax.add_patch(plt.Rectangle((R_I*1e3, y0), (R_O-R_I)*1e3, h,
                                   facecolor=col, edgecolor="k", lw=0.6, zorder=2))
    ytxt = [ -2.9, -2.2, -0.9, 0.0, 0.9, 3.5, 4.6 ]
    for (name, y0, h, col), yt in zip(layers, ytxt):
        ax.annotate(name, xy=(R_O*1e3 + 0.15, y0 + h/2), xytext=(11.2, yt),
                    fontsize=7, va="center",
                    arrowprops=dict(arrowstyle="-", lw=0.5, color="0.5"))
    ax.set_xlim(0, 16); ax.set_ylim(-4.5, 6.0)
    ax.set_xlabel("radius [mm]"); ax.set_ylabel("axial position [mm]")
    ax.set_title("AFPM layer stack (r-z section)")
    ax.grid(alpha=0.25)
    fig.tight_layout(); fig.savefig(viz / "section_2d.png", dpi=150); plt.close(fig)

    # ---------- 3D assembly ----------
    import pyvista as pv
    pv.OFF_SCREEN = True
    p = pv.Plotter(off_screen=True, window_size=(1100, 800))
    # stator PCB (semi-transparent disc)
    pcb = pv.Cylinder(center=(0, 0, 0), direction=(0, 0, 1), radius=R_O, height=PCB_T)
    p.add_mesh(pcb, color="#3b6ea5", opacity=0.30)
    # magnets on both sides
    hw = (R_O - R_I) * 0.46
    hh = 2 * math.pi * (R_O + R_I) / 2 / (2 * P_PAIRS) * 0.44
    for side, zoff in (("top", PCB_T / 2 + GAP + H_M / 2), ("bot", -PCB_T / 2 - GAP - H_M / 2)):
        for k in range(2 * P_PAIRS):
            ang = 360.0 / (2 * P_PAIRS) * k
            m = pv.Box(bounds=(-hw, hw, -hh, hh, -H_M / 2, H_M / 2))
            m.translate(((R_O + R_I) / 2, 0, zoff), inplace=True)
            m.rotate_z(ang, point=(0, 0, 0), inplace=True)
            # rotate the box so it sits on the radius
            p.add_mesh(m, color=("#cc3333" if (k % 2 == 0) == (side == "top") else "#3366cc"),
                       opacity=0.95)
    # rotor discs
    for zoff in (PCB_T / 2 + GAP + H_M + 0.0005, -PCB_T / 2 - GAP - H_M - 0.0005):
        disc = pv.Cylinder(center=(0, 0, zoff), direction=(0, 0, 1), radius=R_O, height=0.001)
        p.add_mesh(disc, color="#b0b0b0", opacity=0.85)
    p.add_axes()
    p.camera_position = "iso"
    p.camera.zoom(1.25)
    p.screenshot(str(viz / "afpm_3d.png"))
    p.close()

    # exploded view
    p = pv.Plotter(off_screen=True, window_size=(1100, 800))
    for zoff, col in ((0.012, "#b0b0b0"), (0.006, "#cc3333"), (0.0, "#3b6ea5")):
        disc = pv.Cylinder(center=(0, 0, zoff), direction=(0, 0, 1), radius=R_O, height=0.0015)
        p.add_mesh(disc, color=col, opacity=0.9)
    p.add_axes()
    p.camera_position = "iso"
    p.camera.zoom(1.3)
    p.screenshot(str(viz / "afpm_exploded.png"))
    p.close()

    result = {
        "paper": {"doi": "arXiv:2509.23561", "Kt_meas_mNm_A": 32.0, "R_meas_ohm": 4.70,
                  "T_stall_mNm": 158, "I_stall_A": 5.95},
        "geometry": geom,
        "topology_note": "dual-rotor TORUS 1-D circuit: 2 magnets in series, 2 gaps, 1 PCB",
        "Bg_fem_T": round(Bg_fem, 4),
        "Bg_circuit_T": round(Bg_circuit, 4),
        "flux_per_pole_fem_Wb": round(Bg_fem * A_pole, 10),
        "flux_per_pole_circuit_Wb": round(Bg_circuit * A_pole, 10),
        "Kt_at_N216_fem_mNm_A": round(1.5 * P_PAIRS * n_table * Bg_fem * A_pole * 1e3, 3),
        "Kt_at_N216_circuit_mNm_A": round(1.5 * P_PAIRS * n_table * Bg_circuit * A_pole * 1e3, 3),
        "N_implied_from_meas_fem": round(n_implied, 1),
        "N_implied_from_meas_circuit": round(n_implied_circuit, 1),
        "N_from_table": n_table,
    }
    (th / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False)[:900])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
