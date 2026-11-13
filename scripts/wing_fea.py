#!/usr/bin/env python
"""S3 of the airfoil validation: UAV wing spar FEA vs Euler-Bernoulli beam theory.

Wing idealisation: the primary bending member is a hollow rectangular CFRP wing
box (D-box), fixed at the root and loaded by the lift distributed over the span.
The point is to validate the structural chain (geometry -> mesh -> CalculiX ->
post) against a closed-form solution.

Design point (from the reference airfoil study):
    NACA 4412, chord c = 0.30 m, span b = 1.20 m
    Cl = 1.791092, V = 30 m/s, rho = 1.225 kg/m3
    q = 0.5*rho*V^2*Cl*c = 296.2 N/m, L = q*b = 355.4 N

Reference (Euler-Bernoulli):
    delta_tip = q*b^4/(8*E*I)
    sigma_root = (q*b^2/2)*(h/2)/I

Steps:
    python wing_fea.py design --job <dir>      # writes wing/design.json + wing/box.geo
    python wing_fea.py mesh   --job <dir>      # gmsh -> wing/job.inp + wing/groups.json
    <msys>\\ccx_i8.exe -i job                 # run in <dir>/wing
    python wing_fea.py post   --job <dir>      # wing/result.json + comparison

Usage:
    python wing_fea.py design --job runs/uav-wing-01
    python wing_fea.py mesh   --job runs/uav-wing-01
    python wing_fea.py post   --job runs/uav-wing-01
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------- #
# design
# --------------------------------------------------------------------------- #
def design_point(cl=1.791092, v=30.0, chord=0.30, span=1.20, rho=1.225):
    q = 0.5 * rho * v**2 * cl * chord
    return {
        "cl": cl, "v_m_s": v, "chord_m": chord, "span_m": span, "rho": rho,
        "dynamic_pressure_Pa": round(0.5 * rho * v**2, 3),
        "lift_per_span_N_m": round(q, 3),
        "total_lift_N": round(q * span, 3),
    }


def section(width=0.30, height=0.040, wall=0.003):
    bi, hi = width - 2 * wall, height - 2 * wall
    I = (width * height**3 - bi * hi**3) / 12.0
    return {
        "width_m": width, "height_m": height, "wall_m": wall,
        "area_m2": width * height - bi * hi, "I_m4": I,
        "section_modulus_m3": I / (height / 2.0),
    }


def beam_theory(d, s, E):
    q, b, I = d["lift_per_span_N_m"], d["span_m"], s["I_m4"]
    delta = q * b**4 / (8.0 * E * I)
    M = q * b**2 / 2.0
    sigma = M * (s["height_m"] / 2.0) / I
    return {
        "tip_deflection_mm": round(delta * 1e3, 4),
        "root_moment_Nm": round(M, 2),
        "root_bending_stress_MPa": round(sigma / 1e6, 4),
        "deflection_span_ratio": round(delta / b, 6),
    }


def write_geo(path: Path, width, height, wall, span, h):
    """Kept for documentation only: the actual meshing uses the gmsh OCC API.

    The .geo text syntax differs between gmsh versions (`BooleanDifference{...}`
    vs `BooleanDifference(3) = {...}{...}`), which broke reproducibly.  Driving
    `gmsh.model.occ.cut()` from Python avoids that grammar entirely.
    """
    bi, hi = width - 2 * wall, height - 2 * wall
    geo = f"""// hollow wing box, units = m (reference only; mesh uses the OCC API)
Box(1) = {{0, 0, 0, {width}, {height}, {span}}};
Box(2) = {{{wall}, {wall}, {wall}, {bi}, {hi}, {span - 2*wall}}};
// cut inner from outer via gmsh.model.occ.cut in wing_fea.py
"""
    path.write_text(geo, encoding="ascii")


# --------------------------------------------------------------------------- #
# mesh -> CalculiX deck
# --------------------------------------------------------------------------- #
def build_deck(job: Path, d, s, E, nu, rho_mat, load_mode: str = "body"):
    """Read the gmsh .msh (v2 ASCII) and write an Abaqus/CalculiX deck.

    Units: mm, N, MPa, t, s.  Two equivalent ways to apply the same lift q [N/m]:
      * load_mode="body"     : *DLOAD GRAV with an effective density chosen so that
                               rho_eff * g * A = q.  Convenient, but it applies the
                               transverse "inertia" to *all* walls, which adds a
                               model artefact of about +3 pp to the tip deflection
                               (measured: 1.8353 mm body vs 1.7794 mm pressure on the
                               same mesh).  Kept as the default only so the stored
                               artefacts stay reproducible.
      * load_mode="pressure" : *DLOAD P on the top skin faces.  Closer to the real
                               skin loading and therefore the recommended setting
                               for new runs/comparisons (small local wall bending at
                               the load application is a physical effect, not a bug).
    """
    msh = job / "wing" / "mesh.msh"
    if not msh.exists():
        raise SystemExit(f"ERROR: missing {msh}")

    # --- minimal MSH2 reader -------------------------------------------------
    text = msh.read_text(encoding="ascii", errors="replace").splitlines()
    nodes, elems = {}, []
    i = 0
    while i < len(text):
        line = text[i].strip()
        if line == "$Nodes":
            n = int(text[i + 1].strip())
            for k in range(n):
                p = text[i + 2 + k].split()
                nodes[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
            i += 2 + n
            continue
        if line == "$Elements":
            n = int(text[i + 1].strip())
            for k in range(n):
                p = [int(x) for x in text[i + 2 + k].split()]
                # p = [id, type, ntags, tag..., nodes...]
                etype, ntags = p[1], p[2]
                conn = p[3 + ntags:]
                elems.append((etype, conn))
            i += 2 + n
            continue
        i += 1

    tetra_types = {4: 4, 11: 10}      # gmsh type -> nodes per element
    used = [e for e in elems if e[0] in tetra_types]
    if not used:
        raise SystemExit("ERROR: no tetrahedra in mesh")
    npe = tetra_types[used[0][0]]
    ctype = "C3D4" if npe == 4 else "C3D10"

    # --- coordinate transform: m -> mm, z is the span -----------------------
    coords = {nid: (x * 1e3, y * 1e3, z * 1e3) for nid, (x, y, z) in nodes.items()}

    # --- node sets by geometry ---------------------------------------------
    zs = [c[2] for c in coords.values()]
    ys = [c[1] for c in coords.values()]
    zmin, zmax = min(zs), max(zs)
    ymax = max(ys)
    tol = 1e-6
    root_nodes = sorted(n for n, c in coords.items() if abs(c[2] - zmin) < tol)
    tip_nodes = sorted(n for n, c in coords.items() if abs(c[2] - zmax) < tol)
    top_nodes = sorted(n for n, c in coords.items() if abs(c[1] - ymax) < tol)

    # --- deck ---------------------------------------------------------------
    width, height = s["width_m"] * 1e3, s["height_m"] * 1e3
    q = d["lift_per_span_N_m"]                      # N/m
    p_mpa = (q / d["chord_m"]) / 1e6                # Pa -> MPa
    # *DLOAD on solid elements needs an ELEMENT set plus the loaded FACE number.
    # C3D4 face numbering (CalculiX): 1=1-2-3, 2=1-2-4, 3=2-3-4, 4=1-3-4.
    C3D4_FACES = {1: (0, 1, 2), 2: (0, 1, 3), 3: (1, 2, 3), 4: (0, 2, 3)}
    face_elems: dict[int, list[int]] = {1: [], 2: [], 3: [], 4: []}
    for eid, (etype, conn) in enumerate(used, start=1):
        for fno, idx in C3D4_FACES.items():
            tri = [conn[i] for i in idx]
            if all(n in coords and abs(coords[n][1] - ymax) < 1e-6 for n in tri):
                face_elems[fno].append(eid)
                break

    elems_text = []
    for eid, (etype, conn) in enumerate(used, start=1):
        elems_text.append(f"{eid}, " + ", ".join(str(n) for n in conn))

    deck = ["*Heading", "wing box", "*NODE"]
    for nid in sorted(coords):
        x, y, z = coords[nid]
        deck.append(f"{nid}, {x:.9g}, {y:.9g}, {z:.9g}")
    deck.append(f"*ELEMENT, TYPE={ctype}, ELSET=SOLID")
    deck.extend(elems_text)
    deck.append("*NSET, NSET=NROOT")
    deck.extend(_chunks(root_nodes))

    dload = []
    if load_mode == "body":
        # effective density so that rho_eff * g * A = q  [t/mm3]
        A_mm2 = s["area_m2"] * 1e6
        g_mm_s2 = 9810.0
        rho_eff_t_mm3 = (q / 1e3) / (g_mm_s2 * A_mm2)
        dload.append(f"SOLID, GRAV, {g_mm_s2:.6g}, 0., -1., 0.")
    else:
        rho_eff_t_mm3 = rho_mat / 1e12
        for fno, ids in face_elems.items():
            if not ids:
                continue
            deck.append(f"*ELSET, ELSET=ETOP{fno}")
            deck.extend(_chunks(ids))
            dload.append(f"ETOP{fno}, P{fno}, {p_mpa:.6g}")

    deck += [
        "*MATERIAL, NAME=CFRP",
        "*ELASTIC", f"{E/1e6:.6g}, {nu}",
        "*DENSITY", f"{rho_eff_t_mm3:.6g}",
        "*SOLID SECTION, ELSET=SOLID, MATERIAL=CFRP",
        "*STEP", "*STATIC",
        "*BOUNDARY", "NROOT, 1, 3, 0.0",
        "*DLOAD",
        *dload,
        "*NODE FILE", "U",
        "*EL FILE", "S",
        "*END STEP",
    ]
    (job / "wing" / "job.inp").write_text("\n".join(deck) + "\n", encoding="ascii")

    info = {
        "mesh_file": str(msh), "nodes": len(coords), "elements": len(used),
        "element_type": ctype,
        "root_nodes": len(root_nodes), "top_nodes": len(top_nodes),
        "top_faces": {f: len(v) for f, v in face_elems.items()},
        "top_elements": sum(len(v) for v in face_elems.values()),
        "tip_nodes": len(tip_nodes),
        "pressure_MPa": round(p_mpa, 8),
        "expected_total_lift_N": round(p_mpa * (width * d["span_m"] * 1e3), 3),
    }
    (job / "wing" / "mesh.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))
    return 0


def _chunks(ids, n=10):
    return [", ".join(str(i) for i in ids[k:k + n]) for k in range(0, len(ids), n)]


# --------------------------------------------------------------------------- #
# post: read .frd, compare with beam theory
# --------------------------------------------------------------------------- #
def post(job: Path, E):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import frd_reader  # local minimal FRD reader

    wing = job / "wing"
    frd = wing / "job.frd"
    if not frd.exists():
        raise SystemExit(f"ERROR: missing {frd}; run ccx_i8 -i job in {wing}")

    res = frd_reader.read_frd_results(frd)
    nodes, elements = frd_reader.read_inp_mesh(wing / "job.inp")
    disp = res.get("DISP", {})
    stress = res.get("STRESS", {})   # nodal (CalculiX FRD), keyed by NODE id

    # Element-averaged stress: average the nodal values over each element's
    # connectivity.  The FRD carries one value per node, so using `stress[eid]`
    # directly mixes the node and element numbering spaces (the old bug that
    # made the section table meaningless).
    elem_stress: dict[int, list[float]] = {}
    for eid, (etype, conn) in enumerate(elements, start=1):
        vals = [stress[n] for n in conn if n in stress]
        if len(vals) != len(conn) or not vals:
            continue
        elem_stress[eid] = [sum(v[i] for v in vals) / len(vals) for i in range(6)]

    # tip deflection: max |U| among nodes at max z (FRD displacements are in mm,
    # because the deck is in mm)
    zs = {n: c[2] for n, c in nodes.items()}
    zmax = max(zs.values())
    tip = [n for n, z in zs.items() if abs(z - zmax) < 1e-6 and n in disp]
    tip_u = [math.sqrt(sum(v * v for v in disp[n][:3])) for n in tip]
    delta_fea = max(tip_u) if tip_u else float("nan")

    # Bending stress: compare S11 (axial, along the span->x? see note) at the root.
    # In this model the span runs along Z, so the bending axial stress is S33.
    s11 = [abs(s[0]) for s in stress.values() if len(s) >= 6]
    s33 = [abs(s[2]) for s in stress.values() if len(s) >= 6]
    sigma_fea = max(s11) if s11 else float("nan")
    sigma_axial = max(s33) if s33 else float("nan")          # nodal extrapolated peak

    def _vm(s):
        return math.sqrt(0.5 * ((s[0] - s[1]) ** 2 + (s[1] - s[2]) ** 2 + (s[2] - s[0]) ** 2)
                         + 3 * (s[3] ** 2 + s[4] ** 2 + s[5] ** 2))

    sigma_vm = max((_vm(s) for s in stress.values() if len(s) >= 6), default=float("nan"))

    # element-averaged peaks (physically meaningful, comparable to beam theory)
    s11_e = [abs(s[0]) for s in elem_stress.values()]
    s33_e = [abs(s[2]) for s in elem_stress.values()]
    vm_e = [_vm(s) for s in elem_stress.values()]
    sigma_axial_ea = max(s33_e) if s33_e else float("nan")
    sigma_vm_ea = max(vm_e) if vm_e else float("nan")

    design = json.loads((wing / "design.json").read_text(encoding="utf-8"))
    theory = design["beam_theory"]

    # Section-by-section check away from the clamped root (where the peak is a
    # boundary/corner artefact): sigma(z) = M(z)*c/I, M(z) = q*(b-z)^2/2
    nodes_all = nodes
    q_n_mm = design["design"]["lift_per_span_N_m"] / 1e3      # N/mm
    b_mm = design["design"]["span_m"] * 1e3
    I = design["section"]["I_m4"] * 1e12                       # mm^4
    c_mm = design["section"]["height_m"] * 1e3 / 2.0
    sections = []
    for z_target in (100.0, 200.0, 400.0):
        vals = []
        for eid, (etype, conn) in enumerate(elements, start=1):
            zc = sum(nodes_all[n][2] for n in conn if n in nodes_all) / max(len(conn), 1)
            if abs(zc - z_target) < 3.0 and eid in elem_stress:
                vals.append(abs(elem_stress[eid][2]))          # S33 = axial (element-averaged)
        if not vals:
            continue
        M = q_n_mm * (b_mm - z_target) ** 2 / 2.0
        sigma_th = M * c_mm / I
        sections.append({
            "z_mm": z_target,
            "fea_max_s33_MPa": round(max(vals), 3),
            "beam_sigma_MPa": round(sigma_th, 3),
            "rel_err": round(abs(max(vals) - sigma_th) / sigma_th, 4),
            "n_elements": len(vals),
        })

    # deflection profile: delta(z) = q z^2 (6b^2 - 4bz + z^2) / (24 E I)
    E_mpa = design["material"]["E_Pa"] / 1e6

    def beam_delta(z):
        return q_n_mm * z**2 * (6 * b_mm**2 - 4 * b_mm * z + z**2) / (24 * E_mpa * I)

    profile = []
    for z_target in (100.0, 200.0, 400.0, 600.0, 800.0, 1000.0, 1200.0):
        vals = [math.sqrt(sum(v * v for v in disp[n][:3]))
                for n, c in nodes_all.items()
                if abs(c[2] - z_target) < 3.0 and n in disp]
        if not vals:
            continue
        fea = sum(vals) / len(vals)
        th = beam_delta(z_target)
        profile.append({
            "z_mm": z_target,
            "fea_deflection_mm": round(fea, 4),
            "beam_deflection_mm": round(th, 4),
            "rel_err": round(abs(fea - th) / th, 4) if th > 1e-9 else None,
            "n_nodes": len(vals),
        })

    info = {
        "fea": {
            "tip_deflection_mm": round(delta_fea, 4) if tip_u else None,
            "max_s11_MPa": round(sigma_fea, 4),
            "max_s33_MPa": round(sigma_axial, 4),
            "max_vm_stress_MPa": round(sigma_vm, 4),
            "max_s33_element_avg_MPa": round(sigma_axial_ea, 4),
            "max_vm_stress_element_avg_MPa": round(sigma_vm_ea, 4),
            "tip_nodes": len(tip),
            "n_disp": len(disp), "n_stress": len(stress),
        },
        "beam_theory": theory,
        "deflection_profile": profile,
        "sections": sections,
        "error": {
            "deflection_rel_err": round(abs(delta_fea - theory["tip_deflection_mm"]) / theory["tip_deflection_mm"], 4)
            if tip_u else None,
            # the section table is the stress check; the global nodal/element
            # peak sits in the clamped-root corner and is not a beam quantity
            "section_s33_max_rel_err": (round(max(s["rel_err"] for s in sections), 4)
                                        if sections else None),
        },
        "note": ("deflection profile is the primary check; the nodal S33 peak is a small-area "
                 "extrapolation artefact, while the section table uses element-averaged nodal stresses "
                 "(node/element id spaces are no longer mixed)"),
    }
    (wing / "result.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(info, indent=2, ensure_ascii=False))
    return 0


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    d1 = sub.add_parser("design")
    d1.add_argument("--job", required=True)
    d1.add_argument("--cl", type=float, default=1.791092)
    d1.add_argument("--v", type=float, default=30.0)
    d1.add_argument("--span", type=float, default=1.20)
    d1.add_argument("--chord", type=float, default=0.30)
    d1.add_argument("--height", type=float, default=0.040)
    d1.add_argument("--wall", type=float, default=0.003)
    d1.add_argument("--E", type=float, default=70e9)
    d1.add_argument("--nu", type=float, default=0.30)
    d1.add_argument("--rho-mat", type=float, default=1600.0)
    d1.add_argument("--h", type=float, default=0.008)

    d2 = sub.add_parser("mesh")
    d2.add_argument("--job", required=True)
    d2.add_argument("--load", choices=["body", "pressure"], default="body")

    d3 = sub.add_parser("post")
    d3.add_argument("--job", required=True)
    d3.add_argument("--E", type=float, default=70e9)

    args = ap.parse_args()
    job = Path(args.job).resolve()
    (job / "wing").mkdir(parents=True, exist_ok=True)

    if args.cmd == "design":
        d = design_point(args.cl, args.v, args.chord, args.span)
        s = section(args.chord, args.height, args.wall)
        t = beam_theory(d, s, args.E)
        info = {"design": d, "section": s,
                "material": {"E_Pa": args.E, "nu": args.nu, "rho": args.rho_mat},
                "beam_theory": t}
        write_geo(job / "wing" / "box.geo", args.chord, args.height, args.wall, args.span, args.h)
        (job / "wing" / "design.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "mesh":
        design = json.loads((job / "wing" / "design.json").read_text(encoding="utf-8"))
        msh = job / "wing" / "mesh.msh"
        s = design["section"]
        width, height, span = s["width_m"], s["height_m"], design["design"]["span_m"]
        wall = s["wall_m"]
        h = design.get("mesh_size_m", 0.008)

        # Drive gmsh through its OCC Python API: the .geo boolean syntax is
        # version-dependent and the pip wheel's gmsh.bat launcher returns 9009.
        import gmsh

        gmsh.initialize(["gmsh", "-v", "2"])
        try:
            gmsh.model.add("wing")
            outer = gmsh.model.occ.addBox(0, 0, 0, width, height, span)
            inner = gmsh.model.occ.addBox(wall, wall, wall, width - 2 * wall,
                                          height - 2 * wall, span - 2 * wall)
            gmsh.model.occ.cut([(3, outer)], [(3, inner)])
            gmsh.model.occ.synchronize()
            vols = gmsh.model.getEntities(3)
            if not vols:
                raise SystemExit("ERROR: boolean cut left no volume")
            gmsh.model.addPhysicalGroup(3, [t for _, t in vols], name="SOLID")
            # Keep the default Delaunay 3D algorithm: the Frontal algorithm (6)
            # silently produced zero elements inside the 3 mm walls.
            gmsh.option.setNumber("Mesh.MeshSizeMax", h)
            gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
            gmsh.model.mesh.generate(3)
            gmsh.write(str(msh))
        finally:
            gmsh.finalize()
        return build_deck(job, design["design"], design["section"],
                          design["material"]["E_Pa"], design["material"]["nu"], design["material"]["rho"],
                          load_mode=args.load)

    return post(job, args.E)


if __name__ == "__main__":
    raise SystemExit(main())
