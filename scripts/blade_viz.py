#!/usr/bin/env python
"""2D/3D visualisation for the wind-turbine blade design and BEM results.

Reads  <job>/blade/design.json, <job>/blade/blade.stl, <job>/bem/bem.json
Writes <job>/viz/{distributions.png, cp_tsr.png, power_curve.png,
                  blade_3d.png, blade_3d_rotor.png}

Usage: python blade_viz.py --job <dir>
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    args = ap.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    job = Path(args.job).resolve()
    viz = job / "viz"
    viz.mkdir(parents=True, exist_ok=True)

    design = json.loads((job / "blade" / "design.json").read_text(encoding="utf-8"))
    bem = json.loads((job / "bem" / "bem.json").read_text(encoding="utf-8"))

    rows = design["rows"]
    rR = np.array([x["r_over_R"] for x in rows])
    chord = np.array([x["chord_m"] for x in rows])
    twist = np.array([x["twist_deg"] for x in rows])

    # ---------------- 2D: chord + twist distributions ----------------------
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
    ax[0].plot(rR, chord, "o-", color="tab:blue", ms=3)
    ax[0].set_xlabel("r / R"); ax[0].set_ylabel("chord [m]")
    ax[0].set_title("Blade chord distribution (NACA 5512 sections)")
    ax[0].grid(alpha=0.3)
    ax[1].plot(rR, twist, "s-", color="tab:red", ms=3)
    ax[1].set_xlabel("r / R"); ax[1].set_ylabel("twist [deg]")
    ax[1].set_title("Blade twist distribution")
    ax[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(viz / "distributions.png", dpi=150)
    plt.close(fig)

    # ---------------- 2D: Cp vs TSR ---------------------------------------
    sweep = bem["cp_sweep"]
    tsr = [s["tsr"] for s in sweep]
    cp = [s["cp"] for s in sweep]
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    ax.plot(tsr, cp, "o-", color="tab:green", ms=3, label="local BEM")
    reported = bem["paper"]["reported"]
    ax.plot([reported["Cp_TSR"]], [reported["Cp_max"]], "*", ms=15,
            color="tab:red", label=f"paper: Cp={reported['Cp_max']} @ TSR={reported['Cp_TSR']}")
    ax.axhline(16 / 27, color="0.5", ls="--", lw=1, label="Betz limit 0.593")
    ax.set_xlabel("tip-speed ratio $\\lambda$"); ax.set_ylabel("$C_P$")
    ax.set_title("Power coefficient vs TSR"); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(viz / "cp_tsr.png", dpi=150); plt.close(fig)

    # ---------------- 2D: power curve -------------------------------------
    pc = bem["power_curve"]
    V = [p["V_m_s"] for p in pc]
    P = [p["power_kW"] for p in pc]
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    ax.plot(V, P, "o-", color="tab:blue", label="local BEM (25 rpm)")
    ax.plot([9], [reported["P_9_m_s_kW"]], "*", ms=15, color="tab:red",
            label=f"paper: {reported['P_9_m_s_kW']} kW @ 9 m/s")
    ax.plot([14], [reported["P_14_m_s_kW"]], "*", ms=15, color="tab:orange",
            label=f"paper: {reported['P_14_m_s_kW']} kW @ 14 m/s")
    ax.set_xlabel("wind speed [m/s]"); ax.set_ylabel("power [kW]")
    ax.set_title("Power curve at rated 25 rpm"); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    fig.tight_layout(); fig.savefig(viz / "power_curve.png", dpi=150); plt.close(fig)

    # ---------------- 3D: single blade ------------------------------------
    import pyvista as pv
    pv.OFF_SCREEN = True
    stl = job / "blade" / "blade.stl"
    mesh = pv.read(str(stl))
    # colour by spanwise station (z), plus chord annotation via axes
    plotter = pv.Plotter(off_screen=True, window_size=(1100, 800))
    plotter.add_mesh(mesh, scalars=mesh.points[:, 2], cmap="viridis", show_edges=False,
                     scalar_bar_args={"title": "span z [m]"})
    plotter.add_axes(xlabel="chord x", ylabel="thick y", zlabel="span z")
    # look along -y so the chord/twist silhouette is visible
    plotter.camera_position = "xz"
    plotter.camera.zoom(1.25)
    plotter.screenshot(str(viz / "blade_3d.png"))
    plotter.close()

    # ---------------- 3D: rotor (3 blades, 120 deg apart) ------------------
    plotter = pv.Plotter(off_screen=True, window_size=(1000, 1000))
    colors = ["#4C72B0", "#DD8452", "#55A868"]
    for k in range(3):
        # blade is built along +z; bring it into the rotor plane (x-y) first
        b = mesh.copy().rotate_x(-90.0, point=(0.0, 0.0, 0.0)).rotate_z(120.0 * k, point=(0.0, 0.0, 0.0))
        plotter.add_mesh(b, color=colors[k], show_scalar_bar=False)
    hub = pv.Cylinder(center=(0, 0, 1.5), direction=(0, 0, 1), radius=2.0, height=3.0)
    plotter.add_mesh(hub, color="gray")
    plotter.add_axes()
    plotter.camera_position = "xy"
    plotter.view_isometric()
    plotter.screenshot(str(viz / "blade_3d_rotor.png"))
    plotter.close()

    print(str(viz))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
