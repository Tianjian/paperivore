# Paperivore — documentation index

One report per paper. Each one follows the same shape: **parameters extracted →
model built → comparison → verdict → what was learned** (including the paper's own
defects). Read them in order if you want the story, or jump to the one that matches
your physics.

| # | Case | What it proves | Verdict | Report |
|---|---|---|---|---|
| 0 | Windows toolchain | build123d · gmsh · CalculiX · PyVista wired together, pitfalls catalogued | ✅ | [Toolchain report](CAD-CAE-Windows-Toolchain-Report.md) |
| 0b | FreeCAD | where a GUI CAD actually helps, and why headless drawing export fails | ⚠️ conditional | [Postmortem](FreeCAD-necessity-and-deployment-postmortem.md) |
| 1 | NACA 4412 wing | airfoil geometry + box-spar FEA against beam theory | ✅ | [Report](Airfoil-Validation-Report.md) |
| 2 | NACA 2412 / 4412 polars | 10 lift points, lift-curve slope, stall onset | ✅ | [Report](Airfoil-Validation-2-Report.md) |
| 3 | 25 m wind-turbine blade | Glauert design, BEM `Cp–TSR`, power curve, solid FEA | ✅ / ⚠️ | [Report](Wind-Blade-Validation-Report.md) |
| 4 | Exhaust pipe | steady conduction + two-sided convection vs exact and fin solutions | ✅ | [Report](Thermal-Pipe-Validation-Report.md) |
| 5 | PCB axial-flux motor | magnetic circuit + custom 2D magnetostatics | ❌ | [Report](AFPM-EM-Validation-Report.md) |

## Setup

[docs/SETUP.md](SETUP.md) — Python, MSYS2/CalculiX (`ccx_i8`!), optional FreeCAD, unit
conventions, and the sanity-check command that must reproduce `0.0708 mm` at 500 N.

## How to read a verdict

| Mark | Meaning |
|---|---|
| ✅ | the number lands inside the stated tolerance and the tolerance is justified |
| ⚠️ | partly reproduced, with the residual explained |
| ❌ | not reproduced — and the report says why, with evidence |
| ➖ | not verifiable with this toolchain (no viscous CFD, no 3D EM, …) |

## The one-line summary of every report

- **Toolchain**: 2.5 GB of environment, 11 chapters of pitfalls, all open source.
- **FreeCAD**: keep it as a human review station, never in the automated loop.
- **Airfoil #1**: geometry is trivial; the 6.7 % deflection offset is the real lesson.
- **Airfoil #2**: inviscid theory over-predicts lift — by design, not by bug.
- **Wind blade**: BEM gets `Cp` within 11 %; the low-TSR polar is where it loses.
- **Thermal**: 0.001 % against an exact solution — and a 1.7 % "error" that was the
  reference model's fault, not the solver's.
- **Motor**: the toolchain can now compute magnetic fields, and immediately found that
  the paper's own parameter set cannot reproduce its measured torque constant.
