# Scripts

Every script is standalone, takes `--job <dir>`, and writes only inside that directory.
Run them with the repository venv: `.venv\Scripts\python scripts\<script>.py ...`.

## Structural pipeline (box cantilever)

| Script | Purpose | Usage |
|---|---|---|
| `model.py` | parametric box cantilever → STEP | `python scripts/model.py --job results/box-cantilever-500N` |
| `mesh.py` | STEP → gmsh → `.msh` + physical groups | `python scripts/mesh.py --job results/box-cantilever-500N` |
| `deck.py` | `.msh` + loads → CalculiX `.inp` | `python scripts/deck.py --job results/box-cantilever-500N` |
| `frd_reader.py` | `.frd` → `.vtu` + `frd.json` + `result.json` (writes FRD **nodal** stresses to `point_data` and element averages to `cell_data`) | `python scripts/frd_reader.py --job results/box-cantilever-500N` |
| `render.py` | stress/displacement PNG from the `.vtu` | `python scripts/render.py --job results/box-cantilever-500N` |
| `run_job.ps1` | the whole chain in one call | `pwsh scripts/run_job.ps1 -Job results/box-cantilever-500N -SkipSolve` |
| `params.example.json` | input schema for `run_job.ps1` | — |
| `smoke.inp` | minimal CalculiX deck used to verify the solver install (1 mm cube, 1 N; max \|U\| ≈ 5.17e-6 mm) | `ccx_i8.exe -i smoke` |

## Airfoils

| Script | Purpose | Usage |
|---|---|---|
| `airfoil_validate.py` | NACA 4-digit geometry + thin-airfoil theory → `airfoil.json` | `--job results/uav-wing-naca4412` |
| `airfoil_cad.py` | profile → closed STEP (single face) | `--job results/uav-wing-naca4412` |
| `wing_fea.py` | wing box `design` / `mesh` / `post`, compared with beam theory | `--job results/uav-wing-naca4412 --cl 1.26 --v 43` |
| `polar_validate.py` | NACA 2412/4412 polars against the J. Thermal Eng. tables | `--job results/uav-wing-polar` |

## Wind-turbine blade

| Script | Purpose | Usage |
|---|---|---|
| `blade_geometry.py` | Glauert chord/twist → NACA 5512 loft → STEP/STL | `--job results/wind-blade-25m --R 26.5 --tsr 9 --cl 1.2 --nsec 20 --rhub 2.5` |
| `blade_bem.py` | BEM: `Cp–TSR`, power curve, thrust | `--job results/wind-blade-25m` |
| `blade_fea.py` | `mesh` / `post`: centrifugal + aerodynamic load | `--job results/wind-blade-25m --h 0.9` |
| `blade_viz.py` | blade 2D distributions, `Cp–TSR`, 3D rotor | `--job results/wind-blade-25m` |

## Heat transfer

| Script | Purpose | Usage |
|---|---|---|
| `thermal_pipe.py` | pipe mesh → `*FILM` deck → comparison with exact and fin solutions | `--job results/exhaust-pipe-gradient --h 0.0025 --seg 10` |

Uses **SI units** (m, N, Pa, kg, s, K) — the only scripts that do.

## Electromagnetics

| Script | Purpose | Usage |
|---|---|---|
| `afpm_model.py` | AFPM 3D geometry; 2D magnetostatic solver (scalar potential, periodic BC) + dual-rotor 1-D circuit | `geom` / `field --job results/afpm-pcb-motor` (`field` writes `Bg_fem_T`, `Bg_circuit_T`, `flux_per_pole_{fem,circuit}_Wb`) |
| `afpm_getdp.py` | **full-stack 2D** magnetostatics with GetDP (A_z, conforming mesh, layer-averaged coil flux) | `--job results/afpm-pcb-motor/getdp2d [--multi-slice 5]` (needs a `getdp` binary) |
| `getdp_bootstrap.sh` | rootless GetDP install (Ubuntu/Debian: apt download + dpkg -x) | `./scripts/getdp_bootstrap.sh` then `GETDP=... python scripts/afpm_getdp.py ...` |
| `afpm_viz.py` | assembly render, r-z section, `Kt(N, h_m)` study | `--job results/afpm-pcb-motor` |

## Drawing / projection (optional)

| Script | Purpose | Usage |
|---|---|---|
| `fc_drawing_export.py` | runs **inside** FreeCADCmd: STEP → DXF/SVG | `set CAE_JOB=<dir>` then `FreeCADCmd.exe -c "exec(open('scripts/fc_drawing_export.py').read())"` |
| `annotate_dxf.py` | adds title block + dimensions, exports PDF | `--job results/box-cantilever-freecad` |

## Solver invocation

CalculiX is not a Python module. From the case directory:

```powershell
ccx_i8.exe -i job        # structural
ccx_i8.exe -i steady     # thermal
```

`ccx.exe` (the PaStiX build) crashes with `0xC0000005` on this toolchain — always use
`ccx_i8.exe`. See `docs/SETUP.md`.
