#!/usr/bin/env python
"""Wind-turbine blade structural check: CalculiX FEA under centrifugal + aero load.

Model
-----
* geometry: <job>/blade/blade.step (lofted NACA 5512 sections, real chord/twist)
* material: GFRP equivalent, E = 25 GPa, nu = 0.3, rho = 1900 kg/m3 (solid idealisation)
* loads:
    - centrifugal: *DLOAD CENTRIF at 25 rpm about the blade axis (z)
    - aerodynamic: nodal flapwise forces (through-thickness +y) from the BEM thrust
* boundary: root face (z = z_min) fully fixed

Usage:
    python blade_fea.py mesh --job <dir> [--h 0.9]
    <msys>\\ccx_i8.exe -i blade        (run in <dir>/fea)
    python blade_fea.py post --job <dir>
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

E_MPA = 25000.0
NU = 0.30
RHO_T_MM3 = 1.9e-9
OMEGA = 25.0 * 2.0 * math.pi / 60.0


def build_deck(job: Path, h: float) -> int:
    import gmsh

    fea = job / "fea"
    fea.mkdir(parents=True, exist_ok=True)
    step = job / "blade" / "blade.step"
    if not step.exists():
        raise SystemExit(f"ERROR: missing {step}")

    # 1) mesh with gmsh and let gmsh write the Abaqus deck (correct C3D4 order)
    gmsh.initialize(["gmsh", "-v", "2"])
    try:
        gmsh.model.add("blade")
        gmsh.model.occ.importShapes(str(step))
        gmsh.model.occ.synchronize()
        vols = gmsh.model.getEntities(3)
        gmsh.model.addPhysicalGroup(3, [tg for _, tg in vols], name="SOLID")
        gmsh.option.setNumber("Mesh.MeshSizeMax", h)
        gmsh.model.mesh.generate(3)
        gmsh.write(str(fea / "blade_mesh.inp"))
    finally:
        gmsh.finalize()

    # 2) parse nodes and scale the mesh from metres to mm (CalculiX data is in MPa)
    raw = (fea / "blade_mesh.inp").read_text(encoding="ascii", errors="replace").splitlines()
    coords, scaled, in_nodes = {}, [], False
    for line in raw:
        s = line.strip()
        if s.startswith("*"):
            in_nodes = s.upper().startswith("*NODE")
            scaled.append(line)
            continue
        if in_nodes and s:
            parts = [x for x in s.split(",") if x.strip()]
            if len(parts) >= 4:
                try:
                    x, y, z = (float(parts[1]) * 1e3, float(parts[2]) * 1e3, float(parts[3]) * 1e3)
                    coords[int(parts[0])] = (x, y, z)
                    scaled.append(f"{parts[0]}, {x:.9g}, {y:.9g}, {z:.9g}")
                    continue
                except ValueError:
                    pass
        scaled.append(line)

    if not coords:
        raise SystemExit("ERROR: no nodes parsed from gmsh deck")

    zmin = min(c[2] for c in coords.values())
    zmax = max(c[2] for c in coords.values())
    root = [n for n, c in coords.items() if abs(c[2] - zmin) < 1e-6]
    n_elem, in_elem = 0, False
    for raw_line in raw:
        text_line = raw_line.strip()
        if not text_line:
            continue
        if text_line.startswith("*"):
            in_elem = text_line.upper().startswith("*ELEMENT")
            continue
        if in_elem:
            n_elem += 1

    # 3) aero load: per-node weights normalised to the BEM thrust per blade
    bem = json.loads((job / "bem" / "bem.json").read_text(encoding="utf-8"))
    at9 = next(p for p in bem["power_curve"] if p["V_m_s"] == 9)
    thrust = at9["thrust_kN"] * 1e3 / 3.0

    ids = [n for n in coords if abs(coords[n][2] - zmin) >= 1e-6]
    zs = np.array([coords[n][2] for n in ids])
    w = np.sin(np.pi * (zs - zmin) / (zmax - zmin)) + 0.2
    w = w / w.sum() * thrust

    # The blade is twisted, so the flapwise direction is normal to the LOCAL chord,
    # not to the global y axis. Rotate the force by the local twist angle.
    design = json.loads((job / "blade" / "design.json").read_text(encoding="utf-8"))
    zt = np.array([row["r_m"] for row in design["rows"]]) * 1000.0
    tw = np.array([row["twist_deg"] for row in design["rows"]])
    theta = np.radians(np.interp(zs, zt, tw))
    cload = []
    for n, f, th in zip(ids, w, theta):
        cload.append(f"{n}, 1, {-f * math.sin(th):.6g}")
        cload.append(f"{n}, 2, {f * math.cos(th):.6g}")

    # 4) deck = scaled mesh + sets + material + step + loads
    deck = ["\n".join(scaled).rstrip(), "*NSET, NSET=NROOT"]
    for k in range(0, len(root), 10):
        deck.append(", ".join(str(i) for i in root[k:k + 10]))
    deck += [
        "*MATERIAL, NAME=GFRP",
        "*ELASTIC", f"{E_MPA}, {NU}",
        "*DENSITY", f"{RHO_T_MM3:.6g}",
        "*SOLID SECTION, ELSET=SOLID, MATERIAL=GFRP",
        "*STEP", "*STATIC",
        "*BOUNDARY", "NROOT, 1, 3, 0.0",
        "*DLOAD", f"SOLID, CENTRIF, {OMEGA**2:.6g}, 0., 0., 0., 0., 0., 1.",
        "*CLOAD", *cload,
        "*NODE FILE", "U",
        "*EL FILE", "S",
        "*END STEP",
    ]
    (fea / "blade.inp").write_text("\n".join(deck) + "\n", encoding="ascii")

    info = {
        "nodes": len(coords), "elements": n_elem, "element_type": "C3D4",
        "mesh_size_m": h, "root_nodes": len(root),
        "thrust_per_blade_N": round(thrust, 1),
        "cload_sum_N": round(float(w.sum()), 1),
        "omega_rad_s": round(OMEGA, 4), "rpm": 25.0,
        "z_range_mm": [round(zmin, 2), round(zmax, 2)],
    }
    (fea / "mesh.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))
    return 0


def post(job: Path) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import frd_reader
    import pyvista as pv

    fea = job / "fea"
    frd = fea / "blade.frd"
    if not frd.exists():
        raise SystemExit(f"ERROR: missing {frd}; run ccx_i8 -i blade in {fea}")

    res = frd_reader.read_frd_results(frd)
    nodes, elements = frd_reader.read_inp_mesh(fea / "blade.inp")
    disp = res.get("DISP", {})
    stress = res.get("STRESS", {})

    zmax = max(c[2] for c in nodes.values())
    tip = [n for n, c in nodes.items() if abs(c[2] - zmax) < 5.0 and n in disp]
    tip_u = max(math.sqrt(sum(v * v for v in disp[n][:3])) for n in tip) if tip else float("nan")

    vm = []
    for s in stress.values():
        if len(s) >= 6:
            vm.append(0.5 * ((s[0] - s[1]) ** 2 + (s[1] - s[2]) ** 2 + (s[2] - s[0]) ** 2)
                      + 3 * (s[3] ** 2 + s[4] ** 2 + s[5] ** 2))
    max_vm = math.sqrt(max(vm)) if vm else float("nan")

    grid = frd_reader.build_vtk(fea, nodes, elements, disp, stress)[1]
    surf = grid.extract_surface()
    (job / "viz").mkdir(exist_ok=True)
    pv.OFF_SCREEN = True

    # (a) stress contour on the undeformed surface
    p = pv.Plotter(off_screen=True, window_size=(1100, 800))
    p.add_mesh(surf, scalars="S_vm", cmap="turbo", smooth_shading=True,
               clim=(0.0, 10.0), scalar_bar_args={"title": "von Mises [MPa]"})
    p.add_axes()
    p.camera_position = [(26000, -26000, 16000), (0, 0, 14000), (0, 0, 1)]
    p.camera.zoom(1.15)
    p.screenshot(str(job / "viz" / "stress_3d.png"))
    p.close()

    # (b) deformed shape (x20) coloured by displacement magnitude
    warped = surf.warp_by_vector("U", factor=20.0)
    p = pv.Plotter(off_screen=True, window_size=(1100, 800))
    p.add_mesh(warped, scalars="U_mag", cmap="viridis", smooth_shading=True,
               scalar_bar_args={"title": "|U| [mm] (x20)"})
    p.add_axes()
    p.camera_position = [(26000, -26000, 16000), (0, 0, 14000), (0, 0, 1)]
    p.camera.zoom(1.15)
    p.screenshot(str(job / "viz" / "deformed_3d.png"))
    p.close()

    info = {
        "tip_deflection_m": round(tip_u / 1000.0, 4),
        "tip_deflection_mm": round(tip_u, 2),
        "max_vm_stress_MPa": round(max_vm, 2),
        "tip_nodes": len(tip),
        "stress_3d": str(job / "viz" / "stress_3d.png"),
        "deformed_3d": str(job / "viz" / "deformed_3d.png"),
    }
    (fea / "result.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mesh"); m.add_argument("--job", required=True); m.add_argument("--h", type=float, default=0.9)
    p = sub.add_parser("post"); p.add_argument("--job", required=True)
    args = ap.parse_args()
    job = Path(args.job).resolve()
    return build_deck(job, args.h) if args.cmd == "mesh" else post(job)


if __name__ == "__main__":
    raise SystemExit(main())
