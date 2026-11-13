#!/usr/bin/env python
"""最小 FRD 读取器：把 CalculiX 的 .frd 结果叠加到已有的 part.inp 网格上。

为什么不直接用 ccx2paraview：
  ccx2paraview 3.2.0 在 numpy>=2 下 `calculate_principal()` 会抛
  TypeError（复数特征值排序），而且它会自行重建网格。这里只做两件事：
    1) 从 .frd 的 100CL 结果块读位移/应力（**每个记录对应一个节点**）；
    2) 用 part.inp 的网格拓扑（C3D4/C3D10）建 VTK UnstructuredGrid。

重要语义（2026-11 修正）：
  CalculiX 在 .frd 中写的是**节点结果**：每个节点一条记录，分量由单元积分点
  外插到节点并在共享该节点的单元之间平均。所以 `STRESS` 字典的键是**节点 id**，
  不是单元 id。旧实现把节点表按单元 id 塞进 `cell_data`（两者都从 1 开始编
  号，静默错位）；本版把节点值放进 `point_data["S"]`，`cell_data["S"]` 用单元
  连接上的节点平均值（由节点值派生，供云图使用）。

用法：
    python scripts/frd_reader.py --job <dir>     # 写 job.vtu、frd.json、result.json

FRD 结果块结构：
    100CL  101 1.0 ... 357 0 1 1      <- 结果块头（记录数 = 节点数）
     -4  DISP        4    1           <- 数据集名（DISP / STRESS）
     -5  D1          1    2    1    0 <- 分量定义
     -1         1 0.0 0.0 0.0         <- 数据行（节点编号 + 分量）
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
    """返回 {'DISP': {node_id: [ux,uy,uz]}, 'STRESS': {node_id: [sxx,...]}}。

    STRESS 的键是**节点 id**（CalculiX 的 FRD 节点结果），不是单元 id。
    """
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


def _von_mises(s):
    """s[..., 0:6] = sxx, syy, szz, sxy, syz, szx -> von Mises."""
    return (
        0.5 * ((s[..., 0] - s[..., 1]) ** 2
               + (s[..., 1] - s[..., 2]) ** 2
               + (s[..., 2] - s[..., 0]) ** 2)
        + 3.0 * (s[..., 3] ** 2 + s[..., 4] ** 2 + s[..., 5] ** 2)
    ) ** 0.5


def build_vtk(job_dir: Path, nodes, elements, disp, stress):
    """写 <job>/job.vtu。

    * point_data["S"] / ["S_vm"]  = FRD 的原生**节点**值（真实场；峰值即"节点外插峰值"）；
    * cell_data["S"]  / ["S_vm"]  = 每个单元连接上的节点平均（派生量，供云图用）。

    这样既保留物理上正确的节点场，又给渲染器一个与单元对齐的字段；不再把
    节点编号当单元编号使用。
    """
    import numpy as np
    import pyvista as pv

    ids = sorted(nodes)
    index = {nid: i for i, nid in enumerate(ids)}
    points = np.array([nodes[n] for n in ids], dtype=float)

    cell_types = {"C3D4": pv.CellType.TETRA, "C3D10": pv.CellType.QUADRATIC_TETRA}
    # VTK legacy 单元数组格式：[n0, p0..pn, n1, p0..pn, ...]
    flat: list[int] = []
    types: list[int] = []
    used: list[list[int]] = []
    for etype, conn_ids in elements:
        if etype not in cell_types:
            continue
        if any(n not in index for n in conn_ids):
            continue
        local = [index[n] for n in conn_ids]
        flat.append(len(local))
        flat.extend(local)
        types.append(cell_types[etype])
        used.append(local)

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
        nodal = np.zeros((len(ids), 6))
        for nid, v in stress.items():
            if nid in index and len(v) >= 6:
                nodal[index[nid]] = v[:6]
        grid.point_data["S"] = nodal
        grid.point_data["S_vm"] = _von_mises(nodal)

        cell = np.zeros((len(used), 6))
        for i, conn in enumerate(used):
            cell[i] = nodal[conn].mean(axis=0)
        grid.cell_data["S"] = cell
        grid.cell_data["S_vm"] = _von_mises(cell)

    out = job_dir / "job.vtu"
    grid.save(str(out))
    return out, grid


def summarize(job_dir: Path, grid) -> dict:
    """result.json 的数值部分（render.py 与外层 CLI 共用同一口径）。"""
    info: dict = {
        "vtk": str(job_dir / "job.vtu"),
        "n_points": int(grid.n_points),
        "n_cells": int(grid.n_cells),
        "arrays": list(dict.fromkeys(grid.array_names)),
    }
    if "U_mag" in grid.point_data:
        info["max_disp_mm"] = float(grid.point_data["U_mag"].max())
    if "S_vm" in grid.point_data:
        info["max_vm_stress_MPa"] = float(grid.point_data["S_vm"].max())
        info["max_vm_stress_note"] = (
            "nodal extrapolated peak from raw FRD (values averaged over elements at nodes)"
        )
    if "S_vm" in grid.cell_data:
        info["max_vm_stress_element_avg_MPa"] = float(grid.cell_data["S_vm"].max())
    return info


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


def write_result(job_dir: Path) -> dict:
    """写 <job>/result.json（数值 + job.sta / job.dat 摘要）。"""
    import pyvista as pv

    convert(job_dir)
    grid = pv.read(str(job_dir / "job.vtu"))
    info = summarize(job_dir, grid)

    sta = job_dir / "job.sta"
    if sta.exists():
        lines = [ln for ln in sta.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        info["sta_tail"] = lines[-3:]

    info["errors"] = []
    dat = job_dir / "job.dat"
    if dat.exists():
        text = dat.read_text(encoding="utf-8", errors="replace")
        info["errors"] = [ln.strip() for ln in text.splitlines() if "*ERROR" in ln.upper()][:10]

    (job_dir / "result.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    return info


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="FRD -> job.vtu + frd.json + result.json（节点结果）")
    ap.add_argument("--job", required=True)
    args = ap.parse_args(argv)
    job_dir = Path(args.job).resolve()
    info = write_result(job_dir)
    print(json.dumps(info, ensure_ascii=False))
    return 0 if not info.get("errors") else 4


if __name__ == "__main__":
    raise SystemExit(main())
