# Papers — provenance & licences

These PDFs are kept **for reproducibility only**: every benchmark in `docs/` can be checked
against the source numbers without a paywall. Each file remains under its own licence; the
MIT licence of this repository applies to the code, not to these PDFs.

If you are a rights holder and want a file removed, open an issue — it will be deleted.

| File | Paper | Venue / year | Identifier | Licence | Role | Outcome |
|---|---|---|---|---|---|---|
| `naca4412_zenodo.pdf` | NACA 4412 airfoil study (geometry + CFD) | Zenodo record | [10.5281/zenodo.16422521](https://doi.org/10.5281/zenodo.16422521) | open (per record) | Round 1 ground truth: airfoil geometry, `Cl`, wing loads | ✅ pass — geometry < 0.1 %, tip deflection +6.7 % |
| `jten.pdf` | Performance analysis of NACA 2412 / NACA 4412 airfoils | J. Thermal Engineering **10**(6): 1524–1538, 2024 | [10.14744/thermal.0000892](https://doi.org/10.14744/thermal.0000892) | **CC BY-NC** (stated in the PDF) | Round 2: 10 lift + 10 drag points at 5 angles of attack | ✅ pass pre-stall (4.5–23 %); data-quality issues found in the paper |
| `shahrood_hawt.pdf` | Aerodynamic Performance Assessment and Blade Design Optimization of HAWTs | Renewable Energy Research and Applications **7**(1): 117–127, 2026 | [10.22044/rera.2026.17534.1520](https://doi.org/10.22044/rera.2026.17534.1520) | open access | Round 3: 25 m blade design rules, `Cp,max = 0.52`, power points | ✅ / ⚠️ — `Cp` −11 %, 9 m/s power −8.9 % |
| `exhaust_tsci.pdf` | Heat Transfer in Exhaust System of a Cold Start Engine at Low Environmental Temperature | Thermal Science **14** (Suppl.): S219–S232, 2010 | open access (journal) | Round 4: pipe geometry `L=200 mm, D=39 mm, t=1.5 mm`, Č.4571 properties | ✅ pass — 0.001 % vs exact solution |
| `pcb_afpm.pdf` | High Torque Density PCB Axial Flux Permanent Magnet Motor for Micro Robots | arXiv preprint, 2025 | [arXiv:2509.23561](https://arxiv.org/abs/2509.23561) | arXiv licence (per listing) | Round 5: AFPM design table + measured `Kt`, `R` | ❌ fail — `Kt` −53 %, missing magnet thickness / turn definition |
| `exhaust_manifold.pdf` | An Analysis of the Material and Design of an Exhaust Manifold for A Single-Cylinder ICE | J. Adv. Res. Appl. Sci. Eng. Tech. **30**(2): 163–175, 2023 | open access | **screened out** — no reproducible thermal numbers (flow-only study) | — |

## How the prey is chosen

1. **Numbers, not pictures.** At least one tabulated or digitizable value that a solver can
   be compared against. Papers with only contour plots are rejected.
2. **Complete geometry + BCs.** A benchmark you have to guess is not a benchmark.
3. **Open licence.** The PDF must be legally redistributable for the repository to keep it.
4. **Internal consistency check first.** Before modelling, the paper's own tables are
   cross-checked (e.g. force vs coefficient vs reference area). Two candidates died here:
   one reported `Cl = 0.0589` at 0° while its own 5° value implied ≈ 0.23, and another's
   force and coefficient tables could not be reconciled by any single reference area.

## Licence status

- Verified from the document itself: `jten.pdf` (CC BY-NC).
- Stated open access by the publisher: `shahrood_hawt.pdf`, `exhaust_tsci.pdf`,
  `exhaust_manifold.pdf`.
- Per record / per listing: `naca4412_zenodo.pdf`, `pcb_afpm.pdf`.
- If any status is wrong, the file will be replaced with a link instead of a copy.
