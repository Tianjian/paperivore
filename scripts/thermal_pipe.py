#!/usr/bin/env python
"""Exhaust-pipe temperature field: CalculiX thermal FEA vs exact 1D solution.

Reference geometry / material (open access paper)
-------------------------------------------------
S. D. Petković, R. B. Pešić, J. K. Lukić, "Heat Transfer in Exhaust System of a
Cold Start Engine at Low Environmental Temperature", Thermal Science 14 (Suppl.),
S219-S232, 2010.  Table 1, element 1 (exhaust pipe):
    L = 200 mm, D = 39 mm, wall 1.5 mm, Č.4571, rho = 7900 kg/m3,
    lambda = 15 W/mK, c = 477 J/kgK.

The paper models a cold start with a system-level finite-difference scheme over
pipe + pre-catalyst + muffler; its output is a temperature-vs-time curve for
several components, not a per-point field.  So the quantitative check here is
made against the exact 1D solution for the same geometry and boundary
conditions, and the paper supplies geometry, material and the physical scenario.

Model (SI units: m, N, Pa, kg, s, K)
------------------------------------
    pipe r_i = 0.018 m, r_o = 0.0195 m, L = 0.2 m, k = 15 W/mK
    inner: gas 500 C at inlet, cooling linearly to 350 C at outlet,
           h_i = 100 W/m2K  (10 axial segments, so the field has an axial gradient)
    outer: ambient 20 C, h_o = 10 W/m2K

Exact solution per segment (two convection boundaries):
    R_i = 1/(h_i 2 pi r_i dz), R_w = ln(r_o/r_i)/(2 pi k dz), R_o = 1/(h_o 2 pi r_o dz)
    q   = (T_gas - T_amb)/(R_i+R_w+R_o)
    T_wi = T_gas - q R_i,   T_wo = T_amb + q R_o

Usage:
    python thermal_pipe.py mesh --job <dir> [--h 0.0025] [--seg 10]
    <msys>\\ccx_i8.exe -i steady
    python thermal_pipe.py post --job <dir>
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

R_I = 0.018
R_O = 0.0195
L = 0.2
K_W_MK = 15.0
RHO = 7900.0
CP = 477.0
T_GAS_IN = 500.0
T_GAS_OUT = 350.0
T_AMB = 20.0
H_I = 100.0
H_O = 10.0
NSEG = 10


def gas_temperature(z: float) -> float:
    return T_GAS_IN + (T_GAS_OUT - T_GAS_IN) * (z / L)


def analytic_segment(z_mid: float, dz: float) -> dict:
    ri, ro = R_I, R_O
    tg = gas_temperature(z_mid)
    R_i = 1.0 / (H_I * 2 * math.pi * ri * dz)
    R_w = math.log(ro / ri) / (2 * math.pi * K_W_MK * dz)
    R_o = 1.0 / (H_O * 2 * math.pi * ro * dz)
    q = (tg - T_AMB) / (R_i + R_w + R_o)
    return {
        "z_m": round(z_mid, 4), "T_gas_C": round(tg, 2),
        "T_wall_inner_C": round(tg - q * R_i, 3),
        "T_wall_outer_C": round(T_AMB + q * R_o, 3),
        "q_W": round(q, 3),
    }


def build_mesh(job: Path, h: float, nseg: int, t_in: float | None = None,
               t_out: float | None = None) -> int:
    global T_GAS_IN, T_GAS_OUT
    if t_in is not None:
        T_GAS_IN = t_in
    if t_out is not None:
        T_GAS_OUT = t_out
    th = job / "thermal"
    th.mkdir(parents=True, exist_ok=True)
    step = th / "pipe.step"
    if not step.exists():
        # build123d 只在需要生成几何时导入：已有 pipe.step 的用户（例如没有
        # CAD 内核的 Linux 环境）只需 gmsh，不必装 OCCT。
        from build123d import Cylinder, Pos, export_step

        outer = Pos(0, 0, L / 2) * Cylinder(R_O, L, align=(None, None, None))
        inner = Pos(0, 0, L / 2) * Cylinder(R_I, L * 1.2, align=(None, None, None))
        export_step(outer - inner, str(step))
    import gmsh

    gmsh.initialize(["gmsh", "-v", "2"])
    try:
        gmsh.model.add("pipe")
        gmsh.model.occ.importShapes(str(step))
        gmsh.model.occ.synchronize()
        vols = gmsh.model.getEntities(3)
        gmsh.model.addPhysicalGroup(3, [t for _, t in vols], name="SOLID")
        gmsh.option.setNumber("Mesh.MeshSizeMax", h)
        gmsh.model.mesh.generate(3)
        gmsh.write(str(th / "pipe_mesh.inp"))
    finally:
        gmsh.finalize()

    raw = (th / "pipe_mesh.inp").read_text(encoding="ascii", errors="replace").splitlines()
    nodes, tets, in_nodes, mode = {}, [], False, None
    for line in raw:
        s = line.strip()
        if s.startswith("*"):
            in_nodes = s.upper().startswith("*NODE")
            mode = "elem" if s.upper().startswith("*ELEMENT") else None
            continue
        if in_nodes and s:
            p = [x for x in s.split(",") if x.strip()]
            if len(p) >= 4:
                nodes[int(p[0])] = tuple(float(v) for v in p[1:4])
        elif mode == "elem" and s:
            p = [x for x in s.split(",") if x.strip()]
            if len(p) >= 5:
                tets.append([int(x) for x in p[1:]])

    def rad(n):
        x, y, _ = nodes[n]
        return math.hypot(x, y)

    z_min = min(v[2] for v in nodes.values())

    faces = {1: (0, 1, 2), 2: (0, 1, 3), 3: (1, 2, 3), 4: (0, 2, 3)}
    dz = L / nseg
    film_in, film_out = [], []
    for eid, conn in enumerate(tets, start=1):
        for fno, idx in faces.items():
            tri = [conn[i] for i in idx]
            rr = [rad(n) for n in tri]
            zc = sum(nodes[n][2] for n in tri) / 3.0 - z_min
            if all(abs(r - R_I) < 2e-5 for r in rr):
                film_in.append((eid, fno, zc))
                break
            if all(abs(r - R_O) < 2e-5 for r in rr):
                film_out.append((eid, fno, zc))
                break

    deck = ["\n".join(raw).rstrip(), "*NSET, NSET=NALL"]
    for k in range(0, len(nodes), 10):
        deck.append(", ".join(str(i) for i in sorted(nodes)[k:k + 10]))
    deck += [
        "*MATERIAL, NAME=STEEL4571",
        "*CONDUCTIVITY", f"{K_W_MK}",
        "*DENSITY", f"{RHO}",
        "*SPECIFIC HEAT", f"{CP}",
        "*SOLID SECTION, ELSET=SOLID, MATERIAL=STEEL4571",
        "*STEP", "*HEAT TRANSFER, STEADY STATE",
        "*FILM",
        *[f"{e}, F{f}, {gas_temperature(z):.4f}, {H_I}" for e, f, z in film_in],
        *[f"{e}, F{f}, {T_AMB}, {H_O}" for e, f, z in film_out],
        "*NODE FILE", "NT",
        "*END STEP",
    ]
    (th / "steady.inp").write_text("\n".join(deck) + "\n", encoding="ascii")

    seg = [analytic_segment((i + 0.5) * dz, dz) for i in range(nseg)]
    info = {
        "nodes": len(nodes), "elements": len(tets),
        "inner_faces": len(film_in), "outer_faces": len(film_out),
        "geometry": {"r_i": R_I, "r_o": R_O, "L": L},
        "material": {"k_W_mK": K_W_MK, "rho_kg_m3": RHO, "cp_J_kgK": CP},
        "bc": {"T_gas_in_C": T_GAS_IN, "T_gas_out_C": T_GAS_OUT,
               "h_i": H_I, "T_amb_C": T_AMB, "h_o": H_O, "segments": nseg},
        "analytic_segments": seg,
    }
    (th / "mesh.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: info[k] for k in ("nodes", "elements", "inner_faces", "outer_faces")},
                     ensure_ascii=False))
    return 0


def fin_reference(n: int = 401, t_in: float | None = None,
                  t_out: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """1-D fin solution INCLUDING axial conduction (adiabatic ends), closed form.

    k A_c T'' = h_o P_o (T - T_amb) + h_i P_i (T - T_gas(x)),  T_gas linear
    ->  T'' - m^2 T = -m^2 (A + B x),  m^2 = (h_o P_o + h_i P_i)/(k A_c)
    Particular solution is A + B x (the gas profile), plus two exponentials
    fixed by the adiabatic end conditions. Closed form avoids the ill-conditioned
    finite-difference system (b - 2 ~ 1e-3).
    """
    A_c = math.pi * (R_O**2 - R_I**2)
    P_o = 2 * math.pi * R_O
    P_i = 2 * math.pi * R_I
    hP = H_O * P_o + H_I * P_i
    tg_in = T_GAS_IN if t_in is None else t_in
    tg_out = T_GAS_OUT if t_out is None else t_out
    m = math.sqrt(hP / (K_W_MK * A_c))
    A = (H_O * P_o * T_AMB + H_I * P_i * tg_in) / hP
    B = H_I * P_i * (tg_out - tg_in) / (L * hP)
    # T = A + B x + C e^{mx} + D e^{-mx};  T'(0)=0, T'(L)=0
    emL = math.exp(m * L)
    emmL = math.exp(-m * L)
    # B + mC - mD = 0
    # B + mC emL - mD emmL = 0
    # =>  mC (emL - 1) - mD (emmL - 1) = 0  and  mC - mD = -B
    # solve 2x2: [1, -1; (emL-1), -(emmL-1)] [mC, mD] = [-B, 0]
    det = -(emmL - 1) + (emL - 1)
    mC = (-B * (-(emmL - 1)) - (-1) * 0) / det
    mD = (1 * 0 - (-B) * (emL - 1)) / det
    C, D = mC / m, mD / m
    x = np.linspace(0.0, L, n)
    T = A + B * x + C * np.exp(m * x) + D * np.exp(-m * x)
    return x, T
def _read_temperature(frd: Path) -> dict[int, float]:
    out, cur = {}, None
    for line in frd.read_text(encoding="ascii", errors="replace").splitlines():
        s = line.rstrip()
        if "100CL" in s:
            cur = None
            continue
        if s.startswith(" -4"):
            cur = "T" if ("NDTEMP" in s.upper() or "TEMP" in s.upper()) else None
            continue
        if s.startswith(" -3"):
            cur = None
            continue
        if cur and (s.startswith(" -1") or s.startswith(" -2")):
            try:
                out[int(s[3:13].strip())] = float(s[13:25].strip())
            except ValueError:
                pass
    return out


def post(job: Path) -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pyvista as pv

    th = job / "thermal"
    viz = job / "viz"
    viz.mkdir(exist_ok=True)
    info = json.loads((th / "mesh.json").read_text(encoding="utf-8"))
    Ts = _read_temperature(th / "steady.frd")

    nodes, in_nodes = {}, False
    for line in (th / "steady.inp").read_text(encoding="ascii", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("*"):
            in_nodes = s.upper().startswith("*NODE")
            continue
        if in_nodes and s:
            p = [x for x in s.split(",") if x.strip()]
            if len(p) >= 4:
                try:
                    nodes[int(p[0])] = tuple(float(v) for v in p[1:4])
                except ValueError:
                    pass

    dz = L / info["bc"]["segments"]
    zmin_n = min(v[2] for v in nodes.values())
    fin_x, fin_T = fin_reference(t_in=info["bc"]["T_gas_in_C"],
                                 t_out=info["bc"]["T_gas_out_C"])
    rows = []
    for i, seg in enumerate(info["analytic_segments"]):
        z0, z1 = i * dz, (i + 1) * dz
        # use the axial coordinate relative to the pipe inlet and drop the end
        # caps (they are adiabatic and would bias the segment averages)
        sel = [n for n in nodes
               if z0 <= (nodes[n][2] - zmin_n) < z1
               and 1e-6 < (nodes[n][2] - zmin_n) < L - 1e-6 and n in Ts]
        ri_nodes = [n for n in sel if abs(math.hypot(*nodes[n][:2]) - R_I) < 2e-5]
        ro_nodes = [n for n in sel if abs(math.hypot(*nodes[n][:2]) - R_O) < 2e-5]
        twi = float(np.mean([Ts[n] for n in ri_nodes])) if ri_nodes else float("nan")
        two = float(np.mean([Ts[n] for n in ro_nodes])) if ro_nodes else float("nan")
        rows.append({
            "z_m": seg["z_m"], "T_gas_C": seg["T_gas_C"],
            "fin_C": round(float(fin_T[np.argmin(np.abs(fin_x - seg["z_m"]))]), 3),
            "fea_inner_C": round(twi, 3), "ana_inner_C": seg["T_wall_inner_C"],
            "fea_outer_C": round(two, 3), "ana_outer_C": seg["T_wall_outer_C"],
            "err_inner_pct": round(abs(twi - seg["T_wall_inner_C"]) / seg["T_wall_inner_C"] * 100, 3),
            "err_outer_pct": round(abs(two - seg["T_wall_outer_C"]) / seg["T_wall_outer_C"] * 100, 3),
        })

    for r in rows:
        r["err_fin_pct"] = round(abs(r["fea_inner_C"] - r["fin_C"]) / r["fin_C"] * 100, 3)
    result = {"segments": rows,
              "max_err_inner_pct": max(r["err_inner_pct"] for r in rows),
              "max_err_outer_pct": max(r["err_outer_pct"] for r in rows),
              "max_err_fin_pct": max(r["err_fin_pct"] for r in rows)}

    z = [r["z_m"] * 1e3 for r in rows]
    fig, ax = plt.subplots(1, 2, figsize=(11.5, 4.2))
    ax[0].plot([x * 1e3 for x in fin_x], fin_T, "-", color="0.35", lw=1.5,
               label="fin solution (with axial conduction)")
    ax[0].plot(z, [r["ana_inner_C"] for r in rows], "k:", label="1D radial only")
    ax[0].plot(z, [r["fea_inner_C"] for r in rows], "o", ms=5, label="FEA inner")
    ax[0].plot(z, [r["ana_outer_C"] for r in rows], "k--", label="1D radial only (outer)")
    ax[0].plot(z, [r["fea_outer_C"] for r in rows], "s", ms=5, label="FEA outer")
    ax[0].set_xlabel("axial position [mm]"); ax[0].set_ylabel("wall temperature [C]")
    ax[0].set_title("Pipe wall temperature along the axis"); ax[0].grid(alpha=0.3); ax[0].legend(fontsize=8)
    ax[1].plot(z, [r["T_gas_C"] for r in rows], "r-", label="gas (imposed)")
    ax[1].plot(z, [r["fea_inner_C"] for r in rows], "o-", ms=3, label="wall inner")
    ax[1].plot(z, [r["fea_outer_C"] for r in rows], "s-", ms=3, label="wall outer")
    ax[1].set_xlabel("axial position [mm]"); ax[1].set_ylabel("temperature [C]")
    ax[1].set_title("Temperature field summary"); ax[1].grid(alpha=0.3); ax[1].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(viz / "thermal_2d.png", dpi=150); plt.close(fig)

    # surface mesh from the tetrahedra (solid, not a point cloud)
    tets3 = []
    mode_e = False
    for line in (th / "pipe_mesh.inp").read_text(encoding="ascii", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("*"):
            mode_e = s.upper().startswith("*ELEMENT")
            continue
        if mode_e and s:
            q = [x for x in s.split(",") if x.strip()]
            if len(q) >= 5:
                tets3.append([int(x) for x in q[1:5]])
    ids = sorted(nodes)
    index = {n: i for i, n in enumerate(ids)}
    pts = np.array([nodes[n] for n in ids])
    cells = np.array([[4, index[a], index[b], index[c], index[d]] for a, b, c, d in tets3]).ravel()
    celltypes = np.full(len(tets3), pv.CellType.TETRA, dtype=np.uint8)
    grid = pv.UnstructuredGrid(cells, celltypes, pts)
    grid.point_data["T"] = np.array([Ts.get(n, np.nan) for n in ids])
    surf3 = grid.extract_surface()

    pv.OFF_SCREEN = True
    p = pv.Plotter(off_screen=True, window_size=(1000, 760))
    p.add_mesh(surf3, scalars="T", cmap="coolwarm", smooth_shading=True,
               scalar_bar_args={"title": "T [C]"})
    p.add_axes()
    p.camera_position = "iso"
    p.camera.zoom(1.2)
    p.screenshot(str(viz / "thermal_3d.png"))
    p.close()

    # cut-away half section: shows the radial gradient through the wall
    p = pv.Plotter(off_screen=True, window_size=(1000, 760))
    half = grid.clip("x", value=0.0, invert=True)
    p.add_mesh(half.extract_surface(), scalars="T", cmap="coolwarm", smooth_shading=True,
               scalar_bar_args={"title": "T [C]"})
    p.add_axes()
    p.camera_position = "iso"
    p.camera.zoom(1.2)
    p.screenshot(str(viz / "thermal_3d_cut.png"))
    p.close()

    (th / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"max_err_inner_pct": result["max_err_inner_pct"],
                      "max_err_outer_pct": result["max_err_outer_pct"],
                      "max_err_fin_pct": result["max_err_fin_pct"],
                      "first": rows[0], "last": rows[-1]}, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mesh"); m.add_argument("--job", required=True)
    m.add_argument("--h", type=float, default=0.0025); m.add_argument("--seg", type=int, default=10)
    m.add_argument("--tgas-in", type=float, default=None)
    m.add_argument("--tgas-out", type=float, default=None)
    sub.add_parser("post").add_argument("--job", required=True)
    args = ap.parse_args()
    job = Path(args.job).resolve()
    return (build_mesh(job, args.h, args.seg, args.tgas_in, args.tgas_out)
            if args.cmd == "mesh" else post(job))


if __name__ == "__main__":
    raise SystemExit(main())
