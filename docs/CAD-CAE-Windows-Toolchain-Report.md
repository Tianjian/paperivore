# Windows 上基于 DeepSeek Harness 的开源 CAD / CAE 机械设计工具链研究报告

> 版本：v1.2 ｜ 调研日期：2026-11-01 ｜ 修订：2026-11-13（后处理节点/单元语义修正）｜ 环境：Windows 11 x64，DeepSeek Harness (dsh) desktop profile
> 本版本包含**本机实测**的端到端流水线（build123d → gmsh → CalculiX ccx_i8 → PyVista），不是纸面调研。
> 目标：在 Windows 本机搭建**全开源**、**Agent 友好**（可被 LLM 以文件 + CLI 方式可靠驱动）的机械 CAD / CAE 工具链
> 结论先行：**可以完整搭建，而且不需要任何商业软件。** 唯一必须接受的取舍是"用代码建模（CAD-as-Code）而不是点鼠标建模"。

> **平台说明（2026-11）**：本报告记录最初的 Windows 11 基线；Python 核心（以及
> GetDP / CalculiX 案例）也可在 Ubuntu 上运行，CI 会在 Windows 与 Ubuntu 上跑纯 Python 基准。

---

## 0. 一页结论

### 0.1 三条可行工具链（按推荐度排序）

| 方案 | CAD 层 | 网格/求解层 | 后处理层 | 适用场景 | Agent 友好度 |
|---|---|---|---|---|---|
| **A. 极简闭环（首选）** | `build123d` 0.13.0（pip，OCCT 8.0） | `gmsh` 4.15.2（pip）+ `CalculiX ccx_i8` 2.23（MSYS2） | 内置 FRD 读取 + `PyVista`（离屏 PNG） | 零件级静力/模态/热分析、参数扫描、批量出图 | ★★★★★ |
| **B. 多物理场** | `build123d` / `FreeCAD 1.1.4` | `gmsh` + `Elmer FEM` 26.2.1（MSYS2） | `PyVista` / `ParaView pvbatch` | 热-结构耦合、电磁、流体-热 | ★★★★☆ |
| **C. CFD 专项** | `build123d`（出 STL/STEP） | `blueCFD-Core 2024-1`（OpenFOAM 12 原生 Windows）或 `SU2 8.6.0` | `foamToVTK` + `ParaView 6.2` | 外流场、管道、换热器 | ★★★☆☆ |

### 0.2 三条硬结论

1. **CAD 层选 `build123d`，不要一上来就搞 FreeCAD GUI 自动化。** build123d 是纯 pip 包、无 GUI、无 VTK、单文件脚本直接输出 STEP；FreeCAD 适合作为"重资产节点"（工程图、装配、FEM 工作台、.FCStd 参数历史），用 `FreeCADCmd.exe` 跑脚本，绝不要用 GUI 点击自动化。
2. **CAE 层在 Windows 上真正"原生可用"的组合是 `gmsh + CalculiX ccx_i8 + PyVista`。** 三者在 MSYS2 ucrt64 / PyPI 都有当前版本（ccx 2.23 / gmsh 4.15.2 / paraview 6.1.1 / vtk 9.6.2 / opencascade 7.9.3），全部是普通 `.exe` 或 wheel，可由 PowerShell 直接调用。**注意：必须用 `ccx_i8.exe`，`ccx.exe` 在本机 PaStiX 分解阶段会 access violation（见 §4.2）。**
3. **`Code_Aster`、FEniCSx/dolfinx、SALOME-SMESH 在 Windows 上不是可行选项**（官方不发 Windows 构建或只在 WSL/Linux 可用）；`CGX` 是交互式 OpenGL 程序，不适合 Agent 循环，用 `ccx2paraview + PyVista` 或本报告自带的最小 FRD 读取器替代。

### 0.3 本机已验证（而非纸面推断）

| 验证项 | 结果 |
|---|---|
| Python | 3.13.9（Microsoft Store 版；首轮曾误判其缺 `venv`，复测证明 venv/ensurepip 正常，见 §7.1） |
| `pip install build123d` | ✅ 成功，build123d **0.13.0**（本项目 venv） |
| `build123d` 建模 + 导出 | ✅ `Box(80,40,12)` + 2 mm 圆角：`is_valid=True`、体积 38358.796 mm³、STEP 31,743 B |
| `gmsh` 4.15.2 网格 | ✅ 35,510 节点 / 22,333 个 C3D10 单元，固定面 173 节点、加载面 3,085 节点 |
| `CalculiX ccx_i8` 2.23 求解 | ✅ 13.2 s 完成，`*ERROR` 0 条，`job.sta` 显示 1 步 1 增量收敛 |
| 结果 | ✅ 最大位移 **0.070832 mm**，最大 von Mises **51.60 MPa**（节点外插峰值；500 N 作用于 80×40×12 梁的自由端面（max-X 面），固定端为 min-X 面；同一复现网格的单元平均峰值 40.38 MPa） |
| 线性自检 | ✅ 同一套网格把载荷改到 800 N：位移 0.113330 mm、应力 82.56 MPa，**位移与逐节点应力张量比值均为 1.6000** |
| 出图 | ✅ `stress.png`（等轴测）+ `stress_side.png`（侧视，可见固定端应力集中） |
| `winget` 可用包 | FreeCAD **1.1.4**、OpenSCAD **2021.01**/Nightly、ParaView **6.2.0**（含 MPI 版）、Gmsh **4.13.1**、Blender 5.2.3、MSYS2 **20260927** |
| MSYS2 仓库实测存在 | `calculix-ccx 2.23-1`、`gmsh 4.15.2-2`、`elmerfem 26.2.1-5`、`paraview 6.1.1-4`、`opencascade 7.9.3-3`、`freecad 1.1.4-1`、`vtk 9.6.2-8`、`openscad 2021.01-25` |
| DSH 集成能力 | ✅ 内置 **MCP 客户端**（stdio / http / sse 三种传输）、Skill 机制、subagent / workflow 编排、后台作业、文件策略（`danger-full-access`） |
| FreeCAD 1.1.4 | ✅ 已部署到 `C:\FreeCAD\1.1.4`（便携版 + SHA256 校验）；`FreeCADCmd` 建模/STEP/`.FCStd`/**TechDraw DXF** 无头可用，PDF/SVG 不可用 |

> 可复现实物：`results/box-cantilever-500N/`（`params.json` → `part.step` → `part.inp` → `job.inp` → `job.frd` → `job.vtu` → `stress.png` / `result.json`），脚本在 `skills/cad-cae/scripts/`。
> 运行环境：便携版 MSYS2 解压在 `msys/msys64`（`pacman` 装的 ccx），无需管理员权限、不改系统 PATH。

> **Post-fix 说明（2026-11-13 复现后修订）**：`frd_reader.py` 的节点/单元语义已修正——CalculiX 的 FRD `STRESS` 块是**节点结果**（每个节点一条，由单元积分点外插并在共享节点间平均），旧实现把它按**单元 id** 索引造成静默错位。现行版本：`point_data["S"]/["S_vm"]` = FRD 原生节点值（峰值即**节点外插峰值**），`cell_data["S"]/["S_vm"]` = 单元连接上的节点平均（派生量，供云图）；`result.json` 的 `max_vm_stress_note` 已更新为 "nodal extrapolated peak from raw FRD (values averaged over elements at nodes)"，后处理另提供 `max_vm_stress_element_avg_MPa`（单元平均峰值）。因此同一组结果现在有两个口径：
> - **51.60 MPa = 节点外插峰值**（`max_vm_stress_MPa`，artifact 保留的口径）；
> - **40.38 MPa = 同一复现网格的单元平均峰值**（`max_vm_stress_element_avg_MPa`）。
>
> 该峰值随网格加密单调上升、**不收敛**（h=6/4/3 mm → 44.5/49.6/51.0 MPa），只能在"网格带内可复现"，不能作为收敛判据。旧文中的"节点平均后 36.83 MPa"无法用节点平均复现（那是旧管线渲染表面平滑的产物，无物理意义），已删除。


---

## 1. 调研范围与方法

### 1.1 什么叫"Agent 友好"

本报告用 7 条可检验的标准打分（1–5），而不是看软件是否"有名"：

| # | 标准 | 为什么对 LLM Agent 重要 |
|---|---|---|
| C1 | **非交互安装**（winget / pip / pacman / 解压即用） | Agent 无法点"下一步" |
| C2 | **单一确定性 CLI + 退出码** | 便于 `pwsh` 调用、重试、超时控制 |
| C3 | **文本输入可生成/可 diff**（.py / .scad / .geo / .inp / .sif / .cfg） | LLM 的本职工作就是写文本；二进制/状态化输入不可控 |
| C4 | **文件进、文件出**（无 socket、无 GUI 会话、无许可证守护） | 天然幂等、可并行、可缓存 |
| C5 | **无强制 GUI 窗口** | 无人值守/后台作业的前提 |
| C6 | **诊断信息稳定可解析**（错误码、日志格式） | 让 Agent 能自我纠错而不是瞎猜 |
| C7 | **生态互操作**（STEP / STL / VTK / MSH 标准格式） | 工具链可替换、可分阶段验证 |

### 1.2 方法

- 一手元数据核对：PyPI JSON API、MSYS2 包数据库、winget 清单（`winget show`）、GitHub Releases API。
- 本机实测：Python/pip/venv、build123d 安装与建模导出、winget 包清单、MSYS2 包存在性。
- 对不可达资源（GitHub raw 在本网络超时）改用镜像/元数据接口交叉验证，任何"未实测"的结论都在正文标注 ⚠。

---

## 2. 总体架构：五段式流水线

```
┌─────────────┐   STEP/STL   ┌──────────────┐   .msh/.inp   ┌──────────────┐   .frd/.vtu   ┌──────────────┐
│  CAD 建模    │ ───────────▶ │  几何清理/网格 │ ────────────▶ │   求解器      │ ────────────▶ │  后处理/出图  │
│ build123d   │              │  gmsh        │               │ CalculiX ccx │               │ ccx2paraview │
│ FreeCAD     │ ◀─────────── │  (OCC import)│ ◀──────────── │ Elmer/SU2    │ ◀──────────── │ PyVista      │
│ OpenSCAD    │   .step 回写  │              │   .geo 参数    │ blueCFD      │   .vtk/.png   │ ParaView     │
└─────────────┘              └──────────────┘               └──────────────┘               └──────────────┘
       ▲                                                                                          │
       └────────────────────────── 参数 JSON / 结果 JSON / 图像 ──────────────────────────────────┘
                              （Agent 只读写这些"契约文件"）
```

**核心设计原则（比选型更重要）：**

1. **以 STEP 为唯一几何契约**（AP214/AP242）。STL/3MF 只作为网格化/3D 打印的终端产物，绝不作为中间格式回传。
2. **每一段都是"纯文件变换"**：输入文件 + 参数 → 输出文件 + 日志。这样 Agent 可以任意重跑某一段而不污染上游。
3. **参数外置为 JSON**，脚本只做"读参数 → 建模/网格/求解 → 写结果"的薄封装。LLM 改 JSON 比改 Python 更不容易引入语法错误。
4. **成功判据不只看退出码**：CalculiX 出错时可能返回 0，FreeCAD 的 REPL 永远返回 0。必须同时校验产物存在性 + 数值合理性（体积、最大应力、网格质量）。

---

## 3. CAD 层选型（几何建模）

### 3.1 对比矩阵

| 工具 | 版本（核实） | 许可证 | Windows 安装方式 | 无头/CLI | 输出 STEP | Agent 友好度 | 一句话定位 |
|---|---|---|---|---|---|---|---|
| **build123d** | 0.13.0 | Apache-2.0 | `pip install build123d`（Py ≥3.11,<3.15） | ✅ 纯库 | ✅ | **5/5** | 默认建模层：Pythonic、选择器语义清晰、无 VTK |
| **FreeCAD** | 1.1.4 | LGPL-2.1+ | `winget install FreeCAD.FreeCAD` / MSYS2 | ✅ `FreeCADCmd.exe` | ✅ | 3/5 | 重资产节点：PartDesign / TechDraw / FEM / .FCStd |
| **CadQuery** | 2.8.0 | Apache-2.0 | `pip install cadquery`（Py 3.11–3.13） | ✅ 纯库 | ✅ | 4/5 | 成熟稳定、有装配约束求解器；但依赖 `vtk==9.5.2`，体积大 |
| **OpenSCAD** | 2021.01（stable）/ Nightly | GPL-2.0+ | `winget install OpenSCAD.OpenSCAD` | ✅ `-o` | ❌ | 3.5/5 | 文本 DSL 最"Agent 原生"，但只有网格、无倒角、无 STEP |
| **pythonocc-core** | 8.0.1.2（conda-forge） | LGPL-3.0+ | **仅 conda/mamba** | ✅ | ✅ | 2/5 | OCCT 底层逃生舱，不要当建模层 |
| **SolveSpace** | 3.3 | GPL-3.0 | Windows 安装包**只有 GUI** | ⚠ 无官方 CLI | ✅ | 2/5 | 约束求解器优秀，但 Windows 无 CLI 发布 |
| **SALOME** | 9.16.0 | LGPL-2.1+ | 官方有 Win10/11 二进制 | GUI 优先 | ✅ | 1.5/5 | 平台级软件，不适合当 CLI 节点 |
| **Blender + CAD Sketcher** | 5.2.3 | GPL-3.0 | winget | ✅ `blender -b -P` | ❌ | 2/5 | 只适合可视化/动画尾巴 |

### 3.2 build123d（推荐默认建模层）

**为什么是它：**

- 纯 pip，**不依赖 VTK**（`cadquery-ocp-novtk`），安装体积约 200–300 MB，而不是 CadQuery 的 ~2 GB。
- 支持 Python 3.11–3.14，本机 3.13.9 实测通过。
- 语义化选择器（`edges().filter_by(Axis.Z)`）对 LLM 非常友好：意图即代码，不需要记拓扑索引。
- 一行导出：`export_step(part, "a.step")` / `export_stl(...)`。

**最小可用脚本（已验证）：**

```python
# model.py —— Agent 只需要生成/修改这个文件
import time, os
from build123d import Box, fillet, Axis, export_step, export_stl

t0 = time.time()
part = fillet(Box(40, 20, 10).edges().filter_by(Axis.Z), radius=2)
assert part.is_valid, "几何无效"
print("volume_mm3", round(part.volume, 3))

out = r"C:\cae\out"
os.makedirs(out, exist_ok=True)
export_step(part, os.path.join(out, "part.step"))
export_stl(part, os.path.join(out, "part.stl"), tolerance=0.05, angular_tolerance=0.2)
print("elapsed_s", round(time.time() - t0, 2))
```

实测输出：

```
valid True volume 7965.664 bbox Vector: (X=40, Y=20, Z=10)
box.step True 31719
box.stl True 13484
elapsed_s 0.05
```

**限制（必须知道）：**

- 没有装配约束求解器。装配是 `Compound` 树 + `Location`/`Pos` 手工定位，或 `Joints` 声明式连接。复杂装配的配合关系需要自己写数学。
- 没有参数化历史：**Python 文件本身就是参数化源**。修改 = 改代码重跑，而不是改一个尺寸。
- 没有工程图（TechDraw 那类）。2D 只能导 DXF/SVG，尺寸标注要自己在 DXF 里加或交给 FreeCAD。
- OCCT 8.0 与 FreeCAD 1.1.x 的 OCCT 7.9 存在版本差，STEP 跨工具往返后务必在目标端做 `is_valid` 校验。

### 3.3 FreeCAD 1.1.4（已部署；定位：投影器 + 审图台）

> **2026-11-01 实测更新**：FreeCAD 已成功部署到 `C:\FreeCAD\1.1.4`（便携版，SHA256 校验通过），
> 完整的能力边界与"为什么它不是必需项"见 `docs/FreeCAD-necessity-and-deployment-postmortem.md`。
> 这里只保留工具链视角的结论。

**定位：** 不是"主建模器"，而是三件事的执行者——(a) `.FCStd` 参数化历史与装配、(b) **TechDraw 投影视图（几何 DXF）**、(c) 读取各种奇异格式做格式转换。
**FEM 不推荐走 FreeCAD**：本工具链已直接驱动同一个 CalculiX，多一层前端只增加状态与故障面。

**正确用法：生成 `.py` 或 `.FCMacro`，用 `FreeCADCmd.exe` 执行。**

```powershell
$fc = "C:\FreeCAD\1.1.4\FreeCADCmd.exe"
& $fc --version                                  # FreeCAD 1.1.4 Revision 20260928

# 单行代码
& $fc -c "import Part; print(Part.makeBox(10,10,10).Volume)"

# 脚本（注意：位置参数 .py 会先按模块 import；别用 freecad_*.py 命名）
& $fc C:\work\fc_build.py

# 推荐：用 -c exec(...) + 环境变量传参，绕开 FreeCADCmd 自己的 argv 解析
$env:CAE_JOB = "C:\cae\jobs\job-0001"
& $fc -c "exec(open(r'C:\work\fc_drawing_export.py', encoding='utf-8').read())"
```

**无头能力边界（1.1.4 实测，别假设更多）：**

| 能力 | 无头可用 | 实测结论 |
|---|---|---|
| Part 建模 / STEP 导入导出 / `.FCStd` 保存 | ✅ | `Part.makeBox(40,20,10)` + 2 mm 圆角 → 体积 7770.36 mm³、26 面 |
| STEP 导入一致性 | ✅ | 读 build123d 的 `part.step` → 38358.796 mm³，与 build123d 完全一致 |
| `TechDraw.writeDXFPage` | ✅ | A4、1:1、Front+Top；100×50×10 的盒 → 100×10 矩形正确；**只有几何线框** |
| `TechDraw.writeSVG` / `writePDF` | ❌ | `dir(TechDraw)` 里没有这两个符号；`DrawPage` 也没有 `getSVGFile` |
| 标题栏字段 | ⚠ | `setEditFieldContent` 可调用，但**不写进 DXF** |
| 退出码 | ⚠ | 未捕获异常仍返回 **0**；`sys.exit(3)` 才返回 3 |

**2D 工程图的完整自动链路（本工程已实现）：**

```
part.step --FreeCADCmd/TechDraw--> drawing.dxf（纯几何）
        --annotate_dxf.py (ezdxf)--> drawing_annotated.dxf（图框/标题栏/总长总高）
        --matplotlib--> drawing.pdf（A4 横放，中文 SimHei）
```

**必须知道的坑：**

| 坑 | 现象 | 对策 |
|---|---|---|
| 用错可执行文件 | `FreeCAD.exe` 是 GUI 子系统，stdout 不接管管道 | **永远用 `FreeCADCmd.exe`** |
| 退出码不可信 | 脚本异常仍返回 0；没有 `--python-exit-code` | 脚本内 `try/except` + `sys.exit(9)`，外部校验产物 |
| `--job` 被吃掉 | FreeCADCmd 打印帮助并退出 | 用 `$env:CAE_JOB` + `-c "exec(open(...).read())"` |
| `freecad_*.py` 静默不执行 | 位置参数 `.py` 被当模块 import，与 FreeCAD 子模块冲突 | 改名 `fc_*.py`，或统一用 `-c exec(...)` |
| 安装目录带 Deny ACE | `Could not create directories ... Access is denied` | 装到 `C:\FreeCAD\1.1.4` 这类干净目录（本工作区 ACL 有 `Everyone: Deny`） |
| TechDraw 不出 PDF/SVG | 无头 API 不存在 | `annotate_dxf.py` 用 ezdxf + matplotlib 生成 PDF |
| 并行任务抢 `user.cfg` | `%APPDATA%\FreeCAD\user.cfg` 被写坏 | 每任务设 `FREECAD_USER_HOME`，或 `-u/-s`，加 `--safe-mode` |

**GUI 自动化的现实：** `freecad-mcp`（MIT，0.1.28）需要一个"人先启动 FreeCAD GUI + 点 Start RPC Server"的会话，适合"人在旁边看着的副驾驶"，**不适合 CI/无人值守**。全自动场景请走 `FreeCADCmd`。

### 3.4 CadQuery 2.8.0 vs build123d 0.13.0 的兼容性陷阱

两者都基于 OCCT，但**依赖的 OCP 发行版不同**：

| | CadQuery 2.8.0 | build123d 0.13.0 |
|---|---|---|
| OCP 依赖 | `cadquery-ocp >=7.9.3.1,<8.0` | `cadquery-ocp-novtk >=8.0,<8.1` |
| Windows wheel | cp310–cp313 | cp311–cp314 |
| VTK | 硬钉 `vtk==9.5.2` | 无 VTK |
| 安装体积 | ~2 GB | ~200–300 MB |
| 装配 | 有约束求解器（nlopt） | 无求解器，手工定位 |

**两者会安装同名 `OCP` 模块，绝不能装进同一个环境。** 需要同时用时，建两个 venv，通过 STEP 文件通信。

### 3.5 OpenSCAD：最"文本原生"，但只到网格为止

```powershell
winget install --id OpenSCAD.OpenSCAD -e
& "C:\Program Files\OpenSCAD\openscad.exe" -o out.stl -D "w=20" -D "wall=2" part.scad
```

- 优点：单文件 DSL、`-D` 直接参数化、无 import、报错带行号、`--summary-file -` 输出 JSON 统计。
- 硬限制：**不能读写 STEP/IGES/BREP**，没有真正的倒角/圆角（只能 Minkowski/hull 近似），复杂 CSG 很慢。
- winget 装到的是 **2021.01**（5 年前），没有 Manifold 后端、没有 `--backend` 参数。要用 Manifold 加速必须手动装 Nightly，并接受每周变化的不稳定性。
- 结论：**只在"纯参数化图元 + 3D 打印"场景用**，不要放进 STEP 主流水线。

---

## 4. CAE 层选型（网格 → 求解 → 后处理）

### 4.1 对比矩阵

| 工具 | 版本（核实） | 许可证 | Windows 安装 | CLI 入口 | 无头 | Agent 友好度 | 备注 |
|---|---|---|---|---|---|---|---|
| **Gmsh** | 4.15.2 | GPL-2.0+ | `pip install gmsh`（win_amd64）或 MSYS2 | `gmsh.exe` / `import gmsh` | ✅ | **5/5** | 网格层唯一首选；OCC 读 STEP；Physical Group 是 BC 契约 |
| **CalculiX ccx** | 2.23-1 | GPL-2.0+ | MSYS2 `pacman -S mingw-w64-ucrt-x86_64-calculix-ccx` | `ccx_i8.exe -i job` | ✅ | 4/5 | 静力/模态/屈曲/接触/热；**无 MPI**，仅 OpenMP |
| **Elmer FEM** | 26.2.1-5 | GPL-2.0+ | MSYS2 `elmerfem` | `ElmerGrid` + `ElmerSolver` | ✅ | 3.5/5 | 多物理场强；SIF 文本冗长，LLM 写起来 token 成本高 |
| **NGSolve/Netgen** | 6.2.2608 | LGPL-2.1 | `pip install ngsolve`（cp310–cp314 win） | `import ngsolve` | ✅ | 4.5/5 | 全 Python、无文件往返；适合自定义 PDE |
| **ParaView** | 6.2.0（winget）/ 6.1.1（MSYS2） | BSD-3 | winget 或 MSYS2 | `pvpython` / `pvbatch` | ⚠ 需 GL | 4/5 | 批量出图/动画；Windows 无 OSMesa 软件渲染 |
| **PyVista / VTK** | 0.49.x / 9.6.2 | MIT / BSD-3 | `pip install pyvista` | `python render.py` | ✅（WGL） | **5/5** | 首选后处理：离屏截图、探针、切片 |
| **ccx2paraview** | 3.2.0 | MIT | `pip install ccx2paraview` | `ccx2paraview job.frd vtk` | ✅ | 3/5 | 补 meshio 不支持 FRD 的缺口；**numpy≥2 下会崩**（见 §7.2），本报告改用自带 `frd_reader.py` |
| **meshio** | 5.3.5 | MIT | `pip install meshio` | `meshio convert` | ✅ | 5/5 | 40+ 格式互转；**读不了 `.frd`** |
| **OpenFOAM (blueCFD)** | 2024-1 / OF12 | GPL-3.0 | 官方安装包（1.2 GB） | `setvars.bat` + `simpleFoam` | ✅ | 2.5/5 | Windows 唯一原生 OpenFOAM；**路径不能有空格** |
| **SU2** | 8.6.0 | LGPL-2.1 | 解压 zip + 设 `SU2_RUN` | `SU2_CFD config.cfg` | ✅ | 4/5 | 可压流/优化；网格需 .su2/CGNS |
| **OpenTURNS** | 1.27 | LGPL-3.0 | `pip install openturns` 或 MSYS2 | Python API | ✅ | 4.5/5 | 不确定性量化/DOE/可靠性 |
| **Code_Aster** | 17.x | GPL-2.0 | ❌ **无 Windows 版** | `as_run`（Linux） | — | 1.5/5 | 只能 WSL2/容器 |
| **FEniCSx / dolfinx** | 0.9/0.10 | LGPL-3.0 | ❌ 无 win-64 | — | — | 1.5/5 | 只能 WSL2/Docker |
| **CGX** | 2.23 | GPL-2.0 | ❌ 无现行 Windows 构建 | `cgx -b`（仍需 GL） | ❌ | 1/5 | 交互式 OpenGL，Agent 死路 |
| **SALOME/SMESH** | 9.16 | LGPL-2.1 | ⚠ 有 Windows 平台包但 GUI 优先 | `salome -t` | ⚠ | 1.5/5 | 当平台用，不当 CLI 用 |

### 4.2 推荐求解器：CalculiX ccx（用 `ccx_i8.exe`）

**为什么选它：** 单文件 `.inp` 输入、`.dat/.frd/.sta` 输出、纯 CLI、GPL 免费、Windows 有 MSYS2 现行版本、OpenMP 多线程、覆盖静力/模态/屈曲/接触/热-结构。

**安装（无需管理员；MSYS2 可用 winget 装，也可解压便携版）：**

```powershell
winget install --id MSYS2.MSYS2 -e --accept-package-agreements --accept-source-agreements
C:\msys64\usr\bin\pacman.exe -S --needed --noconfirm `
  mingw-w64-ucrt-x86_64-gmsh `
  mingw-w64-ucrt-x86_64-calculix-ccx `
  mingw-w64-ucrt-x86_64-elmerfem `
  mingw-w64-ucrt-x86_64-paraview `
  mingw-w64-ucrt-x86_64-opencascade
```

> 国内网络如果 winget 拉 MSYS2 卡住：直接下载 `msys2-x86_64-latest.tar.xz`（清华镜像，约 43 MB）解压，再跑 `pacman -Sy` + 上面的 `pacman -S`。本报告就是这样装成的，全程不需要管理员权限、不写系统目录。

**运行（实测必须用 `ccx_i8.exe`）：**

```powershell
$env:OMP_NUM_THREADS = "8"
$env:CCX_NPROC_STIFFNESS = "8"
ccx_i8.exe -i job     # 读 job.inp，写 job.dat / job.frd / job.sta / job.cvg
```

**⚠ 关键实测发现：MSYS2 的 `ccx.exe` 2.23 在 PaStiX 矩阵分解阶段会崩溃**（Windows 退出码 `-1073741819` = `0xC0000005` access violation），即使是一个 6 单元的小模型也一样；同包的 **`ccx_i8.exe`（64 位整数版）同一模型 13.2 s 正常收敛**。原因大概率是 PaStiX 的 32 位索引封装在 Windows 上的缺陷，不是模型问题。**流水线里默认调用 `ccx_i8.exe`**，`run_job.ps1` 已按此实现并带回退。

**关键工程实践：** 不要试图用某个 Python 库"生成" CalculiX 模型（`pycalculix` 已多年不维护）。正确做法是**模板化 deck**：网格段来自 Gmsh 的 Abaqus 写出器，再用 `string.Template` 追加材料、分析步、边界条件、载荷、输出请求。文本可 diff、可审查、零依赖。

**成功判据（重要）：** CalculiX 的错误以 `.dat` 里的 `*ERROR` 行出现，退出码不一定可靠。Agent 必须解析 `.dat`/`.sta`，并检查 `.frd` 是否生成、数值是否有限。

### 4.3 多物理场：Elmer

```powershell
ElmerGrid.exe 14 2 part.msh -autoclean   # 14 = Gmsh 输入, 2 = Elmer 目录输出
ElmerSolver.exe case.sif                 # SIF 纯文本，输出 .vtu/.ep
```

- 优点：热-结构、电磁、流体-热耦合能力远超 ccx；SIF 是纯文本。
- 缺点：SIF 段落冗长且内部一致性要求高（材料/求解器/边界段必须对得上），LLM 生成时 token 成本高、易错。建议先做一个可用模板，只让 Agent 改参数块。

### 4.4 后处理：自带 FRD 读取器 + PyVista

`ccx2paraview` 3.2.0 在 **numpy ≥ 2** 下会抛 `TypeError: '<' not supported between instances of 'complex' and 'complex'`（`calculate_principal()` 直接排序复数特征值）。本报告因此带了一个 60 行的 `skills/cad-cae/scripts/frd_reader.py`：

- 从 `job.frd` 的 `100CL` 结果块里读 `DISP` / `STRESS`（12 字符定宽解析，处理"数值之间无空格"的 `5-5.05751E-04`）；**FRD 的 `STRESS` 是节点结果（每个节点一条，由单元积分点外插并在共享节点间平均）**；
- 用 `part.inp` 的 `C3D4/C3D10` 拓扑建 `pyvista.UnstructuredGrid`；
- `point_data["S"]/["S_vm"]` 放 FRD 原生节点值（真实场），`cell_data["S"]/["S_vm"]` 放单元连接上的节点平均（派生量、供云图）；`python frd_reader.py --job <dir>` 已是有用的 CLI，会写 `job.vtu` + `frd.json` + `result.json`。

```python
# render.py 的核心（已在 Windows 实测出图）
import pyvista as pv
pv.OFF_SCREEN = True
mesh = pv.read("job.vtu")
p = pv.Plotter(off_screen=True)
p.add_mesh(mesh, scalars="S_vm", cmap="turbo", show_edges=False,
           scalar_bar_args={"title": "S_vm [MPa]"})
p.view_isometric()          # 另存一张 camera_position="xz" 的侧视图
p.screenshot("stress.png")
```

**Windows 特有约束：**

- 没有 OSMesa/EGL 软件渲染后端，VTK 走 WGL，**必须有一个真实 GL 上下文**。
- 在 Session 0 / Windows 服务 / 无 GPU 的 RDP 会话中，`OFF_SCREEN=True` 会失败（`pvbatch --force-offscreen-rendering` 同理）。
- 对策：把出图放在**交互式用户会话**里跑；或把渲染卸载到 Linux 容器；或退化为"数值探针 + matplotlib 曲线图"（纯 CPU，永远可用）。

---

## 5. 三条工具链蓝图（可直接照做）

### 5.1 方案 A：极简闭环（静力分析，一天可落地）

**目录结构：**

```
C:\cae\
├── venv\                      # Python 3.12 venv（build123d + gmsh + pyvista + ccx2paraview）
├── bin\                       # 可选：软链/复制 ccx.exe 等
├── jobs\
│   └── bracket-001\
│       ├── params.json        # Agent 只改这个
│       ├── model.py           # 生成 STEP
│       ├── mesh.py            # STEP -> .inp（含 Physical Group）
│       ├── deck.py            # 模板化 .inp -> job.inp
│       ├── render.py          # .frd -> .vtk -> PNG
│       ├── part.step
│       ├── job.inp / job.dat / job.frd / job.sta
│       ├── stress.png
│       └── result.json        # 汇总：最大位移、最大应力、是否收敛
└── out\
```

**执行链（5 条命令，全部可重试、幂等）：**

```powershell
$env:PYTHONUTF8 = "1"
$py = "C:\cae\venv\Scripts\python.exe"
$env:PATH = "C:\msys64\ucrt64\bin;" + $env:PATH

& $py C:\cae\jobs\bracket-001\model.py --job $Job
& $py C:\cae\jobs\bracket-001\mesh.py  --job $Job
& $py C:\cae\jobs\bracket-001\deck.py  --job $Job
ccx_i8.exe -i job                      # cwd = $Job
& $py C:\cae\jobs\bracket-001\render.py --job $Job
```

一键版：`skills/cad-cae/scripts/run_job.ps1 -Job C:\cae\jobs\bracket-001`

**为什么这条链对 Agent 最友好：** 每一步只有一个输入、一个输出、一个退出码；任何一步失败都可以单独重跑；`params.json` 是唯一的"意图载体"，LLM 不需要理解 OCCT 或有限元理论，只需要会填参数。

### 5.2 方案 B：多物理场（热-结构耦合）

在方案 A 基础上，把 `ccx` 换成 `ElmerGrid + ElmerSolver`，网格仍由 Gmsh 生成：

```powershell
gmsh.exe -3 part.step -o part.msh -format msh2 -nt 8
ElmerGrid.exe 14 2 part.msh -autoclean
ElmerSolver.exe case.sif
```

适用：电机/电子散热、热变形、电磁-热。**不要**用它做纯静力——SIF 的编写成本高于 `.inp`。

### 5.3 方案 C：CFD 专项

**C1. blueCFD-Core（OpenFOAM 12 原生 Windows）**

```powershell
# 安装到无空格路径！例如 C:\blueCFD-Core\2024\
C:\blueCFD-Core\2024\setvars.bat
blockMesh.exe
snappyHexMesh.exe -overwrite
simpleFoam.exe
foamToVTK.exe
```

坑：安装路径含空格会直接坏掉（官方 release note 明确要求）；大量 bash 语义（`runApplication`）需要 `setvars.bat` 环境；并行 decomposing 在 Windows 上很脆弱。

**C2. SU2（外流场/气动优化）**

```powershell
$env:SU2_RUN = "C:\SU2"; $env:SU2_HOME = "C:\SU2"
$env:PATH = "$env:SU2_RUN;" + $env:PATH
SU2_CFD.exe config.cfg
```

坑：网格必须是 `.su2` 或 CGNS（用 Gmsh 转换）；`SU2_RUN` 路径含空格的引号 bug 在 Windows 上未修。

---

## 6. 与 DeepSeek Harness 的集成：让工具链真正"Agent 化"

### 6.1 DSH 已经提供了什么（本机实测/代码核对）

| 能力 | 在 CAD/CAE 里的用法 |
|---|---|
| **MCP 客户端**（stdio / http / sse 三种传输） | 把 `freecad-mcp`、`@casys/mcp-calculix` 这类现成服务器挂上来；或把自己写的 `cad-cae-mcp` 挂上来 |
| **Skill 机制**（`SKILL.md` + 按需加载） | 把"STEP→网格→求解→出图"的标准作业程序固化成 skill，Agent 每次自动加载，避免重复解释 |
| **subagent / workflow** | 参数扫描：一个 workflow 脚本 fan-out N 个几何/载荷组合，各自独立跑求解，最后汇总 |
| **后台作业**（`job_output` / `job_kill`） | 长时求解（分钟~小时级）不阻塞对话，Agent 可以继续做别的 |
| **文件策略**（当前 `danger-full-access`） | 求解器需要写工作目录；生产环境建议收敛到 `workspace-write` + 只读工具目录 |
| **图像读取**（`read_image`） | Agent 可以直接"看"自己渲染出的应力云图，做视觉自检（是否全蓝、是否有奇异点） |

补充（代码核对，非猜测）：

- MCP 传输由 `@modelcontextprotocol/client` 提供，DSH 的 ACP 会话请求里 `mcpServers` 支持 `stdio`（`name/command/args/env`）、`http`、`sse` 三类。
- 插件装配走**分层配置**：`~/.dsh/profiles/<profile>/cordis.patch.yml`（本机为 `desktop`）在基础 bundle 之上按 `id` 覆盖/插入插件行，`cordis.yml` 只是空的根列表。
- 用户全局指令放在 `~/.dsh/AGENTS.md`（`$DSH_HOME` 可覆盖），项目级 `AGENTS.md` 从项目根逐级向下叠加 —— 这是把"本项目的 CAD 规范/单位制/禁止事项"注入每次会话的正规入口。

### 6.2 推荐集成方式：CLI 优先，MCP 其次

**不要为了 MCP 而 MCP。** 本工具链里每个工具本来就是"文件进、文件出"的 CLI，把它们包成 MCP 服务器的边际收益很低，反而多一层进程/协议故障点。推荐的优先级：

1. **Skill + 脚本（首选）**：把流水线写成 `skills/cad-cae/SKILL.md` + `scripts/*.py`，Agent 用 `pwsh` 调用。简单、可调试、可版本管理。
2. **MCP（按需）**：当需要"交互式探索"（在 FreeCAD 里看模型、增量修改）或需要把能力暴露给多个客户端时，再上 MCP。
3. **现成 MCP 的取舍**：
   - `freecad-mcp`（MIT，0.1.28）：依赖运行中的 FreeCAD GUI，适合副驾驶，不适合无人值守。
   - `@casys/mcp-calculix`（MIT，0.8.6）：把 STEP→Gmsh→CalculiX 封成受限工具集（只允许线性静力、模态、屈曲、蠕变、稳态热-结构），安全性好但不可扩展；分发以 Linux 容器为主，Windows 需要 Docker 或 Deno + 本地 gmsh/ccx。

### 6.3 一个可直接用的 Skill 骨架

见本仓库 `skills/cad-cae/SKILL.md`。核心是：**固定命令、固定目录、固定产物、固定判据**，让 Agent 不需要临场发挥。

---

## 7. Windows 专属坑清单（按杀伤力排序）

### 7.1 环境层

| 坑 | 现象 | 对策 |
|---|---|---|
| **`venv` 创建失败的误判（重要）** | 首轮部署时 `python -m venv .\_venv_occ` 报 9009，当时误判为"Store 版 Python 缺 venv 模块"；后续复测证明 **Store Python 3.13.9 的 venv/ensurepip 正常，工作区内建 venv 成功**，真正原因是那一轮的路径/瞬时环境问题 | 先用 `python -c "import venv, ensurepip"` **验证**再下结论；建 venv 用绝对路径，失败时换工作目录重试，不要直接归因于解释器 |
| **winget 拉大安装包挂起** | `winget install MSYS2.MSYS2` / `astral-sh.uv` 长时间 0 字节；换网络后 GitHub 直链仍只有 0.03 MB/s | 大包优先走镜像：MSYS2 用清华 `msys2-x86_64-latest.tar.xz`；FreeCAD 用清华 GitHub-release 镜像（399 MB/28 s）；装完务必比对官方 SHA256 |
| PATH 污染 | MSYS2 的 `ucrt64\bin` 全局前置会遮蔽系统 zlib/libssl/Qt6 | 只在单次进程内 `$env:PATH = "...ucrt64\bin;" + $env:PATH` |
| 中文控制台编码 | 求解器日志乱码、Python `UnicodeEncodeError` | `$env:PYTHONUTF8=1`、`$env:PYTHONIOENCODING=utf-8`，日志重定向到文件按 UTF-8 读 |
| **PowerShell 执行策略拦截未签名脚本** | `run_job.ps1` 报 "未对文件进行数字签名"（默认 Restricted） | 不要改机器级策略；每次调用加 `powershell -NoProfile -ExecutionPolicy Bypass -File ...`（本报告实测可行） |
| `.ps1` 里的中文被写坏 | Windows PowerShell 5.1 按 ANSI 读无 BOM 文件，中文变乱码、字符串截断导致语法错误 | 脚本正文用英文；或保证 UTF-8 with BOM；Python 脚本不受影响 |
| `PYTHONHOME` 污染 | FreeCAD 内嵌解释器启动失败 | 调 `FreeCADCmd` 前清空 `PYTHONHOME`/`PYTHONPATH` |
| conda 与 pip 混装 | `DLL load failed while importing OCP` | 一个环境只选一种包管理器 |

### 7.2 求解/网格层

| 坑 | 现象 | 对策 |
|---|---|---|
| **路径含空格** | blueCFD 直接坏；SU2 引号 bug；Gmsh `Merge "..."` 失败 | 所有工作目录用 `C:\cae\...`，绝不用 `C:\Program Files\...` 或含中文/空格的路径 |
| **MAX_PATH 260** | OCCT 临时文件、FreeCAD 插件路径、深目录失败 | 开启 `LongPathsEnabled=1`，并保持 `C:\cae\r\<4位编号>` 这样的浅目录 |
| **MPI 在 Windows 上是短板** | CalculiX 根本没有 MPI；Elmer 的 MS-MPI 常装不上；SU2 需额外 MS-MPI | 优先 OpenMP（`OMP_NUM_THREADS`）；真需要 MPI 就把 Linux 栈放 WSL2，Windows 只做编排 |
| **`.frd` 没人爱** | `meshio` 读不了 FRD；`ccx2paraview` 3.2.0 在 numpy≥2 下崩 | 用本报告自带的 `frd_reader.py`（定宽解析 + part.inp 拓扑），或把 numpy 钉到 <2 |
| **gmsh 把面单元写进 `.inp`** | `*ELEMENT, type=CPS6` 混入，ccx 报 "plane stress elements should lie in z=0" | 只给"体"建 Physical Group，并设 `Mesh.SaveAll=0` |
| **自己拼 C3D10 连接表** | ccx 报 "nonpositive jacobian" | 用 gmsh 自带 Abaqus 写出器，二阶四面体节点顺序由它负责 |
| **`ccx.exe` 2.23 在 PaStiX 阶段崩** | 退出码 `-1073741819`（0xC0000005），小模型也崩 | 改用同包 `ccx_i8.exe`（实测正常） |
| **离屏渲染无软件回退** | 服务/无 GPU 会话里截图失败 | 交互式会话跑渲染；或 Linux 容器渲染；或退化为 matplotlib 数值图 |
| **CGX 交互式** | Agent 卡在等窗口/等按键 | 全部后处理走 `frd_reader + PyVista`，不碰 cgx |
| **pip 版 gmsh ≠ MSYS2 版 gmsh** | 两个二进制、两套 OCC/MED 依赖 | 一个项目只选一种，写进 manifest 并固定版本 |

### 7.3 FreeCAD 层（2026-11-01 实测）

| 坑 | 现象 | 对策 |
|---|---|---|
| **安装目录带 Deny ACE** | `Could not create directories ... Access is denied`，随后 `Illegal storage access` 崩溃 | 装到 `C:\FreeCAD\1.1.4` 这类干净目录；本工作区 ACL 有 `Everyone: Deny DeleteSubdirectoriesAndFiles`，FreeCAD 初始化会撞上 |
| **`FreeCADCmd` 吃掉 `--job`** | 打印命令行帮助并退出，脚本根本没跑 | 用 `$env:CAE_JOB` 传参 + `-c "exec(open(...).read())"` |
| **`freecad_*.py` 静默不执行** | 位置参数 `.py` 先按模块 import，与 `freecad` 包冲突，无任何输出、退出码 0 | 改名 `fc_*.py`，或统一用 `-c exec(...)` |
| **异常仍返回 0** | 脚本抛 `RuntimeError`，`$LASTEXITCODE` 还是 0 | 脚本内 `try/except` + `sys.exit(9)`，外部再校验产物 |
| **TechDraw 只出几何** | `writeDXFPage` 成功，但 DXF 里没有标题栏文字与尺寸；`writeSVG`/`writePDF` 不存在 | `annotate_dxf.py`（ezdxf）补图框/标题栏/尺寸，再 matplotlib 出 PDF |
| **CJK 在 DXF 里变 `\U+XXXX`** | ezdxf 写出时转义，自身渲染器画成方框 | DXF 不放中文文本；PDF 由 matplotlib 用 SimHei 叠加绘制 |
| **STEP 导出空壳** | `Part.export([shape], path)` 只写 1 个 CARTESIAN_POINT、1640 B | 传 `DocumentObject`（`Part.export([obj], path)`）或 `shape.exportStep(path)`；并检查 `ADVANCED_FACE` 数量 |

### 7.4 版本/依赖层

| 坑 | 现象 | 对策 |
|---|---|---|
| CadQuery 与 build123d 共存 | 两套 `OCP`，DLL 冲突 | 分开 venv，用 STEP 通信 |
| FreeCAD 内嵌 Python 3.11 | 系统 3.13 的包不能 `import FreeCAD` | 不混用；FreeCAD 脚本只用它自带解释器 |
| OCCT 7.9 vs 8.0 | STEP 往返后 `is_valid` 失败 | 每个阶段入口都做 `is_valid` 校验，失败即回退 |
| OpenSCAD stable 太老 | 无 Manifold、无 `--backend` | 要么接受慢，要么锁一个 Nightly 版本并纳入回归测试 |
| `ezdxf` 缓存目录不可写 | 每次 import 打警告 `Cannot create cache home directory` | 设置 `EZDXF_CACHE_HOME` 到工作目录，或忽略（非致命） |

---

## 8. 许可证与商业化边界

| 组件 | 许可证 | 能嵌入商业产品吗 | 注意 |
|---|---|---|---|
| build123d / CadQuery | Apache-2.0 | ✅ 可以 | 保留 NOTICE |
| OCCT（OCP 封装） | LGPL-2.1 + 例外 | ✅ 动态链接 + 允许替换即可 | 不要静态链接闭源 |
| FreeCAD | LGPL-2.1+ | ✅ 作为独立进程调用 | 不要改其源码后闭源分发 |
| CalculiX / Gmsh / Elmer / OpenFOAM | **GPL-2.0/3.0** | ⚠ **只能独立进程 + 文件接口** | 绝不能链接进闭源程序；本报告的"文件进文件出"架构天然满足 |
| ParaView / VTK | BSD-3 | ✅ 可以 | 保留版权声明 |
| PyVista / meshio / ccx2paraview | MIT | ✅ 可以 | 保留版权声明 |
| NGSolve | LGPL-2.1 | ✅ 动态链接 | — |

**一句话：** 商业产品里，Apache/MIT/BSD/LGPL 部分可以放心用；**GPL 部分（ccx、gmsh、Elmer、OpenFOAM）必须放在独立进程里，用文件交互**——这正是本报告推荐的架构，所以不算额外成本。

---

## 9. 落地路线图（建议 3 个阶段）

### 阶段 1：打通"一个零件"（0.5–1 天）

- [ ] 验证 Python：`python -c "import venv, ensurepip; print('ok')"`；不 OK 再装 python.org 版（`winget install Python.Python.3.12`）
- [ ] `python -m venv C:\cae\venv` → `pip install build123d gmsh pyvista meshio`（`ccx2paraview` 可选）
- [ ] 装 MSYS2：`winget install MSYS2.MSYS2`，或解压便携版 `msys2-base-x86_64-latest.tar.xz` → `pacman -Sy` → `pacman -S mingw-w64-ucrt-x86_64-calculix-ccx`
- [ ] 跑通 `run_job.ps1`（或 §5.1 的 5 条命令），产出 `stress.png` + `result.json`
- [ ] 验收：`result.json` 无 `*ERROR`，`max_disp_mm`/`max_vm_stress_MPa` 为有限值且量级合理（可与解析解对照）

> 本机参考结果（80×40×12、2 mm 圆角、钢、500 N 自由端面下压，固定端为 min-X 面）：`max_disp_mm = 0.070832`、`max_vm_stress_MPa = 51.60`（节点外插峰值；同一复现网格单元平均峰值 40.38 MPa）、求解 13.2 s。注意该峰值随网格加密上升（h=6/4/3 mm → 44.5/49.6/51.0 MPa）、不收敛，只作网格带内复现性参考。

### 阶段 2：固化为 Skill + 参数化（1–2 天）

- [ ] 把流水线写成 `skills/cad-cae/SKILL.md` + `scripts/{model,mesh,deck,render}.py`
- [ ] `params.json` 定义几何/材料/载荷/网格尺寸
- [ ] 加"前置校验"（`is_valid`、网格质量、单位检查）和"后置校验"（收敛、应力合理性）
- [ ] 用 DSH 的 subagent 跑 3 个不同载荷工况，验证并行不打架（每个任务独立目录）

### 阶段 3：扩展与规模化（按需）

- [ ] 参数扫描：DSH `workflow` 脚本 fan-out N 个工况，汇总成 CSV/图表
- [ ] 多物理场：接 Elmer（热-结构）
- [ ] CFD：blueCFD 或 SU2（注意路径/MPI 坑）
- [ ] 可视化增强：ParaView `pvbatch` 出动画；或 PyVista 出交互式 HTML（`export_html`）
- [ ] 可选：把最常用的 3 个动作包成 MCP server，供其他客户端复用

---

## 10. 附录

### 10.0 实测运行记录（可复现）

```
results/box-cantilever-500N/
├── params.json        80×40×12 mm，2 mm 圆角，钢 E=210 GPa ν=0.3，500 N 向 -Z
├── model.json         volume 38358.796 mm³，bbox [80,40,12]，STEP 31,743 B
├── part.step          build123d 0.13.0 / OCCT 8.0.1
├── mesh.json          nodes 35,510；C3D10 × 22,333；fixed 173 节点；load 3,085 节点
├── groups.json        FIXED/LOAD 精确节点号（按坐标平面筛选）
├── job.inp            4.0 MB：*NODE/*ELEMENT(C3D10)/*NSET/*MATERIAL/*STATIC/*BOUNDARY/*CLOAD
├── job.frd            CalculiX 2.23 结果（ccx_i8.exe，13.2 s）
├── job.sta            1 step / 1 increment / 收敛
├── job.vtu            35,510 点，数组 U / U_mag / S / S_vm（节点值；S 另有单元平均的 cell_data 版本）
├── result.json        max_disp_mm 0.070832，max_vm_stress_MPa 51.60（节点外插峰值；单元平均 40.38），errors []
├── stress.png         等轴测应力云图
└── stress_side.png    XZ 侧视，固定端应力集中可见
```

关键命令（实际执行过的版本）：

```powershell
$py = "_venv_cad\Scripts\python.exe"
& $py scripts\model.py  --job results\box-cantilever-500N
& $py scripts\mesh.py   --job results\box-cantilever-500N
& $py scripts\deck.py   --job results\box-cantilever-500N
$env:PATH = "msys\msys64\ucrt64\bin;" + $env:PATH
Set-Location results\box-cantilever-500N; ccx_i8.exe -i job
& $py ..\..\scripts\render.py --job .
```

校验逻辑（也是 Agent 应该照抄的）：

1. `model.json.volume_mm3 > 0` 且 bbox 与参数一致；
2. `mesh.json.nodes_fixed > 0` 且 `nodes_load > 0`；
3. `job.dat` 中不含 `*ERROR`；`job.sta` 末行显示增量完成；
4. `result.json` 的 `max_disp_mm`、`max_vm_stress_MPa` 为有限值，量级与手算/经验相符；
5. `stress.png` 存在，且用 `read_image` 目视确认不是纯色。

| 工况 | 载荷 | 最大位移 | 最大 von Mises（节点外插峰值） | 求解时间 |
|---|---|---|---|---|
| job-0001 | 500 N | 0.070832 mm | 51.60 MPa | 13.2 s |
| job-0003 | 800 N（同一套网格） | 0.113330 mm | 82.56 MPa | 14.4 s |

> 表中 von Mises 为 FRD 节点外插峰值，不是单元积分点峰值；同一复现网格的单元平均峰值为 40.38 MPa（500 N）。

位移比值 1.59997、应力比值 1.60000；逐节点检查 `S` 张量的每个分量，比值都是 1.59999±1e-5，
证明这是严格线弹性响应而非数值巧合。**建议把这条"载荷×1.6 ⇒ 结果×1.6"作为流水线的常驻回归断言** —— 它比"退出码为 0"可靠得多。

### 10.1 版本快照（2026-11-01）

| 组件 | 版本 | 来源 |
|---|---|---|
| build123d | 0.13.0 | PyPI |
| cadquery | 2.8.0 | PyPI |
| cadquery-ocp / novtk | 8.0.1.1.0 | PyPI |
| gmsh | 4.15.2 | PyPI / MSYS2 |
| FreeCAD | **1.1.4**（`C:\FreeCAD\1.1.4`，便携版） | 清华 GitHub-release 镜像 + SHA256 校验 |
| ezdxf | 1.4.5 | PyPI（标题栏/尺寸/PDF） |
| OpenCASCADE | 7.9.3 | MSYS2 |
| CalculiX ccx | 2.23 | MSYS2 |
| Elmer FEM | 26.2.1 | MSYS2 |
| ParaView | 6.2.0 / 6.1.1 | winget / MSYS2 |
| VTK | 9.6.2 | MSYS2 |
| OpenSCAD | 2021.01 | winget / MSYS2 |
| SU2 | 8.6.0 | GitHub Releases |
| blueCFD-Core | 2024-1 (OF12) | GitHub Releases |
| PyVista | 0.49.x | PyPI |
| meshio | 5.3.5 | PyPI |
| ccx2paraview | 3.2.0 | PyPI |

### 10.2 主要参考源

- MSYS2 包库：<https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-calculix-ccx>
- MSYS2 gmsh：<https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-gmsh>
- MSYS2 elmerfem：<https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-elmerfem>
- MSYS2 paraview：<https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-paraview>
- build123d PyPI：<https://pypi.org/pypi/build123d/json>
- cadquery PyPI：<https://pypi.org/pypi/cadquery/json>
- cadquery-ocp PyPI：<https://pypi.org/pypi/cadquery-ocp/json>
- gmsh PyPI：<https://pypi.org/pypi/gmsh/json>
- FreeCAD Releases：<https://api.github.com/repos/FreeCAD/FreeCAD/releases/latest>
- SU2 Releases：<https://api.github.com/repos/su2code/SU2/releases/latest>
- blueCFD-Core：<https://github.com/blueCFD/Core/releases>
- FreeCAD Headless 文档：<https://wiki.freecad.org/Headless_FreeCAD>
- freecad-mcp：<https://pypi.org/project/freecad-mcp/>
- Code_Aster Windows 说明：<https://www.code-aster.de/code-aster/windows-or-linux.html>
- preCICE 安装：<https://precice.org/docs/installation/overview/>

### 10.3 术语

- **BREP**：边界表示法，精确几何（OCCT 的核心数据结构）。
- **STEP (ISO 10303)**：精确 BREP + 装配 + PMI 的交换格式，本工具链的几何契约。
- **Physical Group**：Gmsh 中给几何实体打的标签，导出到 `.inp` 后成为 `*NSET/*ELSET`，是"边界条件选择器"的唯一可靠载体。
- **FRD**：CalculiX 的结果格式，需 `ccx2paraview` 转换。
- **SIF**：Elmer 的求解器输入格式（纯文本）。
- **CAD-as-Code**：用代码（而非 GUI 交互）定义几何，天然可版本控制、可参数化、可被 LLM 生成。

---

*报告完。配套文件：`skills/cad-cae/SKILL.md`（Agent 作业规程）、`scripts/`（可执行脚本骨架）。*
