# Papers — provenance & licences

These PDFs are kept **for reproducibility only**: every benchmark in `docs/` can be checked
against the source numbers without a paywall. Each file remains under its own licence; the
MIT licence of this repository applies to the code, not to these PDFs.

If you are a rights holder and want a file removed, open an issue — it will be deleted.

| File | Paper | Venue / year | Identifier | Licence | Role | Outcome |
|---|---|---|---|---|---|---|
| `naca4412_zenodo.pdf` | NACA 4412 airfoil study (geometry + CFD), A. Sarkar & V. K. Mahto | IJIRT **12**(2): 3882–3886, 2025 (hosted on Zenodo) | [10.5281/zenodo.16422521](https://doi.org/10.5281/zenodo.16422521) | open (per record; no licence statement inside the PDF) | Round 1 ground truth: airfoil geometry, `Cl`, wing loads | ✅ pass — geometry < 0.1 %, tip deflection +6.7 % (section stress ≤3.1 %) |
| `jten.pdf` | Characterization of NACA 2412 and NACA 4412 airfoils: effects of angle of attack on aerodynamics coefficients (D. Akgumus Gok, K. N. M. Al-Nimer) | J. Thermal Engineering **10**(6): 1524–1538, 2024 | [10.14744/thermal.0000892](https://doi.org/10.14744/thermal.0000892) | **CC BY-NC** (stated in the PDF) | Round 2: 10 lift + 10 drag points at 5 angles of attack | ✅ pass pre-stall (4.5–23 %); the paper's 0° `Cl = 0.0589` and its force/coefficient tables are internally inconsistent (flagged, not used as evidence) |
| `shahrood_hawt.pdf` | Aerodynamic Performance Assessment and Blade Design Optimization of HAWTs | Renewable Energy Research and Applications **7**(1): 117–127, 2026 | [10.22044/rera.2026.17534.1520](https://doi.org/10.22044/rera.2026.17534.1520) | open access | Round 3: 25 m blade design rules, `Cp,max = 0.52`, power points | ✅ / ⚠️ — `Cp` −11 % (design-law φ + quadrature), 9 m/s power −8.9 %; 14 m/s −21.5 % (post-stall polar) |
| `exhaust_tsci.pdf` | Heat Transfer in Exhaust System of a Cold Start Engine at Low Environmental Temperature | Thermal Science **14** (Suppl.): S219–S232, 2010 | — (no DOI in the PDF) | open access (journal) | Round 4: pipe geometry `L=200 mm, D=39 mm, t=1.5 mm`, Č.4571 properties | ✅ pass — 0.001 % vs exact solution (conformance test); 0.168 % vs fin |
| `pcb_afpm.pdf` | High Torque Density PCB Axial Flux Permanent Magnet Motor for Micro Robots | arXiv preprint, 2025 | [arXiv:2509.23561](https://arxiv.org/abs/2509.23561) | arXiv licence (per listing; no statement inside the PDF) | Round 5: AFPM design table + measured `Kt`, `R` | ❌ fail — `Kt` −53 % (2-D field) / −62 % (corrected dual-rotor circuit); missing magnet thickness / turn definition |
| `exhaust_manifold.pdf` | An Analysis of the Material and Design of an Exhaust Manifold for A Single-Cylinder ICE | J. Adv. Res. Appl. Sci. Eng. Tech. **30**(2): 163–175, 2023 | — (no DOI in the PDF) | open access | **screened out** — contains a steady-state thermal study, but the field is shown only as contours (no pointwise data) and the geometry/BCs are insufficient to rebuild it | — |

## How the prey is chosen

1. **Numbers, not pictures.** At least one tabulated or digitizable value that a solver can
   be compared against. Papers with only contour plots are rejected.
2. **Complete geometry + BCs.** A benchmark you have to guess is not a benchmark.
3. **Open licence.** The PDF must be legally redistributable for the repository to keep it.
4. **Internal consistency check first.** Before modelling, the paper's own tables are
   cross-checked (e.g. force vs coefficient vs reference area). A paper that survives the
   check is benchmarked; one that does not is rejected. One candidate was rejected
   outright for irreconcilable tables plus contour-only outputs. When the paper is
   otherwise usable, the anomaly is flagged and the case is scored only on the consistent
   points: `jten.pdf` reports `Cl = 0.0589` at 0° (thin-airfoil theory: 0.228; its force
   and coefficient tables cannot be reconciled by any single reference area), so Round 2
   quotes the anomaly and relies on the pre-stall points.

## Licence status

- Verified from the document itself: `jten.pdf` (CC BY-NC).
- Stated open access by the publisher: `shahrood_hawt.pdf`, `exhaust_tsci.pdf`,
  `exhaust_manifold.pdf`.
- Per record / per listing: `naca4412_zenodo.pdf`, `pcb_afpm.pdf`.
- The other PDFs carry **no licence statement inside the document**; their status above is
  taken from the publisher/record page, not from the file itself.
- If any status is wrong, the file will be replaced with a link instead of a copy.

## Transcription fixes (2026-11-13)

- `jten.pdf` title and authors corrected (they were wrong in the scripts, docs and the
  stored `polar.json`).
- The two rows above that lacked an `Identifier` cell were fixed (the Markdown table was
  misaligned).
- `exhaust_manifold.pdf` was described as "flow-only"; it does contain a steady-state
  thermal analysis, and the rejection reason is now the absence of pointwise thermal data.
