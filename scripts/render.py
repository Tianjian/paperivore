#!/usr/bin/env python
"""CalculiX 结果后处理：job.frd -> job.vtu -> stress.png + result.json

用法： python render.py --job C:\\cae\\jobs\\job-0001 [--no-image]

实现说明：
  * 首选本目录的 frd_reader.py（极简 FRD 读取 + part.inp 网格），
    不依赖 ccx2paraview；后者在 numpy>=2 下会因复数特征值排序而崩溃。
  * 如果 frd_reader 失败，再退回 ccx2paraview（并打补丁）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def frd_to_vtk(job_dir: Path) -> Path:
    frd = job_dir / "job.frd"
    if not frd.exists():
        raise SystemExit(f"ERROR: 缺少 {frd}，求解未产生结果")
    for suffix in (".vtk", ".vtu"):
        old = job_dir / ("job" + suffix)
        if old.exists():
            old.unlink()

    try:
        import frd_reader

        return frd_reader.convert(job_dir)
    except Exception as exc:
        print(f"WARN: 内置 FRD 读取失败（{exc}），回退 ccx2paraview", file=sys.stderr)

    try:
        import numpy as np
        import ccx2paraview.common as _common

        # ccx2paraview 3.2.0 与 numpy 2.x 不兼容：复数特征值不能直接 sort。
        if not getattr(_common.CCX2ParaView, "_np2_patched", False):
            def _calculate_principal(self, block):
                res = block.copy()
                for i, val in enumerate(block.data):
                    t = np.array(val, dtype=float).reshape(3, 3)
                    res.data[i] = list(np.sort(np.real(np.linalg.eigvals(t))))
                return res

            _common.CCX2ParaView.calculate_principal = _calculate_principal
            _common.CCX2ParaView._np2_patched = True

        from ccx2paraview.cli import main as ccx_main  # type: ignore

        argv = sys.argv
        try:
            sys.argv = ["ccx2paraview", str(frd), "vtk"]
            ccx_main()
        finally:
            sys.argv = argv
    except Exception:
        subprocess.run([sys.executable, "-m", "ccx2paraview", str(frd), "vtk"],
                       cwd=job_dir, check=True)

    for suffix in (".vtk", ".vtu"):
        candidate = job_dir / ("job" + suffix)
        if candidate.exists():
            return candidate
    raise SystemExit("ERROR: 未能生成 job.vtu")


def summarize(vtk_path: Path) -> dict:
    import pyvista as pv

    mesh = pv.read(str(vtk_path))
    result: dict = {"vtk": str(vtk_path), "n_points": int(mesh.n_points), "arrays": list(mesh.array_names)}
    if "U_mag" in mesh.point_data:
        result["max_disp_mm"] = float(mesh.point_data["U_mag"].max())
    if "S_vm" in mesh.cell_data:
        result["max_vm_stress_MPa"] = float(mesh.cell_data["S_vm"].max())
        result["max_vm_stress_note"] = "element peak from raw FRD (un-averaged)"
    return result


def _surface(path: Path):
    """提取外表面并做单元->节点平均，得到干净的云图（不落盘）。"""
    import pyvista as pv

    grid = pv.read(str(path))
    surf = grid.extract_surface()
    if any(k in surf.cell_data for k in ("S", "S_vm")):
        surf = surf.cell_data_to_point_data()
    return surf


def screenshot(vtk_path: Path, png_path: Path, field: str = "S_vm") -> bool:
    try:
        import pyvista as pv

        pv.OFF_SCREEN = True
        mesh = _surface(vtk_path)
        scalars = None
        for cand in (field, "S_vm", "S", "U_mag", "U"):
            if cand in mesh.array_names:
                scalars = cand
                break
        plotter = pv.Plotter(off_screen=True)
        plotter.add_mesh(mesh, scalars=scalars, cmap="turbo", show_edges=False,
                         scalar_bar_args={"title": scalars or ""})
        plotter.view_isometric()
        plotter.screenshot(str(png_path))
        plotter.close()
        return png_path.exists()
    except Exception as exc:  # 无 GL 上下文时会失败
        print(f"WARN: screenshot failed ({exc}); numeric results are still valid", file=sys.stderr)
        return False


def side_view(vtk_path: Path, png_path: Path) -> bool:
    """侧视图：沿 -Y 看 XZ 面，便于观察梁的弯曲应力梯度（上拉下压）。"""
    try:
        import pyvista as pv

        pv.OFF_SCREEN = True
        mesh = _surface(vtk_path)
        plotter = pv.Plotter(off_screen=True)
        plotter.add_mesh(mesh, scalars="S_vm" if "S_vm" in mesh.array_names else None,
                         cmap="turbo", show_edges=False,
                         scalar_bar_args={"title": "S_vm [MPa]"})
        plotter.camera_position = "xz"
        plotter.screenshot(str(png_path))
        plotter.close()
        return png_path.exists()
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--no-image", action="store_true")
    args = ap.parse_args()

    job_dir = Path(args.job).resolve()
    vtk_path = frd_to_vtk(job_dir)
    info = summarize(vtk_path)

    png = job_dir / "stress.png"
    if not args.no_image:
        info["image"] = str(png) if screenshot(vtk_path, png) else None
        side = job_dir / "stress_side.png"
        info["image_side"] = str(side) if side_view(vtk_path, side) else None

    sta = job_dir / "job.sta"
    if sta.exists():
        lines = [ln for ln in sta.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        info["sta_tail"] = lines[-3:]

    dat = job_dir / "job.dat"
    if dat.exists():
        text = dat.read_text(encoding="utf-8", errors="replace")
        info["errors"] = [ln.strip() for ln in text.splitlines() if "*ERROR" in ln.upper()][:10]

    (job_dir / "result.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))
    return 0 if not info.get("errors") else 4


if __name__ == "__main__":
    raise SystemExit(main())
