# Setting up the toolchain (Windows)

Everything below is free and open source. Total install ≈ 1.5 GB, mostly MSYS2.

## 1. Python

Python 3.11–3.13 (64-bit), then:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

`requirements.txt` pulls build123d (with the OCP/OCCT wheel), gmsh, pyvista, numpy, scipy,
matplotlib, ezdxf.

> **Note on the venv**: create it *inside* the repository. Moving a venv between drives
> breaks the `pyvenv.cfg` home path; recreating is faster than repairing.

## 2. CalculiX

The solver is not on PyPI. On Windows the least painful route is MSYS2:

```powershell
# install MSYS2 from https://www.msys2.org/ , then in an MSYS2 UCRT64 shell:
pacman -S mingw-w64-ucrt-x86_64-ccx
```

Then add to `PATH` for the session:

```powershell
$env:PATH = "C:\msys64\ucrt64\bin;" + $env:PATH
```

Verify:

```powershell
ccx_i8.exe -v
# optional: solve the bundled 1 mm-cube smoke deck (expect max |U| ≈ 5.17e-6 mm, < 0.1 s)
Push-Location scripts; ccx_i8.exe -i smoke; Pop-Location
```

### Why `ccx_i8` and not `ccx`

On this machine the default `ccx.exe` dies with `0xC0000005` (access violation) inside
PaStiX during the first solve. The `ccx_i8` (integer-8) build solves the same deck in
seconds. Always call `ccx_i8.exe -i <jobname>`.

## 2b. GetDP (AFPM case)

`scripts/afpm_getdp.py` needs a `getdp` (or `getdp-sparskit`) binary; CalculiX is not enough.
On Ubuntu/Debian a rootless install is provided:

```bash
./scripts/getdp_bootstrap.sh          # apt-get download + dpkg -x into ~/.cache/paperivore/getdp
# then:
GETDP=~/.cache/paperivore/getdp/root/usr/bin/getdp-sparskit \
  python scripts/afpm_getdp.py --job results/afpm-pcb-motor/getdp2d
```

On Windows, install GetDP from <https://getdp.info> (or ONELAB) and pass `--getdp <path>`.
`getdp --version` should print 3.x.

## 3. FreeCAD (optional — human review only)

The pipeline never needs FreeCAD; it is used to open a `STEP`, browse the model, and export
a drawing for eyeballing.

- Install **outside** any directory whose ACL denies `DeleteSubdirectoriesAndFiles`
  (a hardened workspace folder will make FreeCAD fail at start-up with *Access is denied*).
- `FreeCADCmd.exe --version` should print `1.1.4` or newer.
- Headless PDF/SVG export is **not** available in 1.1.4: `TechDraw` exposes no
  `writeSVG`/`writePDF` in the command-line build, and DXF export contains geometry only
  (no dimensions). Annotate with `ezdxf`/matplotlib instead — see `scripts/annotate_dxf.py`.

## 4. Sanity check

Run the smallest case end to end:

```powershell
.venv\Scripts\python scripts\model.py  --job results\box-cantilever-500N
.venv\Scripts\python scripts\mesh.py   --job results\box-cantilever-500N
.venv\Scripts\python scripts\deck.py   --job results\box-cantilever-500N
Push-Location results\box-cantilever-500N
ccx_i8.exe -i job
Pop-Location
.venv\Scripts\python scripts\frd_reader.py --job results\box-cantilever-500N
```

Expected: `result.json` with `max_disp_mm ≈ 0.0708` and `max_vm_stress_MPa ≈ 51.6` for the
500 N case.  `max_vm_stress_MPa` is the **nodal extrapolated peak** from the FRD (values
averaged over the elements sharing each node); the element-averaged peak is ≈40.4 MPa.
The peak sits on the clamped fillet edge and keeps rising with mesh refinement, so it is a
"mesh-band reproducible" number, not a converged stress.  Add `python scripts/render.py --job
<dir>` if you also want the PNGs (it reuses the same `frd_reader` summary).

## 5. Unit convention (structural)

`mm – N – MPa – t – s`:

| quantity | unit | note |
|---|---|---|
| length | mm | STEP from build123d is in mm |
| stress / modulus | MPa | |
| density | t/mm³ | steel = 7.85e-9 |
| gravity | mm/s² | 9810 |
| force | N | |

Thermal cases use **SI** (m, N, Pa, kg, s, K) instead — mixing the two is the single most
common source of 10³–10⁶ errors. Check the header of every script before reusing it.
