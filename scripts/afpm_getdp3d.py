#!/usr/bin/env python
"""AFPM 3D slab (one pole pair) with GetDP scalar-potential magnetostatics.

This is the 3D step after the full-stack 2D model: the same radial-axial stack
is extruded over one pole pair (x = circumferential, y = axial, z = radial,
radial length R_o-R_i) with air margins in y and z, so the radial fringing at
the inner/outer ends is included.  It is an *unrolled* slab, not yet an
annular sector: the pole pitch is constant in x (the annular r-dependence of
the pitch is the next step).

The problem has no free currents, so the scalar potential phi is solved:
    div(mu grad phi) = div(mu0 M)          B = -mu grad phi - mu hc
which is the GetDP template's Magnetostatics_phi formulation.  With hc in the
magnets only, and Dirichlet phi=0 on the outer air box (the x=0/2P planes are
symmetry planes at magnet centres -> natural Neumann).

External requirement: a `getdp` binary (see scripts/getdp_bootstrap.sh).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from afpm_getdp import (MU0, R_O, R_I, P_PAIRS, GAP, PCB_T,
                        find_getdp, getdp_env, parse_table)

HERE = Path(__file__).resolve().parent


def pole_pitch():
    r_m = (R_O + R_I) / 2.0
    return r_m, 2.0 * math.pi * r_m / (2 * P_PAIRS)


def build_mesh(path: Path, h_m: float, size: float = 0.45e-3) -> dict:
    import gmsh

    r_m, P = pole_pitch()
    Lx = 2.0 * P
    Lr = R_O - R_I
    y_pcb = PCB_T / 2.0
    y_gap = y_pcb + GAP
    y_mag = y_gap + h_m
    y_top = y_mag + 0.001
    ay, az = 0.001, 0.001                 # air margins
    ys = [-y_top, -y_mag, -y_gap, -y_pcb, y_pcb, y_gap, y_mag, y_top]
    xs_mag = [0.0, P / 2.0, 1.5 * P, 2.0 * P]

    gmsh.initialize(["gmsh", "-v", "2"])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", size / 3.0)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.model.add("afpm3d")
        occ = gmsh.model.occ
        boxes = []
        # machine layers (7 bands); magnet bands split into 3 x segments
        for j in range(len(ys) - 1):
            y0, y1 = ys[j], ys[j + 1]
            magnet_band = (abs(y0 + y_mag) < 1e-9 and abs(y1 + y_gap) < 1e-9) or (
                abs(y0 + y_top) < 1e-9 and False)
            # identify the two magnet bands explicitly
            is_mag = (j == 1 or j == 5)
            segs = xs_mag if is_mag else [0.0, Lx]
            for a, b in zip(segs[:-1], segs[1:]):
                boxes.append((3, occ.addBox(a, y0, 0.0, b - a, y1 - y0, Lr)))
        # outer air box
        air = occ.addBox(0.0, -y_top - ay, -az, Lx, 2 * (y_top + ay), Lr + 2 * az)
        boxes.append((3, air))
        out, _ = occ.fragment(boxes, [])
        gmsh.model.occ.synchronize()

        # classify volumes by their bounding-box centre
        vols = [v[1] for v in gmsh.model.getEntities(3)]
        groups = {1: [], 2: [], 3: [], 4: []}
        for v in vols:
            x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(3, v)
            cx, cy, cz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
            if not (0.0 - 1e-9 <= cx <= Lx + 1e-9 and 0.0 - 1e-9 <= cz <= Lr + 1e-9
                    and abs(cy) <= y_top + 1e-9):
                groups[4].append(v)
                continue
            ay_ = abs(cy)
            if ay_ >= y_mag:
                groups[1].append(v)
            elif ay_ >= y_gap:
                if cx < P / 2.0 or cx > 1.5 * P:
                    groups[2].append(v)
                else:
                    groups[3].append(v)
            elif ay_ >= y_pcb:
                groups[4].append(v)          # air gap
            else:
                groups[4].append(v)          # PCB (mu0)
        names = {1: "Iron", 2: "MagnetPos", 3: "MagnetNeg", 4: "Air"}
        for tag, vv in groups.items():
            if vv:
                gmsh.model.addPhysicalGroup(3, vv, tag=tag)
                gmsh.model.setPhysicalName(3, tag, names[tag])

        # Dirichlet boundary: outer air-box faces in y and z (x faces are symmetry)
        far = []
        for s in gmsh.model.getEntities(2):
            x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(2, s[1])
            cx, cy, cz = (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2
            on_y = abs(abs(cy) - (y_top + ay)) < 1e-7
            on_z = abs(cz + az) < 1e-7 or abs(cz - (Lr + az)) < 1e-7
            if on_y or on_z:
                far.append(s[1])
        if far:
            gmsh.model.addPhysicalGroup(2, far, tag=11)
            gmsh.model.setPhysicalName(2, 11, "Far")
        gmsh.model.mesh.generate(3)
        gmsh.write(str(path))
        meta = {"r_m": r_m, "P": P, "Lx": Lx, "Lr": Lr, "y_pcb": y_pcb,
                "y_gap": y_gap, "y_mag": y_mag, "y_top": y_top, "h_m": h_m,
                "n_nodes": int(gmsh.model.mesh.getNodes()[0].size)}
    finally:
        gmsh.finalize()
    return meta


def write_pro(path: Path, meta: dict, br: float, mur_mag: float, mur_iron: float,
              outdir: Path) -> None:
    Lx = meta["Lx"]
    Lr = meta["Lr"]
    y_pcb = meta["y_pcb"]
    hc = br / (MU0 * mur_mag)
    y_pcb2 = 0.5 * y_pcb
    lines = []
    # coil-plane samples: y layers x z positions
    for yi, y in ((0, 0.0), (1, y_pcb2), (2, y_pcb)):
        for zi, frac in enumerate((0.1, 0.3, 0.5, 0.7, 0.9)):
            z = frac * Lr
            lines.append('       Print[ b, OnLine {{0., %.12g, %.12g}{ %.12g, %.12g, %.12g}} {80},\n'
                         '              File "%s/b_y%d_z%d.txt", Format Table ];'
                         % (y, z, Lx, y, z, outdir, yi, zi))
    text = f"""// AFPM 3D slab (one pole pair), scalar potential, generated by scripts/afpm_getdp3d.py
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
    Lx = meta["Lx"]
    Lr = meta["Lr"]
    y_pcb = meta["y_pcb"]
    ys = (0.0, 0.5 * y_pcb, y_pcb)
    dz = Lr / 5.0
    y_flux = []
    slices = []
    for yi in range(3):
        z_flux = []
        for zi in range(5):
            rows = parse_table(work / f"b_y{yi}_z{zi}.txt")
            if not rows:
                z_flux.append(0.0)
                continue
            arr = [r for r in rows if len(r) >= 11]
            if not arr:
                z_flux.append(0.0)
                continue
            x = np.array([r[2] for r in arr]); by = np.array([r[9] for r in arr])
            F = np.concatenate([[0.0], np.cumsum((by[1:] + by[:-1]) / 2 * np.diff(x))])
            z_flux.append(float(np.max(np.abs(F))))
        # average over the z slices (equal width), Wb/m -> Wb per pole
        y_flux.append(sum(z_flux) / len(z_flux) * Lr)
        slices.append({"y": ys[yi], "flux_per_pole_Wb": y_flux[-1]})
    flux = sum(y_flux) / len(y_flux)
    out = {"geometry": meta, "nph": nph, "flux_per_pole_Wb": flux,
           "Kt_mNm_A": 1.5 * P_PAIRS * nph * flux * 1e3, "slices": slices}
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
    work = job / "_getdp3d"; work.mkdir(exist_ok=True)
    msh, pro = work / "afpm3d.msh", work / "afpm3d.pro"
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
    print(json.dumps({k: v for k, v in out.items() if k not in ("geometry", "slices")},
                     indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
