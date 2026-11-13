#!/usr/bin/env python
"""Run inside FreeCADCmd: STEP -> .FCStd + TechDraw 2D DXF.

Usage (must be executed by FreeCADCmd, not by system Python):
    set CAE_JOB=C:\\cae\\jobs\\job-0001
    C:\\FreeCAD\\1.1.4\\FreeCADCmd.exe -c "exec(open(r'<this file>', encoding='utf-8').read())"

Input : <job>\\part.step
Output: <job>\\freecad\\model.FCStd
        <job>\\freecad\\drawing.dxf   (A4 landscape, 1:1, front + top views)
        <job>\\freecad\\report.json

Measured limits (FreeCAD 1.1.4 / Windows):
  * Part modelling, STEP import/export, .FCStd save: works headless
  * TechDraw.writeDXFPage: works headless, but writes GEOMETRY ONLY --
    title-block text is NOT included in the DXF
  * TechDraw.writeSVG / writePDF: not exposed by the C++ API
    (absent from dir(TechDraw)); headless PDF/SVG needs a GUI session,
    or draw the title block yourself with ezdxf
  * An uncaught exception still returns exit code 0: always try/except + sys.exit(n)
  * A positional .py file is imported as a MODULE first, so avoid script names
    that collide with FreeCAD submodules (e.g. do not name it freecad_*.py)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

import FreeCAD as App  # noqa: E402  (only importable inside FreeCADCmd)
import Part  # noqa: E402
import TechDraw  # noqa: E402

TEMPLATE_CANDIDATES = [
    "Mod/TechDraw/Templates/ISO/localized/zh-CN/landscape/A4_Landscape_CN_CLIP.svg",
    "Mod/TechDraw/Templates/ISO/A4_Landscape_ISO5457_minimal.svg",
    "Mod/TechDraw/Templates/Default_Template_A4_Landscape.svg",
]


def pick_template() -> str:
    for rel in TEMPLATE_CANDIDATES:
        path = os.path.join(App.getResourceDir(), rel)
        if os.path.exists(path):
            return path
    raise SystemExit("ERROR: no TechDraw A4 template found")


def main() -> int:
    # FreeCADCmd parses its own command line; unknown options such as --job make it
    # print help and exit. So read the job dir from CAE_JOB, and only fall back to
    # parse_known_args for the standalone case.
    job_env = os.environ.get("CAE_JOB")
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=False)
    args, _ = ap.parse_known_args()

    job = job_env or args.job
    if not job:
        print("ERROR: set CAE_JOB=<job dir> or pass --job", file=sys.stderr)
        return 2

    job = os.path.abspath(job)
    step = os.path.join(job, "part.step")
    if not os.path.exists(step):
        print(f"ERROR: missing {step}", file=sys.stderr)
        return 2

    outdir = os.path.join(job, "freecad")
    os.makedirs(outdir, exist_ok=True)

    # 1) import STEP
    doc = App.newDocument("cae")
    shape = Part.Shape()
    shape.read(step)
    if not shape.isValid():
        print("ERROR: imported STEP geometry is invalid", file=sys.stderr)
        return 3
    obj = doc.addObject("Part::Feature", "Part")
    obj.Shape = shape
    doc.recompute()

    info = {
        "step": step,
        "volume_mm3": round(shape.Volume, 3),
        "faces": len(shape.Faces),
        "edges": len(shape.Edges),
        "freecad_version": ".".join(str(v) for v in App.Version()[:3]),
    }

    # 2) save .FCStd
    fcstd = os.path.join(outdir, "model.FCStd")
    doc.saveAs(fcstd)
    info["fcstd"] = fcstd
    info["fcstd_bytes"] = os.path.getsize(fcstd)

    # 3) TechDraw 2D views -> DXF
    page = doc.addObject("TechDraw::DrawPage", "Page")
    tmpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
    tmpl.Template = pick_template()
    page.Template = tmpl

    front = doc.addObject("TechDraw::DrawViewPart", "Front")
    front.Source = [obj]
    front.Direction = App.Vector(0, -1, 0)
    page.addView(front)

    top = doc.addObject("TechDraw::DrawViewPart", "Top")
    top.Source = [obj]
    top.Direction = App.Vector(0, 0, 1)
    page.addView(top)
    doc.recompute()

    dxf = os.path.join(outdir, "drawing.dxf")
    TechDraw.writeDXFPage(page, dxf)
    info["dxf"] = dxf
    info["dxf_bytes"] = os.path.getsize(dxf) if os.path.exists(dxf) else 0
    info["note"] = "TechDraw headless export writes geometry only; title-block text needs ezdxf"

    report = os.path.join(outdir, "report.json")
    with open(report, "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=2, ensure_ascii=True)
    print(json.dumps(info, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(9)
