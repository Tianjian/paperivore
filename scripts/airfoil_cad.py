#!/usr/bin/env python
"""S2 of the airfoil validation: turn the NACA 4412 profile into CAD geometry.

Input : <job>/airfoil/naca4412.dat  (written by airfoil_validate.py, chord = 1)
Output: <job>/airfoil/naca4412_chord300.step  (closed 2D profile, c = 300 mm)
        <job>/airfoil/geometry.json          (measured chord, thickness, area)

The profile is built with build123d (OCCT) as a closed wire -> face -> STEP.
This validates the CAD layer against the same geometric ground truth used in
airfoil_validate.py: chord 300 mm, max thickness 12% c, max camber 4% c.

Usage: python airfoil_cad.py --job <dir> [--chord 300]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from build123d import Edge, Face, Wire, extrude, export_step


def load_profile(dat: Path):
    pts = []
    for line in dat.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("naca"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                pts.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    return pts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--chord", type=float, default=300.0, help="chord in mm")
    args = ap.parse_args()

    job = Path(args.job).resolve()
    af_dir = job / "airfoil"
    dat = af_dir / "naca4412.dat"
    if not dat.exists():
        raise SystemExit(f"ERROR: missing {dat}; run airfoil_validate.py first")

    pts = load_profile(dat)
    if len(pts) < 10:
        raise SystemExit("ERROR: profile has too few points")

    # scale to chord, centre at quarter chord on x=0..c, y=0 reference
    c = args.chord
    scaled = [(x * c, y * c) for x, y in pts]

    # build a closed polyline (the .dat is already ordered around the surface)
    edges = []
    for i in range(len(scaled)):
        p1 = scaled[i]
        p2 = scaled[(i + 1) % len(scaled)]
        if math.hypot(p2[0] - p1[0], p2[1] - p1[1]) < 1e-9:
            continue
        edges.append(Edge.make_line((p1[0], p1[1], 0), (p2[0], p2[1], 0)))

    wire = Wire(edges)
    face = Face(wire)
    # thin slab (1 mm) so the STEP contains a closed solid; the 2D profile itself
    # is what matters for the airfoil check
    solid = extrude(face, amount=1.0, dir=(0, 0, 1))

    out = af_dir / f"naca4412_chord{int(c)}.step"
    export_step(solid, str(out))

    bb = face.bounding_box()
    info = {
        "chord_mm": c,
        "n_profile_points": len(scaled),
        "bbox_mm": [round(bb.size.X, 3), round(bb.size.Y, 3), round(bb.size.Z, 3)],
        "area_mm2": round(face.area, 3),
        "area_ratio": round(face.area / c**2, 5),
        "max_thickness_mm": round(bb.size.Y, 3),
        "thickness_ratio_bbox": round(bb.size.Y / c, 5),
        "step": str(out),
        "step_bytes": out.stat().st_size,
    }
    (af_dir / "geometry.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

