#!/usr/bin/env python
"""最小 FRD 读取器：把 CalculiX 的 .frd 结果叠加到已有的 part.inp 网格上。

为什么不直接用 ccx2paraview：
  ccx2paraview 3.2.0 在 numpy>=2 下 `calculate_principal()` 会抛
  TypeError（复数特征值排序），而且它会自行重建网格。这里只做两件事：
    1) 从 .frd 的 100CL 结果块读位移/应力（按节点/单元编号索引）；
    2) 用 part.inp 的网格拓扑（C3D4/C3D10）建 VTK UnstructuredGrid。

FRD 结果块结构：
    100CL  101 1.0 ... 357 0 1 1      <- 结果块头（含节点数）
     -4  DISP        4    1           <- 数据集名（DISP / STRESS）
     -5  D1          1    2    1    0 <- 分量定义
     -1         1 0.0 0.0 0.0         <- 数据行（索引 + 分量）
     -3                               <- 块结束
"""
from __future__ import annotations

import json
from pathlib import Path


def read_inp_mesh(inp_path: Path):
    """读 part.inp 的 *NODE 与 *ELEMENT（只收 C3D4/C3D10）。"""
    nodes: dict[int, tuple[float, float, float]] = {}
    elements: list[tuple[str, list[int]]] = []
    mode = None
    etype = None
    with inp_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("*"):
                up = line.upper()
                if up.startswith("*NODE"):
                    mode = "node"
                elif up.startswith("*ELEMENT"):
                    mode = "elem"
                    etype = "C3D10" if "C3D10" in up else ("C3D4" if "C3D4" in up else None)
                else:
                    mode = None
                continue
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if mode == "node" and len(parts) >= 4:
                try:
                    nodes[int(parts[0])] = (float(parts[1]), float(parts[2]), float(parts[3]))
                except ValueError:
                    pass
            elif mode == "elem" and etype and len(parts) >= 5:
                elements.append((etype, [int(p) for p in parts[1:]]))
    return nodes, elements


def read_frd_results(frd_path: Path) -> dict[str, dict[int, list[float]]]:
    """返回 {'DISP': {node_id: [ux,uy,uz]}, 'STRESS': {elem_id: [sxx,...]}}。"""
    results: dict[str, dict[int, list[float]]] = {}
    name: str | None = None
    pending: tuple[int, list[float]] | None = None

    def flush():
        nonlocal pending
        if name and pending:
            results.setdefault(name, {})[pending[0]] = pending[1]
        pending = None

    with frd_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if not line.strip():
                continue

            # 结果块开始：重置状态，名字等 -4 行再定。
            # 注意必须锚定行首：定宽数据行常常正好 100 字符，用 `"100CL" in line`
            # 会把每一条数据行都误判成块头。
            if line.lstrip().startswith("100CL"):
                flush()
                name = None
                continue

            # 数据集名：' -4  DISP' / ' -4  STRESS'
            if line.startswith(" -4"):
                flush()
                up = line.upper()
                if "DISP" in up:
                    name = "DISP"
                elif "STRESS" in up or "SXX" in up:
                    name = "STRESS"
                else:
                    name = None
                continue

            # 块结束
            if line.startswith(" -3"):
                flush()
                name = None
                continue

            if not name:
                continue

            if line.startswith(" -1") or line.startswith(" -2"):
                flush()
                # 定宽字段：'-1' 后 10 字符是编号，之后每 12 字符一个分量；
                # 数值之间可能没有空格（如 '5-5.05751E-04'），不能直接 split()。
                idx_field = line[3:13].strip()
                if not idx_field:
                    continue
                try:
                    idx = int(idx_field)
                except ValueError:
                    continue
                vals = []
                pos = 13
                while pos < len(line):
                    chunk = line[pos : pos + 12].strip()
                    pos += 12
                    if not chunk:
                        continue
                    try:
                        vals.append(float(chunk))
                    except ValueError:
                        pass
                if vals:
                    pending = (idx, vals)
            elif pending is not None and not line.lstrip().startswith("-"):
                try:
                    pending[1].extend(float(v) for v in line.split())
                except ValueError:
                    pass
    flush()
    return results


def build_vtk(job_dir: Path, nodes, elements, disp, stress):
    import numpy as np
    import pyvista as pv

    ids = sorted(nodes)
    index = {nid: i for i, nid in enumerate(ids)}
    points = np.array([nodes[n] for n in ids], dtype=float)

    cell_types = {"C3D4": pv.CellType.TETRA, "C3D10": pv.CellType.QUADRATIC_TETRA}
    # VTK legacy 单元数组格式：[n0, p0..pn, n1, p0..pn, ...]
    flat: list[int] = []
    types: list[int] = []
    for etype, conn_ids in elements:
        if etype not in cell_types:
            continue
        if any(n not in index for n in conn_ids):
            continue
        flat.append(len(conn_ids))
        flat.extend(index[n] for n in conn_ids)
        types.append(cell_types[etype])

    grid = pv.UnstructuredGrid(np.array(flat, dtype=np.int64),
                               np.array(types, dtype=np.uint8),
                               points)

    if disp:
        arr = np.zeros((len(ids), 3))
        for nid, v in disp.items():
            if nid in index and len(v) >= 3:
                arr[index[nid]] = v[:3]
        grid.point_data["U"] = arr
        grid.point_data["U_mag"] = np.linalg.norm(arr, axis=1)

    if stress:
        s = np.zeros((len(elements), 6))
        for i, _ in enumerate(elements):
            eid = i + 1
            if eid in stress and len(stress[eid]) >= 6:
                s[i] = stress[eid][:6]
        grid.cell_data["S"] = s
        vm = (
            0.5 * ((s[:, 0] - s[:, 1]) ** 2 + (s[:, 1] - s[:, 2]) ** 2 + (s[:, 2] - s[:, 0]) ** 2)
            + 3.0 * (s[:, 3] ** 2 + s[:, 4] ** 2 + s[:, 5] ** 2)
        ) ** 0.5
        grid.cell_data["S_vm"] = vm
        # 不在读完就做点平均：体网格的节点平均会把内部单元值混到表面，
        # 云图会出现斑点。平滑放到渲染阶段只对"外表面"做（见 render.py::_surface）。

    out = job_dir / "job.vtu"
    grid.save(str(out))
    return out, grid


def convert(job_dir: Path) -> Path:
    nodes, elements = read_inp_mesh(job_dir / "part.inp")
    res = read_frd_results(job_dir / "job.frd")
    if not nodes or not elements:
        raise SystemExit("ERROR: part.inp 中没有可用网格")
    out, grid = build_vtk(job_dir, nodes, elements, res.get("DISP", {}), res.get("STRESS", {}))
    (job_dir / "frd.json").write_text(
        json.dumps({"arrays": list(res.keys()), "n_points": int(grid.n_points),
                    "n_cells": int(grid.n_cells)}, ensure_ascii=False),
        encoding="utf-8",
    )
    return out
