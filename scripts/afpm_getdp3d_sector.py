#!/usr/bin/env python
"""AFPM 3D **annular sector** (one pole) with GetDP scalar-potential magnetostatics.

This removes the two approximations of the 3D slab:
  * the geometry is a true annular sector (radius r from R_i to R_o), so the
    pole pitch 2*pi*r/10 and the magnet/coil arc length vary with radius;
  * the sector spans one pole (36 deg) from magnet centre to magnet centre, so
    the two radial planes are symmetry planes (natural Neumann for phi).

Stack (axial y): back iron, magnets, air gap, PCB, air gap, magnets, back iron.
The air is a larger annular sector (r from R_i-air to R_o+air, y beyond the
stack); phi=0 on the outer air boundaries, natural Neumann on the two radial
symmetry planes.  Materials are classified after an OCC fragment, so all
interfaces are conforming.

No free currents -> scalar potential phi:
    div(mu grad phi) = div(mu0 M),   B = -mu grad phi - mu hc.

Coil flux: B_y is sampled on radial lines at 5 angles across the + magnet
(one pole) x 4 axial layers inside the PCB, then integrated as
    Phi = int_{0}^{18deg} int_{R_i}^{R_o} B_y r dr dtheta
and averaged over the PCB thickness.

External requirement: a `getdp` binary (see scripts/getdp_bootstrap.sh).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from afpm_getdp import (MU0, R_O, R_I, P_PAIRS, GAP, PCB_T,
                        find_getdp, getdp_env, parse_table)

POLE_DEG = 360.0 / (2 * P_PAIRS)      # 36 deg
HALF_DEG = POLE_DEG / 2.0            # 18 deg


def build_mesh(path: Path, h_m: float, size: float = 0.45e-3) -> dict:
    import gmsh

    y_pcb = PCB_T / 2.0
    y_gap = y_pcb + GAP
    y_mag = y_gap + h_m
    y_top = y_mag + 0.001
    air = 0.001
    r_in_air = R_I - air
    r_out_air = R_O + air
    ys = [-y_top, -y_mag, -y_gap, -y_pcb, y_pcb, y_gap, y_mag, y_top]
    a0 = math.radians(POLE_DEG)
    ah = math.radians(HALF_DEG)

    gmsh.initialize(["gmsh", "-v", "2"])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", size / 3.0)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.model.add("afpm_sector")
        occ = gmsh.model.occ

        def annulus(y0: float, dy: float, r_in: float, r_out: float,
                    angle: float, rotate: float = 0.0) -> int:
            out = occ.addCylinder(0, y0, 0, 0, dy, 0, r_out, angle=angle)
            inn = occ.addCylinder(0, y0, 0, 0, dy, 0, r_in, angle=angle)
            cut, _ = occ.cut([(3, out)], [(3, inn)])
            vol = cut[0][1]
            if rotate:
                occ.rotate([(3, vol)], 0, 0, 0, 0, 1, 0, rotate)
            return vol

        boxes = []
        for j in range(len(ys) - 1):
            y0, dy = ys[j], ys[j + 1] - ys[j]
            is_mag = (j == 1 or j == 5)
            if is_mag:
                boxes.append((3, annulus(y0, dy, R_I, R_O, ah, 0.0)))
                boxes.append((3, annulus(y0, dy, R_I, R_O, ah, ah)))
            else:
                boxes.append((3, annulus(y0, dy, R_I, R_O, a0, 0.0)))
        air_vol = annulus(-y_top - air, 2 * (y_top + air), r_in_air, r_out_air, a0, 0.0)
        boxes.append((3, air_vol))
        occ.fragment(boxes, [])
        gmsh.model.occ.synchronize()

        vols = [v[1] for v in gmsh.model.getEntities(3)]
        groups = {1: [], 2: [], 3: [], 4: []}
        mag_vols = []
        for v in vols:
            x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(3, v)
            cx, cy, cz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
            r = math.hypot(cx, cz)
            th = math.degrees(math.atan2(cz, cx)) % 360.0
            if not (r_in_air - 1e-6 <= r <= r_out_air + 1e-6 and
                    -y_top - 1e-6 <= cy <= y_top + 1e-6):
                groups[4].append(v)
                continue
            if R_I - 1e-6 <= r <= R_O + 1e-6 and abs(cy) <= y_top + 1e-6:
                ay = abs(cy)
                if ay >= y_mag:
                    groups[1].append(v)
                elif ay >= y_gap:
                    mag_vols.append((th, v))
                elif ay >= y_pcb:
                    groups[4].append(v)
                else:
                    groups[4].append(v)
            else:
                groups[4].append(v)
        # magnet polarity by angular position: lower angle = MagnetPos
        mag_vols.sort(key=lambda t: t[0])
        for k, (_, v) in enumerate(mag_vols):
            mid = len(mag_vols) // 2
            groups[2 if k < mid else 3].append(v)
        names = {1: "Iron", 2: "MagnetPos", 3: "MagnetNeg", 4: "Air"}
        for tag, vv in groups.items():
            if vv:
                gmsh.model.addPhysicalGroup(3, vv, tag=tag)
                gmsh.model.setPhysicalName(3, tag, names[tag])

        far = []
        for s in gmsh.model.getEntities(2):
            x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(2, s[1])
            cx, cy, cz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
            r = math.hypot(cx, cz)
            if (abs(r - r_out_air) < 1e-7 or abs(r - r_in_air) < 1e-7 or
                    abs(abs(cy) - (y_top + air)) < 1e-7):
                far.append(s[1])
        if far:
            gmsh.model.addPhysicalGroup(2, far, tag=11)
            gmsh.model.setPhysicalName(2, 11, "Far")
        gmsh.model.mesh.generate(3)
        gmsh.write(str(path))
        meta = {"r_m": (R_O + R_I) / 2, "P": 2 * math.pi * ((R_O + R_I) / 2) / (2 * P_PAIRS),
                "Lr": R_O - R_I, "r_in_air": r_in_air, "r_out_air": r_out_air,
                "y_pcb": y_pcb, "y_gap": y_gap, "y_mag": y_mag, "y_top": y_top,
                "h_m": h_m, "pole_deg": POLE_DEG, "half_deg": HALF_DEG,
                "theta0_deg": 90.0 - POLE_DEG,
                "n_nodes": int(gmsh.model.mesh.getNodes()[0].size)}
    finally:
        gmsh.finalize()
    return meta


def write_pro(path: Path, meta: dict, br: float, mur_mag: float, mur_iron: float,
              outdir: Path) -> None:
    y_pcb = meta["y_pcb"]
    r_i, r_o = R_I, R_O
    thetas = [math.radians(meta["theta0_deg"] + (k + 0.5) * meta["half_deg"] / 5.0)
              for k in range(5)]
    ylayers = [0.0, 0.5 * y_pcb, 0.75 * y_pcb, y_pcb]
    lines = []
    for yi, y in enumerate(ylayers):
        for ti, th in enumerate(thetas):
            ca, sa = math.cos(th), math.sin(th)
            lines.append('       Print[ b, OnLine {{%.12g, %.12g, %.12g}{%.12g, %.12g, %.12g}} {24},\n'
                         '              File "%s/b_y%d_t%d.txt", Format Table ];'
                         % (r_i * ca, y, r_i * sa, r_o * ca, y, r_o * sa,
                            outdir, yi, ti))
    hc = br / (MU0 * mur_mag)
    text = f"""// AFPM 3D annular sector (one pole), scalar potential, generated by scripts/afpm_getdp3d_sector.py
mu0 = 4.e-7*Pi;
br  = {br};
mur_mag  = {mur_mag};
mur_iron = {mur_iron};
hc0 = {hc:.12g};

Group {{
  Iron      = Region[1];
  MagnetPos = Region[2];
  MagnetNeg = Region[3];
  Air       = Region[4];
  Far       = Region[11];
  Domain    = Region[{{Iron, MagnetPos, MagnetNeg, Air}}];
  Magnets   = Region[{{MagnetPos, MagnetNeg}}];
  NonMag    = Region[Air];
}}

Function {{
  mu[NonMag]  = mu0;
  mu[Magnets] = mur_mag*mu0;
  mu[Iron]    = mur_iron*mu0;
  hc[MagnetPos] = Vector[0., +hc0, 0.];
  hc[MagnetNeg] = Vector[0., -hc0, 0.];
}}

Jacobian {{ {{ Name Vol; Case {{ {{ Region All; Jacobian Vol; }} }} }} }}

Integration {{
  {{ Name Int; Case {{ {{ Type Gauss; Case {{
      {{ GeoElement Tetrahedron; NumberOfPoints 4; }}
      {{ GeoElement Triangle;    NumberOfPoints 3; }}
  }} }} }} }}
}}

Constraint {{
  {{ Name phi; Case {{ {{ Region Far; Value 0.; }} }} }}
}}

FunctionSpace {{
  {{ Name Hgrad_phi; Type Form0;
     BasisFunction {{
       {{ Name sn; NameOfCoef phin; Function BF_Node;
          Support Domain; Entity NodesOf[ All ]; }}
     }}
     Constraint {{
       {{ NameOfCoef phin; EntityType NodesOf; NameOfConstraint phi; }}
     }}
  }}
}}

Formulation {{
  {{ Name MagSta; Type FemEquation;
     Quantity {{ {{ Name phi; Type Local; NameOfSpace Hgrad_phi; }} }}
     Equation {{
       Integral {{ [ -mu[] * Dof{{d phi}} , {{d phi}} ]; In Domain;
                   Jacobian Vol; Integration Int; }}
       Integral {{ [ -mu[] * hc[] , {{d phi}} ]; In Magnets;
                   Jacobian Vol; Integration Int; }}
     }}
  }}
}}

Resolution {{
  {{ Name MagSta;
     System {{ {{ Name Sys; NameOfFormulation MagSta; }} }}
     Operation {{ InitSolution[Sys]; Generate[Sys]; Solve[Sys]; SaveSolution[Sys]; }}
  }}
}}

PostProcessing {{
  {{ Name MagSta; NameOfFormulation MagSta;
     Quantity {{
       {{ Name b; Value {{
           Term {{ [ -mu[] * {{d phi}} ]; In Domain; Jacobian Vol; }}
           Term {{ [ -mu[] * hc[] ]; In Magnets; Jacobian Vol; }}
       }} }}
     }}
  }}
}}

PostOperation {{
  {{ Name Bline; NameOfPostProcessing MagSta;
     Operation {{
{chr(10).join(lines)}
     }}
  }}
}}
"""
    path.write_text(text, encoding="utf-8")


def analyse(meta: dict, work: Path, nph: float) -> dict:
    r_i, r_o = R_I, R_O
    y_pcb = meta["y_pcb"]
    ylayers = [0.0, 0.5 * y_pcb, 0.75 * y_pcb, y_pcb]
    dtheta = math.radians(meta["half_deg"] / 5.0)
    per_y = []
    for yi in range(4):
        acc = 0.0
        for ti in range(5):
            rows = parse_table(work / f"b_y{yi}_t{ti}.txt")
            arr = [r for r in rows if len(r) >= 11]
            if len(arr) < 3:
                continue
            x = np.array([r[2] for r in arr])
            z = np.array([r[4] for r in arr])
            by = np.array([r[9] for r in arr])
            r = np.hypot(x, z)
            order = np.argsort(r)
            r, by = r[order], by[order]
            acc += abs(float(np.trapezoid(by * r, r)) * dtheta)
        per_y.append(acc)
    # average over the PCB thickness (field symmetric about y=0)
    avg = float(np.trapezoid(per_y, ylayers) / (ylayers[-1] - ylayers[0]))
    out = {"geometry": meta, "nph": nph, "flux_per_pole_Wb": avg,
           "Kt_mNm_A": 1.5 * P_PAIRS * nph * avg * 1e3,
           "layers": [{"y": y, "flux_Wb": f} for y, f in zip(ylayers, per_y)]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--h-m", type=float, default=0.0010)
    ap.add_argument("--br", type=float, default=1.30)
    ap.add_argument("--mur-mag", type=float, default=1.05)
    ap.add_argument("--mur-iron", type=float, default=1000.0)
    ap.add_argument("--nph", type=float, default=216.0)
    ap.add_argument("--size", type=float, default=0.45e-3)
    ap.add_argument("--getdp", default=None)
    args = ap.parse_args()
    job = Path(args.job).resolve(); job.mkdir(parents=True, exist_ok=True)
    work = job / "_getdp3d_sector"; work.mkdir(exist_ok=True)
    msh, pro = work / "afpm_sector.msh", work / "afpm_sector.pro"
    meta = build_mesh(msh, args.h_m, args.size)
    write_pro(pro, meta, args.br, args.mur_mag, args.mur_iron, work)
    getdp = find_getdp(args.getdp)
    proc = subprocess.run([getdp, str(pro), "-msh", str(msh), "-solve", "MagSta", "-pos", "Bline"],
                          cwd=work, env=getdp_env(getdp), capture_output=True, text=True)
    (work / "getdp.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        print(proc.stdout[-3000:]); print(proc.stderr[-3000:], file=sys.stderr)
        raise SystemExit(f"getdp failed with {proc.returncode} (see {work}/getdp.log)")
    out = analyse(meta, work, args.nph)
    (job / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k not in ("geometry", "layers")},
                     indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
