#!/usr/bin/env python
"""AFPM 2D magnetostatics with GetDP + Gmsh (full-stack, conforming mesh).

The hand-written scalar-potential solver in ``afpm_model.py`` is not a reliable
model of this machine (magnetisation applied to the back iron, a half-cell
symmetry that forces/forbids the through-PCB flux, staircased interfaces, a
mean-radius Cartesian slice, linear iron).  This script models **one pole** of
the full stack (both rotors, N-S TORUS) with a material-conforming structured
mesh and solves it with GetDP's A_z formulation:

    nu curl(A) . curl(w) + hc . curl(w) = js . w      (hc = -Br/(mu0 mu_r))

The magnets are driven by their coercive field, so no magnetisation is ever
applied to the iron.  The domain runs from the centre of one magnet to the
centre of the adjacent (opposite) magnet, where B_x = 0 by symmetry, so the
Dirichlet condition A_z = 0 on both sides is exact (no periodic constraint and
no gauge freedom).  The PCB mid-plane field is parsed from GetDP's table output
and post-processed in Python (flux per pole, harmonic content, Kt).

External requirement: a ``getdp``/``getdp-sparskit`` binary; on Ubuntu it is in
the ``getdp-sparskit`` package.  Pass ``--getdp`` or set ``$GETDP``.
See ``scripts/getdp_bootstrap.sh`` for a rootless install.

Usage:
    python scripts/afpm_getdp.py --job results/afpm-pcb-motor/getdp2d \
        [--h-m 0.001] [--br 1.3] [--arc 1.0] [--nph 216] [--mur-iron 1000]
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

MU0 = 4e-7 * math.pi
R_O, R_I = 0.0095, 0.0035          # outer / inner radius [m]
P_PAIRS = 5
GAP = 0.00025
PCB_T = 0.0060


_RADIUS = None


def pole_geometry():
    r_m = _RADIUS if _RADIUS is not None else (R_O + R_I) / 2.0
    return r_m, 2.0 * math.pi * r_m / (2 * P_PAIRS)      # pole pitch [m]


def build_mesh(path: Path, h_m: float, arc: float, nx_seg: int = 30,
               band_div: dict | None = None) -> dict:
    """Structured, material-conforming mesh of one pole of the full stack.

    x = 0 is the centre of the + magnet, x = P the centre of the - magnet.
    Bands (bottom -> top): iron, magnet, gap, PCB, PCB, gap, magnet, iron.
    """
    import gmsh

    r_m, P = pole_geometry()
    y_pcb = PCB_T / 2.0
    y_gap = y_pcb + GAP
    y_mag = y_gap + h_m
    y_top = y_mag + 0.001                     # 1 mm back iron (assumption)
    ys = [-y_top, -y_mag, -y_gap, -y_pcb, 0.0, y_pcb, y_gap, y_mag, y_top]
    nbands = len(ys) - 1
    w = arc * P
    if w >= 0.999 * P:
        xs = [0.0, P / 2.0, P]
        seg_kind = ["mag_pos", "mag_neg"]
    else:
        xs = [0.0, w / 2.0, P - w / 2.0, P]
        seg_kind = ["mag_pos", "air_mid", "mag_neg"]
    if band_div is None:
        band_div = {0: 6, 1: 10, 2: 3, 3: 8, 4: 8, 5: 3, 6: 10, 7: 6}
    if h_m < 0.0006:
        band_div[1] = band_div[6] = 6

    gmsh.initialize(["gmsh", "-v", "2"])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.model.add("afpm")
        geo = gmsh.model.geo

        pts = {}
        for i, x in enumerate(xs):
            for j, y in enumerate(ys):
                pts[(i, j)] = geo.addPoint(x, y, 0.0)
        hline, vline = {}, {}
        for j in range(len(ys)):
            for i in range(len(xs) - 1):
                hline[(i, j)] = geo.addLine(pts[(i, j)], pts[(i + 1, j)])
        for i in range(len(xs)):
            for j in range(nbands):
                vline[(i, j)] = geo.addLine(pts[(i, j)], pts[(i, j + 1)])
        surf = {}
        for j in range(nbands):
            for i in range(len(xs) - 1):
                loop = geo.addCurveLoop([hline[(i, j)], vline[(i + 1, j)],
                                         -hline[(i, j + 1)], -vline[(i, j)]])
                surf[(i, j)] = geo.addPlaneSurface([loop])

        # physical regions
        groups = {1: [], 2: [], 3: [], 4: [], 5: []}
        for j in range(nbands):
            for i in range(len(xs) - 1):
                if j in (0, 7):
                    groups[1].append(surf[(i, j)])              # iron
                elif j in (1, 6):
                    if seg_kind[i] == "mag_pos":
                        groups[2].append(surf[(i, j)])
                    elif seg_kind[i] == "mag_neg":
                        groups[3].append(surf[(i, j)])
                    else:
                        groups[4].append(surf[(i, j)])          # magnet-band air
                elif j in (2, 5):
                    groups[4].append(surf[(i, j)])              # air gap
                else:
                    groups[5].append(surf[(i, j)])              # PCB
        names = {1: "Iron", 2: "MagnetPos", 3: "MagnetNeg", 4: "Air", 5: "PCB"}
        for tag, ss in groups.items():
            geo.addPhysicalGroup(2, ss, tag=tag)
            gmsh.model.setPhysicalName(2, tag, names[tag])
        geo.addPhysicalGroup(1, [vline[(0, j)] for j in range(nbands)], tag=11)
        gmsh.model.setPhysicalName(1, 11, "Left")
        geo.addPhysicalGroup(1, [vline[(len(xs) - 1, j)] for j in range(nbands)], tag=12)
        gmsh.model.setPhysicalName(1, 12, "Right")

        for tag in hline.values():
            geo.mesh.setTransfiniteCurve(tag, nx_seg)
        for (i, j), tag in vline.items():
            geo.mesh.setTransfiniteCurve(tag, band_div[j])
        for (i, j), s in surf.items():
            corners = [pts[(i, j)], pts[(i + 1, j)], pts[(i + 1, j + 1)], pts[(i, j + 1)]]
            geo.mesh.setTransfiniteSurface(s, "Left", corners)
            geo.mesh.setRecombine(2, s)
        geo.synchronize()
        gmsh.model.mesh.generate(2)
        gmsh.write(str(path))
        meta = {"r_m": r_m, "P": P, "Lx": P, "y_pcb": y_pcb, "y_gap": y_gap,
                "y_mag": y_mag, "y_top": y_top, "h_m": h_m, "arc": arc,
                "xs": xs}
    finally:
        gmsh.finalize()
    return meta


def write_pro(path: Path, meta: dict, br: float, mur_mag: float, mur_iron: float,
              outdir: Path) -> None:
    Lx = meta["Lx"]
    ymid = 0.0
    ygap = (meta["y_pcb"] + meta["y_gap"]) / 2.0
    y_pcb = meta["y_pcb"]
    hc_mag = br / (MU0 * mur_mag)
    text = f"""// AFPM one-pole 2D magnetostatics (A_z), generated by scripts/afpm_getdp.py
mu0 = 4.e-7*Pi;
br  = {br};
mur_mag  = {mur_mag};
mur_iron = {mur_iron};
hc0 = {hc_mag:.12g};
Lx  = {Lx:.12g};

Group {{
  Iron      = Region[1];
  MagnetPos = Region[2];
  MagnetNeg = Region[3];
  Air       = Region[4];
  PCB       = Region[5];
  Left      = Region[11];
  Right     = Region[12];
  Domain    = Region[{{Iron, MagnetPos, MagnetNeg, Air, PCB}}];
  Magnets   = Region[{{MagnetPos, MagnetNeg}}];
  NonMag    = Region[{{Air, PCB}}];
}}

Function {{
  nu[NonMag]   = 1./mu0;
  nu[Magnets]  = 1./(mur_mag*mu0);
  nu[Iron]     = 1./(mur_iron*mu0);
  // coercive field (opposite to Br): Br = -mu hc.  N-S TORUS: the upper rotor's
  // N pole faces the PCB and the lower rotor's S pole faces it, i.e. both
  // magnets have Br pointing away from the PCB at x~0 -> Br = -y there, so
  // hc = +y.  At the adjacent pole both flip.
  hc[MagnetPos] = Vector[0., +hc0, 0.];
  hc[MagnetNeg] = Vector[0., -hc0, 0.];
}}

Jacobian {{ {{ Name Vol; Case {{ {{ Region All; Jacobian Vol; }} }} }} }}

Integration {{
  {{ Name Int; Case {{ {{ Type Gauss; Case {{
      {{ GeoElement Triangle;   NumberOfPoints 3; }}
      {{ GeoElement Quadrangle; NumberOfPoints 4; }}
  }} }} }} }}
}}

Constraint {{
  {{ Name a; Case {{
      {{ Region Left;  Value 0.; }}
      {{ Region Right; Value 0.; }}
  }} }}
}}

FunctionSpace {{
  {{ Name Hcurl_a; Type Form1P;
     BasisFunction {{
       {{ Name se; NameOfCoef ae; Function BF_PerpendicularEdge;
          Support Domain; Entity NodesOf[ All ]; }}
     }}
     Constraint {{
       {{ NameOfCoef ae; EntityType NodesOf; NameOfConstraint a; }}
     }}
  }}
}}

Formulation {{
  {{ Name MagSta; Type FemEquation;
     Quantity {{ {{ Name a; Type Local; NameOfSpace Hcurl_a; }} }}
     Equation {{
       Integral {{ [ nu[] * Dof{{d a}} , {{d a}} ]; In Domain;
                   Jacobian Vol; Integration Int; }}
       Integral {{ [ hc[] , {{d a}} ]; In Magnets;
                   Jacobian Vol; Integration Int; }}
     }}
  }}
}}

Resolution {{
  {{ Name MagSta;
     System {{ {{ Name Sys; NameOfFormulation MagSta; }} }}
     Operation {{ Generate[Sys]; Solve[Sys]; SaveSolution[Sys]; }}
  }}
}}

PostProcessing {{
  {{ Name MagSta; NameOfFormulation MagSta;
     Quantity {{
       {{ Name b; Value {{ Term {{ [ {{d a}} ]; In Domain; Jacobian Vol; }} }} }}
     }}
  }}
}}

PostOperation {{
  {{ Name Bline; NameOfPostProcessing MagSta;
     Operation {{
       Print[ b, OnLine {{{{0., {ymid}, 0.}}{{ {Lx:.12g}, {ymid}, 0.}}}} {{240}},
              File "{outdir}/b_mid.txt", Format Table ];
       Print[ b, OnLine {{{{0., {ygap:.12g}, 0.}}{{ {Lx:.12g}, {ygap:.12g}, 0.}}}} {{240}},
              File "{outdir}/b_gap.txt", Format Table ];
       Print[ b, OnLine {{{{0., 0., 0.}}{{ {Lx:.12g}, 0., 0.}}}} {{160}},
              File "{outdir}/b_L0.txt", Format Table ];
       Print[ b, OnLine {{{{0., {0.5*y_pcb:.12g}, 0.}}{{ {Lx:.12g}, {0.5*y_pcb:.12g}, 0.}}}} {{160}},
              File "{outdir}/b_L1.txt", Format Table ];
       Print[ b, OnLine {{{{0., {0.75*y_pcb:.12g}, 0.}}{{ {Lx:.12g}, {0.75*y_pcb:.12g}, 0.}}}} {{160}},
              File "{outdir}/b_L2.txt", Format Table ];
       Print[ b, OnLine {{{{0., {0.9*y_pcb:.12g}, 0.}}{{ {Lx:.12g}, {0.9*y_pcb:.12g}, 0.}}}} {{160}},
              File "{outdir}/b_L3.txt", Format Table ];
       Print[ b, OnLine {{{{0., {y_pcb:.12g}, 0.}}{{ {Lx:.12g}, {y_pcb:.12g}, 0.}}}} {{160}},
              File "{outdir}/b_L4.txt", Format Table ];
     }}
  }}
}}
"""
    path.write_text(text, encoding="utf-8")


def parse_table(path: Path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line[0].isalpha():
            continue
        try:
            vals = [float(v) for v in line.replace(",", " ").split()]
        except ValueError:
            continue
        if len(vals) >= 3:
            rows.append(vals)
    return rows


def find_getdp(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("GETDP"):
        return os.environ["GETDP"]
    for name in ("getdp-sparskit", "getdp"):
        p = shutil.which(name)
        if p:
            return p
    for cand in ("/tmp/getdp/root/usr/bin/getdp-sparskit",):
        if Path(cand).exists():
            return cand
    raise SystemExit("getdp not found; pass --getdp or set GETDP (scripts/getdp_bootstrap.sh)")


def getdp_env(getdp: str) -> dict:
    env = dict(os.environ)
    root = Path(getdp).resolve().parents[2]
    extra = [str(p) for p in (root / "usr/lib/x86_64-linux-gnu", root / "usr/lib",
                              Path("/tmp/ccxroot/usr/lib/x86_64-linux-gnu"),
                              Path("/tmp/ccxroot/usr/lib")) if p.exists()]
    if extra:
        env["LD_LIBRARY_PATH"] = ":".join(extra + [env.get("LD_LIBRARY_PATH", "")]).strip(":")
    return env


def parse_ba(rows):
    """GetDP table rows -> (x, by).  Columns: [tag, id, x, y, z, x, y, z, bx, by, bz]."""
    import numpy as np
    x, by = [], []
    for r in rows:
        if len(r) >= 11:
            x.append(r[2]); by.append(r[9])
        elif len(r) >= 4:
            x.append(r[-4]); by.append(r[-2])
    if not x:
        return None, None
    x = np.array(x, dtype=float); by = np.array(by, dtype=float)
    order = np.argsort(x)
    return x[order], by[order]


def analyse_slice(meta: dict, layer_rows: dict, rows_gap, nph: float,
                  delta_r: float | None = None):
    """One radial slice, layer-averaged over the PCB thickness.

    The axial flux is strongly non-uniform across the 6 mm PCB (it decays away
    from the magnet faces), so the coil flux linkage must be averaged over the
    layer stack, not read at the mid-plane only.
    """
    import numpy as np
    y_pcb = meta["y_pcb"]
    out = {"geometry": meta, "nph": nph}
    zs, fm = [], []
    for frac, rows in layer_rows:
        x, by = parse_ba(rows)
        if x is None:
            continue
        F = np.concatenate([[0.0], np.cumsum((by[1:] + by[:-1]) / 2.0 * np.diff(x))])
        zs.append(frac * y_pcb)
        fm.append(float(np.max(np.abs(F))))        # Wb per metre of radial length
        if frac == 0.0:
            out["B_mid"] = {"mean_abs": float(np.mean(np.abs(by))),
                            "max_abs": float(np.max(np.abs(by)))}
        if frac >= 0.99:
            out["B_near_surface"] = {"mean_abs": float(np.mean(np.abs(by)))}
    if not zs:
        return out
    zs = np.array(zs); fm = np.array(fm)
    # field is even in z; average over [0, y_pcb] and use it for the whole stack
    avg = float(np.trapezoid(fm, zs) / (zs[-1] - zs[0])) if len(zs) > 1 else float(fm[0])
    out["flux_per_m_layer_avg_Wb_per_m"] = avg
    out["flux_per_pole_Wb"] = avg * (R_O - R_I if delta_r is None else delta_r)
    out["Kt_mNm_A"] = 1.5 * P_PAIRS * nph * out["flux_per_pole_Wb"] * 1e3
    out["layers"] = [{"y_m": float(z), "flux_per_m_Wb_per_m": float(f)} for z, f in zip(zs, fm)]
    xg, byg = parse_ba(rows_gap)
    if xg is not None:
        out["B_gap"] = {"mean_abs": float(np.mean(np.abs(byg))),
                        "max_abs": float(np.max(np.abs(byg)))}
    # fundamental diagnostic on the mid-plane profile
    x0, by0 = parse_ba(layer_rows[0][1])
    if x0 is not None:
        Fh = np.fft.rfft(by0) / len(by0) * 2
        out["B1_T"] = float(abs(Fh[1]))
        out["B3_over_B1"] = float(abs(Fh[3]) / abs(Fh[1])) if abs(Fh[1]) > 0 else float("nan")
    return out


def analyse(meta: dict, layer_rows: dict, rows_gap, nph: float) -> dict:
    return analyse_slice(meta, layer_rows, rows_gap, nph, delta_r=None)


def analyse(meta: dict, rows_mid, rows_gap, nph: float) -> dict:
    return analyse_slice(meta, rows_mid, rows_gap, nph, delta_r=None)


def run_slice(job: Path, radius: float, h_m: float, arc: float, br: float,
              mur_mag: float, mur_iron: float, nph: float, nx_seg: int,
              getdp: str, delta_r: float | None) -> dict:
    """Mesh + solve one radial slice (local pole pitch at `radius`)."""
    # temporarily override the radius used by pole_geometry
    global _RADIUS
    _RADIUS = radius
    work = job / "_getdp"
    work.mkdir(parents=True, exist_ok=True)
    msh = work / "afpm2d.msh"
    pro = work / "afpm2d.pro"
    meta = build_mesh(msh, h_m, arc, nx_seg)
    write_pro(pro, meta, br, mur_mag, mur_iron, work)
    proc = subprocess.run([getdp, str(pro), "-msh", str(msh), "-solve", "MagSta", "-pos", "Bline"],
                          cwd=work, env=getdp_env(getdp), capture_output=True, text=True)
    (work / "getdp.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        print(proc.stdout[-3000:]); print(proc.stderr[-3000:], file=sys.stderr)
        raise SystemExit(f"getdp failed with {proc.returncode} (see {work}/getdp.log)")
    layer_rows = []
    for name, frac in (("b_L0.txt", 0.0), ("b_L1.txt", 0.5),
                       ("b_L2.txt", 0.75), ("b_L3.txt", 0.9),
                       ("b_L4.txt", 1.0)):
        layer_rows.append((frac, parse_table(work / name)))
    return analyse_slice(meta, layer_rows, parse_table(work / "b_gap.txt"),
                         nph, delta_r=delta_r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--h-m", type=float, default=0.0010)
    ap.add_argument("--br", type=float, default=1.30)
    ap.add_argument("--arc", type=float, default=1.0)
    ap.add_argument("--mur-mag", type=float, default=1.05)
    ap.add_argument("--mur-iron", type=float, default=1000.0)
    ap.add_argument("--nph", type=float, default=216.0)
    ap.add_argument("--nx-seg", type=int, default=40)
    ap.add_argument("--radius", type=float, default=None,
                    help="slice radius [m]; default = mean radius")
    ap.add_argument("--multi-slice", type=int, default=0,
                    help="if >0, integrate N radial slices (annulus)")
    ap.add_argument("--getdp", default=None)
    args = ap.parse_args()

    global _RADIUS
    job = Path(args.job).resolve()
    job.mkdir(parents=True, exist_ok=True)
    getdp = find_getdp(args.getdp)

    if args.multi_slice:
        n = args.multi_slice
        dr = (R_O - R_I) / n
        slices = []
        for k in range(n):
            r = R_I + (k + 0.5) * dr
            _RADIUS = r
            d = job / f"slice_{k}"
            d.mkdir(parents=True, exist_ok=True)
            info = run_slice(d, r, args.h_m, args.arc, args.br, args.mur_mag,
                             args.mur_iron, args.nph, args.nx_seg, getdp, dr)
            slices.append({"r_m": r, **{k2: v for k2, v in info.items() if k2 != "geometry"}})
        flux = sum(s.get("flux_per_m_layer_avg_Wb_per_m", 0.0) * dr for s in slices)
        out = {"mode": "multi-slice", "n_slices": n, "delta_r_m": dr,
               "nph": args.nph, "h_m": args.h_m, "br": args.br, "arc": args.arc,
               "flux_per_pole_Wb": flux, "Kt_mNm_A": 1.5 * P_PAIRS * args.nph * flux * 1e3,
               "slices": slices}
    else:
        r = args.radius if args.radius is not None else (R_O + R_I) / 2.0
        _RADIUS = r
        out = run_slice(job, r, args.h_m, args.arc, args.br, args.mur_mag,
                        args.mur_iron, args.nph, args.nx_seg, getdp, None)
        out["radius_m"] = r
    (job / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "slices"}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
