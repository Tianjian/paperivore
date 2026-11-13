#!/usr/bin/env python
"""参数化零件建模：params.json -> part.step / part.stl

单位：mm。用法： python model.py --job C:\\cae\\jobs\\job-0001
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def load_params(job_dir: Path) -> dict:
    p = job_dir / "params.json"
    if not p.exists():
        raise SystemExit(f"缺少参数文件: {p}")
    # utf-8-sig: 兼容 PowerShell 写出的 BOM
    return json.loads(p.read_text(encoding="utf-8-sig"))


def build(geom: dict):
    from build123d import Box, fillet, Axis

    length = float(geom.get("length", 80.0))
    width = float(geom.get("width", 40.0))
    height = float(geom.get("height", 12.0))
    r = float(geom.get("fillet", 2.0))

    part = Box(length, width, height)
    if r > 0:
        part = fillet(part.edges().filter_by(Axis.Z), radius=r)
    return part


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True, help="工况目录（含 params.json）")
    args = ap.parse_args()

    job_dir = Path(args.job).resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    params = load_params(job_dir)

    t0 = time.time()
    from build123d import export_step, export_stl

    part = build(params.get("geometry", {}))
    if not part.is_valid:
        print("ERROR: 几何无效 (is_valid=False)", file=sys.stderr)
        return 2

    step_path = job_dir / "part.step"
    stl_path = job_dir / "part.stl"
    export_step(part, str(step_path))
    export_stl(part, str(stl_path), tolerance=0.05, angular_tolerance=0.2)

    bbox = part.bounding_box().size
    info = {
        "step": str(step_path),
        "stl": str(stl_path),
        "volume_mm3": round(part.volume, 6),
        "bbox_mm": [round(bbox.X, 3), round(bbox.Y, 3), round(bbox.Z, 3)],
        "elapsed_s": round(time.time() - t0, 3),
        "units": params.get("units", "mm-N-MPa"),
    }
    (job_dir / "model.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
