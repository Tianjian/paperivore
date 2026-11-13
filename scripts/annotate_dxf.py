#!/usr/bin/env python
"""Annotate a TechDraw geometry-only DXF with a title block + dimensions, then render a PDF.

Why this exists: FreeCAD 1.1.4 can export a TechDraw page to DXF headlessly, but the
DXF contains geometry only -- no dimensions, no title-block text, and no PDF/SVG
exporter is exposed to FreeCADCmd. This script closes that gap with ezdxf.

Input : <job>/freecad/drawing.dxf   (produced by fc_drawing_export.py under FreeCADCmd)
Output: <job>/freecad/drawing_annotated.dxf
        <job>/freecad/drawing.pdf          (A4 landscape)
        <job>/freecad/drawing_preview.png  (quick visual check)

Usage:
    python annotate_dxf.py --job <job dir>

Requires: ezdxf, matplotlib (pip).
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

# ISO A4 landscape, mm
PAGE_W, PAGE_H = 297.0, 210.0
MARGIN = 10.0


def view_boxes(msp):
    """Return {layer: (minx, miny, maxx, maxy)} for LINE/ARC/SPLINE entities."""
    boxes: dict[str, list[float]] = {}
    for e in msp:
        try:
            if e.dxftype() == "LINE":
                pts = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
            elif e.dxftype() == "ARC":
                c = e.dxf.center
                r = e.dxf.radius
                pts = [(c.x - r, c.y - r), (c.x + r, c.y + r)]
            else:
                continue
        except Exception:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        b = boxes.get(e.dxf.layer)
        if b is None:
            boxes[e.dxf.layer] = [min(xs), min(ys), max(xs), max(ys)]
        else:
            b[0] = min(b[0], min(xs))
            b[1] = min(b[1], min(ys))
            b[2] = max(b[2], max(xs))
            b[3] = max(b[3], max(ys))
    return {k: tuple(v) for k, v in boxes.items()}


def add_dim_h(msp, x1: float, x2: float, y: float, text: str, dim_style: str) -> None:
    """Horizontal linear dimension below y."""
    msp.add_linear_dim(base=(0, y), p1=(x1, y), p2=(x2, y), dimstyle=dim_style,
                       override={"dimtxsty": "Standard", "dimtxt": 2.5}).render()


def add_dim_v(msp, y1: float, y2: float, x: float, text: str, dim_style: str) -> None:
    """Vertical linear dimension left/right of x."""
    msp.add_linear_dim(base=(x, 0), p1=(x, y1), p2=(x, y2), angle=90, dimstyle=dim_style,
                       override={"dimtxsty": "Standard", "dimtxt": 2.5}).render()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--material", default="")
    ap.add_argument("--drawing-no", default="")
    ap.add_argument("--scale", default="1:1")
    args = ap.parse_args()

    job = Path(args.job).resolve()
    src = job / "freecad" / "drawing.dxf"
    if not src.exists():
        raise SystemExit(f"ERROR: missing {src}; run fc_drawing_export.py under FreeCADCmd first")

    doc = ezdxf.readfile(str(src))
    msp = doc.modelspace()

    # --- page frame + title block -------------------------------------------------
    doc.header["$INSUNITS"] = 4  # mm
    doc.header["$MEASUREMENT"] = 1
    frame = msp.add_lwpolyline(
        [(MARGIN, MARGIN), (PAGE_W - MARGIN, MARGIN),
         (PAGE_W - MARGIN, PAGE_H - MARGIN), (MARGIN, PAGE_H - MARGIN)],
        close=True, dxfattribs={"layer": "FRAME"},
    )
    frame.dxf.lineweight = 35

    tb_w, tb_h = 150.0, 36.0
    tb_x, tb_y = PAGE_W - MARGIN - tb_w, MARGIN
    msp.add_lwpolyline(
        [(tb_x, tb_y), (tb_x + tb_w, tb_y), (tb_x + tb_w, tb_y + tb_h), (tb_x, tb_y + tb_h)],
        close=True, dxfattribs={"layer": "FRAME"},
    )
    for i, h in enumerate((9.0, 9.0, 9.0)):
        y = tb_y + tb_h - (i + 1) * h
        msp.add_line((tb_x, y), (tb_x + tb_w, y), dxfattribs={"layer": "FRAME"})
    msp.add_line((tb_x + 45, tb_y), (tb_x + 45, tb_y + tb_h), dxfattribs={"layer": "FRAME"})

    # --- resolve a CJK TTF (used by matplotlib for the PDF overlay) -----------
    cjk_path = None
    try:
        from matplotlib import font_manager
        for name in ("Microsoft YaHei", "SimHei", "SimSun", "Noto Sans CJK SC"):
            try:
                cjk_path = font_manager.findfont(name, fallback_to_default=False)
                break
            except Exception:
                continue
    except Exception:
        cjk_path = None

    part_name = args.title or job.name
    rows = [
        ("PART NO.", part_name),
        ("MATERIAL", args.material or "steel"),
        ("DWG NO.", args.drawing_no or job.name.upper()),
        ("SCALE", args.scale or "1:1"),
    ]
    # NOTE: no TEXT entities are written into the DXF on purpose. ezdxf escapes CJK
    # as \U+XXXX and its renderer draws boxes; CAD apps read it, but our PDF is the
    # primary deliverable, so the title-block text is drawn by matplotlib and the
    # DXF stays a clean geometry + dimension file.

    # --- dimensions: use the union of all view boxes ---------------------------
    # Two independent views (Front + Top) would otherwise get overlapping
    # dimension lines. The union box gives the assembly/envelope dimensions,
    # which is what a quick review drawing needs.
    boxes = view_boxes(msp)
    geom = [(k, b) for k, b in boxes.items() if k not in ("FRAME", "TEXT", "DIM")]
    if not geom:
        raise SystemExit("ERROR: no view geometry found in DXF")
    x1 = min(b[0] for _, b in geom)
    y1 = min(b[1] for _, b in geom)
    x2 = max(b[2] for _, b in geom)
    y2 = max(b[3] for _, b in geom)
    w, h = x2 - x1, y2 - y1

    dim_style = "Standard"
    common = {"dimtxt": 2.5, "dimasz": 2.0, "dimexo": 1.0, "dimexe": 2.0,
              "dimdec": 1, "dimlunit": 2}
    # overall width below the lowest view
    msp.add_linear_dim(base=(0, y1 - 10), p1=(x1, y1), p2=(x2, y1),
                       dimstyle=dim_style, dxfattribs={"layer": "DIM"},
                       override={**common, "dimpost": ""}).render()
    # overall height right of the rightmost view
    msp.add_linear_dim(base=(x2 + 10, 0), p1=(x2, y1), p2=(x2, y2), angle=90,
                       dimstyle=dim_style, dxfattribs={"layer": "DIM"},
                       override={**common, "dimpost": ""}).render()

    out_dxf = job / "freecad" / "drawing_annotated.dxf"
    doc.saveas(str(out_dxf))

    # --- render to PDF (matplotlib, no GUI needed) -------------------------------
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy

    # Chinese labels need a CJK font; fall back to the default if none is installed.
    zh_ok = bool(cjk_path and os.path.exists(cjk_path))
    if zh_ok:
        from matplotlib import font_manager
        plt.rcParams["font.family"] = [font_manager.FontProperties(fname=cjk_path).get_name()]

    cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.BLACK)
    fig = plt.figure(figsize=(PAGE_W / 25.4, PAGE_H / 25.4), facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("white")
    ax.set_xlim(0, PAGE_W)
    ax.set_ylim(0, PAGE_H)
    ax.set_aspect("equal")
    Frontend(RenderContext(doc), MatplotlibBackend(ax), config=cfg).draw_layout(msp, finalize=True)

    # ezdxf writes CJK as \U+XXXX escapes; some renderers show boxes. Overlay the
    # title-block text directly with matplotlib so the PDF is always readable.
    for i, (label, value) in enumerate(rows):
        y = tb_y + tb_h - (i + 1) * 9.0 + 2.2
        ax.text(tb_x + 2, y, label, fontsize=6.5, va="bottom", ha="left", color="black")
        ax.text(tb_x + 47, y, str(value), fontsize=7.5, va="bottom", ha="left", color="black")

    pdf = job / "freecad" / "drawing.pdf"
    fig.savefig(str(pdf), format="pdf", dpi=300)
    png = job / "freecad" / "drawing_preview.png"
    fig.savefig(str(png), format="png", dpi=150)

    info = {
        "annotated_dxf": str(out_dxf),
        "pdf": str(pdf),
        "preview": str(png),
        "cjk_font": zh_ok,
        "views": {k: [round(v, 2) for v in box] for k, box in boxes.items()},
    }
    (job / "freecad" / "drawing.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
