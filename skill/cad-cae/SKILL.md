---
name: cad-cae
description: 在 Windows 上用开源工具链完成"参数化 CAD 建模 → 网格 → 有限元求解 → 结果出图"的完整闭环（build123d + Gmsh + CalculiX ccx + PyVista）。当任务涉及机械零件建模、静力/模态分析、参数扫描、应力云图时加载本技能。
---

# CAD/CAE 开源工具链作业规程（Windows）

本技能把一条**纯文件流**的 CAD→CAE 流水线固化下来。你（Agent）的职责是：
**改参数 → 跑脚本 → 校验产物 → 读结果**。不要试图用 GUI 自动化，不要临场发明命令。

## 0. 环境约定（先检查，不满足就停下来报告）

```powershell
$env:PYTHONUTF8 = "1"
$py = "C:\cae\venv\Scripts\python.exe"     # 见 docs/CAD-CAE-Windows-Toolchain-Report.md §5
$env:PATH = "C:\msys64\ucrt64\bin;" + $env:PATH

& $py -c "import build123d, gmsh, pyvista; print('ok')"
& ccx_i8.exe -v

# G4 求解器冒烟（0.04 s）：先证明"求解器本身能跑"，再碰真模型
# 复制 scripts\smoke.inp 到临时目录后执行：
#   ccx_i8.exe -i smoke   -> 退出码 0、smoke.sta 有 1 个增量
```

- 工作目录**必须**是短路径、无空格、无中文，例如 `C:\cae\jobs\job-0001`。
- 所有子进程都要设 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`。
- 不要永久修改系统 PATH；只在当前进程内前置 `ucrt64\bin`。
- **调用 `.ps1` 必须显式绕过执行策略**（未签名脚本默认被拒绝）：
  `powershell -NoProfile -ExecutionPolicy Bypass -File .\run_job.ps1 -Job <dir>`
  不要改机器级 `Set-ExecutionPolicy`。

## 1. 标准流水线（5 步，每步可单独重跑）

| 步骤 | 命令 | 输入 | 输出 | 成功判据 |
|---|---|---|---|---|
| 1 建模 | `& $py scripts/model.py --job <dir>` | `params.json` | `part.step`, `part.stl` | `part.is_valid`，体积 > 0 |
| 2 网格 | `& $py scripts/mesh.py --job <dir>` | `part.step` | `part.msh`, `part.inp`, `groups.json` | 节点数 > 0；`.inp` 只含 `C3D4/C3D10`（不能有 `CPS6`） |
| 3 组 deck | `& $py scripts/deck.py --job <dir>` | `part.inp` + `groups.json` | `job.inp` | 含 `*STEP`、`*STATIC`、`*NSET`、`*BOUNDARY`、`*CLOAD` |
| 4 求解 | `ccx_i8.exe -i job`（cwd = job 目录） | `job.inp` | `job.dat`, `job.frd`, `job.sta` | `.dat` 无 `*ERROR`；`.sta` 显示增量完成 |
| 5 出图 | `& $py scripts/render.py --job <dir>` | `job.frd` + `part.inp` | `job.vtu`, `stress.png`, `stress_side.png`, `result.json` | PNG 非纯色；`result.json` 数值有限且量级合理 |

一键：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_job.ps1 -Job <dir>`

**求解器必须用 `ccx_i8.exe`**：同包的 `ccx.exe` 2.23 在 PaStiX 分解阶段会 0xC0000005 崩溃（小模型也崩），`ccx_i8.exe` 正常。

### 1.1 可选第 6 步：FreeCAD 2D 工程图

只在**确实需要出图纸**时加，默认不加（FreeCAD 不是仿真必需项）。前置：FreeCAD 装在 `C:\FreeCAD\1.1.4`。

```powershell
# 一键（仿真 + 制图）
... run_job.ps1 -Job <dir> -WithFreeCAD

# 或手工两步
$env:CAE_JOB = "<dir>"
C:\FreeCAD\1.1.4\FreeCADCmd.exe -c "exec(open(r'<repo>\skills\cad-cae\scripts\fc_drawing_export.py', encoding='utf-8').read())"
& $py <repo>\skills\cad-cae\scripts\annotate_dxf.py --job <dir>
```

产物：`<dir>\freecad\{model.FCStd, drawing.dxf, drawing_annotated.dxf, drawing.pdf, drawing_preview.png}`。

**FreeCAD 无头能力边界（1.1.4 实测，不要假设更多）：**

| 能力 | 无头可用 | 说明 |
|---|---|---|
| Part 建模 / STEP 导入导出 / `.FCStd` 保存 | ✅ | 常规脚本即可 |
| `TechDraw.writeDXFPage` | ✅ | **只出几何线框**：无标题栏文字、无尺寸标注 |
| `TechDraw.writeSVG` / `writePDF` | ❌ | C++ API 未暴露（`dir(TechDraw)` 里没有）；出 PDF 靠 `annotate_dxf.py` 用 ezdxf+matplotlib 补 |
| 未捕获异常 | ⚠ | **退出码仍是 0**；必须脚本内 `try/except` + `sys.exit(n)`，外部再校验产物 |

**调用 FreeCADCmd 的三条硬规则：**

1. 作业目录走环境变量 `CAE_JOB`，不要用 `--job`（FreeCADCmd 会自己解析 argv 并拒绝未知参数）。
2. 脚本名不要以 `freecad` 开头（位置参数 `.py` 会先按模块 import，与 FreeCAD 子模块冲突）。
3. FreeCAD **不能装在带 Deny ACE 的目录**（本工作区 ACL 有 `Everyone: Deny DeleteSubdirectoriesAndFiles`，会 `Access is denied`）→ 装到 `C:\FreeCAD\1.1.4`。

## 2. `params.json` 契约

```json
{
  "geometry": { "length": 80.0, "width": 40.0, "height": 12.0, "fillet": 2.0 },
  "material": { "name": "steel", "E": 210000.0, "nu": 0.3, "rho": 7.85e-9 },
  "mesh":     { "size_min": 0.8, "size_max": 4.0, "order": 2 },
  "bc": {
    "fixed_face_tag": 10,
    "load_face_tag": 20,
    "load_total_N": 500.0,
    "load_direction": [0, 0, -1]
  },
  "solver":   { "analysis": "static", "threads": 8 },
  "units":    "mm-N-MPa"
}
```

**单位制固定为 mm-N-MPa**（E=210000 MPa，密度 7.85e-9 t/mm³）。换单位是本流水线最常见的错误来源。

## 3. 铁律（违反会静默出错）

1. **STEP 是几何契约**：建模只输出 STEP；STL 只用于打印/预览，不回灌。
2. **BC 由 `mesh.py` 按坐标端面自动识别**（最小 X = FIXED，最大 X = LOAD），节点号写进 `groups.json`；不要让 LLM 手写节点列表。
3. **不相信退出码**：CalculiX 可能返回 0 但 `.dat` 里有 `*ERROR`；FreeCAD REPL 永远返回 0。必须查产物 + 日志。
4. **一次只改一个变量**：参数扫描时每个工况一个独立目录，不要复用目录（ccx 会覆盖 `job.*`）。
5. **失败不要硬修**：先读 `job.dat` 尾部和 `job.sta`，把错误原文贴给用户，再决定是否调整网格/约束。

## 4. 常见故障速查

| 现象 | 原因 | 处理 |
|---|---|---|
| 进程退出码 `-1073741819`（0xC0000005） | `ccx.exe` 2.23 的 PaStiX 缺陷 | 改用 `ccx_i8.exe` |
| `*ERROR ... plane stress ... z=0` | gmsh 把 `CPS6` 面单元写进了 `.inp` | 只给体建 Physical Group + `Mesh.SaveAll=0` |
| `*ERROR ... nonpositive jacobian` | 手工拼接 C3D10 连接表顺序错 | 用 gmsh 自带 Abaqus 写出器 |
| `*ERROR in linstatic` | 约束不足（刚体位移） | 检查 FIXED 面是否真的选中；补约束 |
| 结果全 0 | 载荷方向/单位错 | 检查 `load_direction` 与 `load_total_N`；确认 mm-N-MPa |
| `TypeError: complex` | `ccx2paraview` 与 numpy≥2 不兼容 | 用 `frd_reader.py`，或把 numpy 钉到 <2 |
| `DLL load failed` | conda/pip 混装 OCP | 重建 venv，只用一个包管理器 |
| PNG 全黑/失败 | 无 GL 上下文（Session 0/RDP） | 在交互会话重跑；或改用 matplotlib 出曲线 |
| 中文乱码 / `.ps1` 语法错 | 控制台 CP936 / 脚本无 BOM 被按 ANSI 读 | 设 `PYTHONUTF8=1`；`.ps1` 正文用英文或存成 UTF-8 BOM |
| FreeCAD 初始化 `Access is denied` | 安装目录带 Deny ACE（本工作区就有） | 装到 `C:\FreeCAD\1.1.4` 这类干净目录 |
| `FreeCADCmd ... --job` 打印帮助 | FreeCADCmd 自己解析命令行，拒绝未知参数 | 用 `$env:CAE_JOB` + `-c "exec(open(...).read())"` |
| 跑 `freecad_xxx.py` 无任何输出 | 位置参数 `.py` 被当作模块 import，与 FreeCAD 子模块冲突 | 改名 `fc_xxx.py`，或改用 `-c exec(...)` |
| FreeCAD 脚本抛异常但退出码 0 | FreeCADCmd 不映射异常到退出码 | 脚本内 `try/except` + `sys.exit(9)`，外部查产物 |
| TechDraw DXF 没有标题栏/尺寸 | `writeDXFPage` 只写几何 | 用 `annotate_dxf.py`（ezdxf）补图框/标题栏/尺寸，再转 PDF |

## 5. 扩展点

- **参数扫描**：用 DSH `workflow` 脚本 fan-out 多个 `job-XXXX` 目录，每个跑 §1 的 5 步，最后汇总 `result.json` 成 CSV。
- **多物理场**：把第 3–4 步换成 `ElmerGrid.exe 14 2 part.msh -autoclean` + `ElmerSolver.exe case.sif`。
- **CFD**：几何仍由第 1 步出 STL/STEP，之后转 blueCFD（`snappyHexMesh`）或 SU2（`.su2`/CGNS）。
- **交互式查看**：需要人看模型时，再启动 FreeCAD GUI + `freecad-mcp`；无人值守不要用。
- **正式工程图**：`-WithFreeCAD` 出 `model.FCStd` + `drawing.dxf`（纯几何）→ `annotate_dxf.py` 补标题栏/尺寸 → `drawing.pdf`。
  仍缺 GD&T、剖视、局部放大；需要这些时由人开 FreeCAD GUI 完成，不要让 Agent 假装能全自动。

## 6. 验收清单（每次任务结束前逐条确认）

- [ ] `part.step` 存在且 `is_valid`
- [ ] `part.inp` 里只有 `C3D4/C3D10`，没有 `CPS6`
- [ ] `job.dat` 无 `*ERROR`
- [ ] `job.sta` 最后一行显示增量完成
- [ ] `result.json` 的 `max_vm_stress_MPa`、`max_disp_mm` 为有限值且在合理量级
- [ ] `stress.png` / `stress_side.png` 存在，且不是纯色（用 `read_image` 目视检查）
- [ ] **线性自检**：载荷 ×1.6 后位移/应力也应 ×1.6（线弹性），偏差 >1% 说明有非线性或未收敛
- [ ] 运行目录里记录了版本：`ccx_i8 -v`、`gmsh --version`、`build123d.__version__`
- [ ] 若跑了 `-WithFreeCAD`：`freecad/report.json` 的 `volume_mm3` 与 `model.json` 一致；`drawing.pdf` 打开后图框、标题栏、尺寸齐全

## 热分析（温度场）要点

- **单位制必须用 SI**（m, N, Pa, kg, s, K）。用 mm-N-MPa 时 `*CONDUCTIVITY` 是 N/(s·K)、
  `*SPECIFIC HEAT` 是 mm²/(s²·K)，极易错 10³–10⁶ 倍。
- **`*FILM` 数据行顺序是 `单元/集合, 面号, 沉温, 换热系数`**，不是 (h, T_sink)。
  写反的典型现象：整场温度≈沉温值、与 h 无关（实测 94.7 °C vs 正确 453 °C）。
- 面号与 `*DLOAD` 相同（C3D4：F1=1-2-3, F2=1-2-4, F3=2-3-4, F4=1-3-4）。
  用"三个节点半径都等于 r_i/r_o"来挑内/外面，比按面号猜更可靠。
- 钢管/薄壁件的**轴向导热不可忽略**：肋片参数 m = sqrt((h_oP_o+h_iP_i)/(λA_c))，
  mL ≫ 1 时壁面近似等温。用"逐段独立 1D 径向"做校验会得到 1–2% 的假误差。
- 首轮必须先用**均匀边界 + 解析解**标定求解器（本工具链实测 0.001%），再上复杂工况。

## 电磁场（永磁电机）要点

- 工具链**原生没有电磁求解器**；已补 `afpm_model.py`（2D 磁标量势，周期边界，磁钢以
  `mu0*M·grad(N)` 进右端），只适用于能闭合磁通回路的切片。
- **周期边界要代列，不能只置零行**：只改行会让矩阵奇异，实测解出 1e74 的无意义值。
  正确做法：`K[:, left] += K[:, right]`，再零化右列与右行、对角置 1。
- **单定子 AFPM 不能用切向-轴向 2D 切片**：回流路径是沿背铁径向，切片里被压掉，
  气隙磁密会偏高 ~25%。这类拓扑必须 3D（或 FEMM 轴对称 + 端部修正）。
- 磁路是可靠的定量底座：`Bg = Br / (1 + g_eff/h_m)`，`Kt = 1.5*p*Nph*Bg*Ap`。
  先与实测 Kt 对表，再决定要不要上 3D。
- 论文常缺磁钢厚度/Br/匝数换算；**先用实测 Kt 反推所需匝数或磁通**，能立刻暴露参数不自洽。
