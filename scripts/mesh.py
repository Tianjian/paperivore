#!/usr/bin/env python
"""STEP -> 四面体网格（part.msh + part.inp）+ groups.json（精确节点集合）

用法： python mesh.py --job C:\\cae\\jobs\\job-0001

约定（与 params.json 对应）：
  FIXED = 最小 X 端面（固定约束）
  LOAD  = 最大 X 端面（施加载荷）
  SOLID = 全部体单元

关键实现细节（踩过的坑）：
  1. 只给“体”建 Physical Group。若给面也建组，gmsh 的 Abaqus 导出会写
     `*ELEMENT, type=CPS6`，ccx 会把它当平面应力问题并报
     "plane stress elements should lie in z=0"。
  2. .inp 必须用 gmsh 自带写出器：二阶四面体的 C3D10 节点顺序由 gmsh
     处理，手工拼连接表会触发 "nonpositive jacobian"。
  3. FIXED/LOAD 的节点集合按坐标平面筛选（nodes_on_x），不再依赖面单元。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def face_by_x(gmsh, surfaces, want_max: bool, tol_rel: float = 1e-6):
    """在所有面中挑 X 坐标极值所在的那些面。返回 [(2, tag), ...]。"""
    xs = []
    for dim, tag in surfaces:
        xmin, _, _, xmax, _, _ = gmsh.model.getBoundingBox(dim, tag)
        xs.append(((xmin + xmax) / 2.0, tag))
    if not xs:
        raise RuntimeError("STEP 中没有可用的面")
    xs.sort(key=lambda t: t[0])
    span = max(abs(xs[-1][0] - xs[0][0]), 1e-12)
    target = xs[-1][0] if want_max else xs[0][0]
    return [(2, t) for x, t in xs if abs(x - target) <= tol_rel * span]


def nodes_on_x(gmsh, plane_x: float, tol_rel: float = 1e-6) -> list[int]:
    """取落在 X = plane_x 平面上的节点（FIXED/LOAD 用）。"""
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    tol = tol_rel * max(abs(plane_x), 1.0)
    return sorted(
        int(t) for i, t in enumerate(node_tags) if abs(coords[3 * i] - plane_x) <= tol
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    args = ap.parse_args()

    job_dir = Path(args.job).resolve()
    params = json.loads((job_dir / "params.json").read_text(encoding="utf-8-sig"))
    mesh_cfg = params.get("mesh", {})

    step_path = job_dir / "part.step"
    if not step_path.exists():
        print(f"ERROR: 缺少 {step_path}，先跑 model.py", file=sys.stderr)
        return 2

    import gmsh

    gmsh.initialize(["gmsh", "-v", "2"])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", int(params.get("solver", {}).get("threads", 8)))
        gmsh.option.setNumber("Mesh.SaveAll", 0)
        gmsh.model.add("part")
        gmsh.model.occ.importShapes(str(step_path))
        gmsh.model.occ.synchronize()

        volumes = gmsh.model.getEntities(3)
        surfaces = gmsh.model.getEntities(2)
        if not volumes:
            print("ERROR: STEP 未导入任何体（可能是曲面片体）", file=sys.stderr)
            return 3

        fixed = face_by_x(gmsh, surfaces, want_max=False)
        load = face_by_x(gmsh, surfaces, want_max=True)
        if not fixed or not load:
            print("ERROR: 未能定位固定/加载端面", file=sys.stderr)
            return 3

        # 只给体建组（见文件头说明）
        gmsh.model.addPhysicalGroup(3, [t for _, t in volumes], tag=1, name="SOLID")

        # 载荷端面局部加密：Distance + Threshold 背景场
        d = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(d, "SurfacesList", [t for _, t in load])
        th = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(th, "InField", d)
        gmsh.model.mesh.field.setNumber(th, "SizeMin", float(mesh_cfg.get("size_min", 1.0)))
        gmsh.model.mesh.field.setNumber(th, "SizeMax", float(mesh_cfg.get("size_max", 6.0)))
        gmsh.model.mesh.field.setNumber(th, "DistMin", 0.0)
        gmsh.model.mesh.field.setNumber(th, "DistMax", 40.0)
        gmsh.model.mesh.field.setAsBackgroundMesh(th)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)

        gmsh.model.mesh.generate(3)
        gmsh.model.mesh.optimize("Netgen")
        order = int(mesh_cfg.get("order", 2))
        if order > 1:
            gmsh.model.mesh.setOrder(order)

        msh_path = job_dir / "part.msh"
        inp_path = job_dir / "part.inp"
        gmsh.write(str(msh_path))
        gmsh.write(str(inp_path))

        plane_fixed = gmsh.model.getBoundingBox(2, fixed[0][1])[0]
        plane_load = gmsh.model.getBoundingBox(2, load[0][1])[3]
        fixed_nodes = nodes_on_x(gmsh, plane_fixed)
        load_nodes = nodes_on_x(gmsh, plane_load)

        all_nodes, _, _ = gmsh.model.mesh.getNodes()
        etypes, etags, _ = gmsh.model.mesh.getElements(3)
        n_elems = sum(len(t) for t in etags)

        groups = {
            "FIXED": {"nodes": fixed_nodes, "plane_x": plane_fixed},
            "LOAD": {"nodes": load_nodes, "plane_x": plane_load},
            "counts": {
                "nodes_total": len(all_nodes),
                "nodes_fixed": len(fixed_nodes),
                "nodes_load": len(load_nodes),
                "elements_solid": n_elems,
            },
        }
        (job_dir / "groups.json").write_text(json.dumps(groups), encoding="utf-8")

        info = {
            "msh": str(msh_path),
            "inp": str(inp_path),
            "groups": str(job_dir / "groups.json"),
            "nodes": len(all_nodes),
            "volume_elements": n_elems,
            "element_order": order,
            "nodes_fixed": len(fixed_nodes),
            "nodes_load": len(load_nodes),
        }
        (job_dir / "mesh.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(info, ensure_ascii=False))
        return 0
    finally:
        gmsh.finalize()


if __name__ == "__main__":
    raise SystemExit(main())
