# FreeCAD 必要性分析 与 部署复盘

> 版本：v1.2 ｜ 2026-11-01 ｜ 对象：`TestCAE` 开源 CAD/CAE 工具链
> 结论先行：
> 1. **FreeCAD 对"全自动 Agent 流水线"不是必需的** —— 上一轮在没有 FreeCAD 的情况下已跑通 STEP→网格→求解→云图。
>    它真正的价值是：**人在环的审图/改图工作台**，以及**投影视图**这一项可以由它代劳。
> 2. **首轮部署失败不是"Windows 不行"**，而是 3 类问题叠加：4 个环境问题、5 个工具链缺陷、4 处我方操作/编码失误；
>    其中 1 个还是我方的**误诊**（Python venv），因此多走了约 2 小时弯路。
> 3. **v1.2 更新：换网络后 FreeCAD 已成功部署并接入流水线**（`C:\FreeCAD\1.1.4`，便携版 + SHA256 校验），
>    同时实测出无头能力的硬边界：**能出几何 DXF，不能出 PDF/SVG**；配套用 `ezdxf` 补齐标注与 PDF。

---

## 第一部分：FreeCAD 在工具链中的必要性

### 1. 判据：什么才算"必要"

一个组件要被称为"必要"，必须满足至少一条：

| 判据 | 含义 |
|---|---|
| **N1 能力独占** | 该能力在工具链其他组件里**完全无法实现** |
| **N2 显著更优** | 其他方案能实现，但成本/风险高一个数量级 |
| **N3 闭环必需** | 没有它某条主流程就走不完 |

按这三条逐项检验 FreeCAD 的五个"招牌能力"。

### 2. 逐项检验

| # | FreeCAD 能力 | 其他可用方案 | 无头/自动化可行性（1.1.4 实测） | 判定 |
|---|---|---|---|---|
| 1 | **Sketcher 全局约束求解** | build123d 用**显式坐标 + 局部求解器**（`ConstrainedArcs` / `ConstrainedLines` / `Triangle` / `BlendCurve`），复杂代数关系可 `sympy.solve` 后代入；CadQuery 无 2D 草图求解器 | 可脚本调用，但"加约束→求解→读结果"的状态机对 Agent 不友好，失败诊断弱 | **不构成 N1**：多数零件用显式几何即可；约束求解的价值主要在**人反复改尺寸**时 |
| 2 | **装配约束求解**（Ondsel solver：Fixed/Revolute/Slider/Ball/Distance/Parallel/Perpendicular/Angle/Gears/Belt/Screw） | CadQuery 有独立装配求解器（`cq.Assembly` + `Constraint`）；build123d 用 `Location`/`Pos` + `Joints`；简单布局用变换矩阵 | 典型工作流是**拖拽 + 点选面/边**；纯脚本要自己构造 LCS 引用，成本高 | **不构成 N1**：强项是机构运动学，不是本工具链（静力/热）的必需项 |
| 3 | **2D 工程图**（TechDraw） | build123d 只能导 DXF/SVG（无尺寸、无 GD&T）；可 `ezdxf` 补标注 | **实测**：`TechDraw.writeDXFPage` **可无头导出**，1:1 正确（100×50×10 的盒 → 100×10 矩形），但**只含几何线框**；`writeSVG` / `writePDF` **不在 C++ API 里**（`dir(TechDraw)` 无此符号） | **唯一接近 N1，但只解决"投影"这一半**：几何自动、标注/标题栏/PDF 需 `ezdxf` 补（本工程已实现），GD&T/剖视/局部放大仍需 GUI |
| 4 | **FEM 工作台** | 本工具链已**直接驱动 CalculiX `ccx_i8`**；FreeCAD FEM 是同一求解器的另一个前端 | 可脚本，但会引入内嵌 Python 3.11、`user.cfg` 竞争、FEM 结果对象等额外状态 | **不构成 N3**：用同一求解器的两个前端做"交叉验证"验证的是**前端**，不是物理 |
| 5 | **格式互操作**（STEP/IGES/DXF/DWG/IFC/STL/3MF…） | build123d/OCP 覆盖 STEP/IGES/BREP/STL/3MF/DXF/SVG；`ifcopenshell` 可单装；DWG 需 ODA（非开源） | `FreeCADCmd` 做批量转换可行 | **弱 N2**：格式特别杂时省事 |

### 3. 成本侧：引入 FreeCAD 要付出什么

| 成本项 | 具体表现 | 对 Agent 的影响 |
|---|---|---|
| 安装体积 | 便携版解压后约 1.5 GB（下载 399 MB） | 镜像/CI 缓存变重；但便携版可整目录复制、免安装 |
| 冷启动 | 每次 `FreeCADCmd` 约 3–10 s（本机实测） | 参数扫描 ×100 工况时不可忽略 |
| 解释器隔离 | 内嵌 **Python 3.11**（conda-forge 打包），与主 venv（3.13）不能互 import | 多一套依赖管理 |
| 状态污染 | `%APPDATA%\FreeCAD\user.cfg` 被并行任务竞争 | 每任务设 `FREECAD_USER_HOME` 或 `-u/-s` |
| 退出码不可信 | 脚本抛异常仍返回 0；**没有 `--python-exit-code`** | 必须靠"产物断言"兜底 |
| 脚本语义陷阱 | 位置参数 `.py` 先按模块 import；`freecad_*.py` 会与子模块冲突 | 命名与调用方式要特殊处理 |
| 2D 出图半自动 | TechDraw 只出几何 DXF，PDF/SVG 无 API | 需要 `ezdxf` + matplotlib 补一条链路 |
| 生态锁定 | `.FCStd` 是私有格式，参数历史锁在 FreeCAD 里 | 与"Python 即参数源"的 CAD-as-Code 理念冲突 |

### 4. 结论：FreeCAD 的定位应是"审图台 + 投影器"，不是"建模 API"

**推荐架构（双轨）：**

```
┌──────────────── Agent 自动轨（不依赖 FreeCAD）────────────────┐
params.json → build123d → part.step → gmsh → ccx_i8 → PyVista → stress.png / result.json
└───────────────────────────────────────────────────────────────┘
                         │ part.step（只读交付物）
                         ▼
┌──────────── 可选：FreeCAD 投影轨（无头）────────────┐
│ FreeCADCmd → TechDraw.writeDXFPage → 几何 DXF        │
│ ezdxf + matplotlib → 标题栏/尺寸 → drawing.pdf       │
└──────────────────────────────────────────────────────┘
                         │ 需要 GD&T / 剖视 / 手改
                         ▼
┌──────────── 人在环轨（FreeCAD GUI，按需）────────────┐
│ 工程师打开 .FCStd → 目视/剖切/改特征 → 导出 STEP → 回自动轨 │
└──────────────────────────────────────────────────────┘
```

**评分：**

| 场景 | FreeCAD 必要性 | 说明 |
|---|---|---|
| 全自动参数扫描 / CI | **1.5 / 5（不必要）** | 已证明无 FreeCAD 可闭环；引入只增加故障面 |
| 单件设计 + 自动分析 | **2 / 5（可选）** | build123d 足够 |
| 需要**投影视图**（无标注） | **3 / 5（可自动）** | TechDraw DXF 可用，配 `ezdxf` 补全 |
| 需要**正式 2D 工程图**（尺寸/公差/标题栏） | **4 / 5（建议，半自动）** | 投影自动 + 标注脚本化 + 人工审签 |
| 复杂装配 / 机构运动 | **3.5 / 5（建议）** | Ondsel + Joint 体系强于手写变换 |
| 格式特别杂的存量数据 | **3 / 5（有用）** | 批量转换省事 |
| 教学/评审/交付演示 | **4 / 5（建议）** | 可视化与交互不可替代 |

**一句话：** 把 FreeCAD 当"**人类工程师的工作台**"和"**投影视图生成器**"是对的；把它当"**Agent 的建模 API**"是错配。

### 5. 什么情况下 FreeCAD 会变成"必要"

满足以下任一条，才建议把 FreeCAD 纳入主链路：

1. 交付物**必须**是带尺寸/公差/标题栏的 2D 图纸（且团队不愿用 `ezdxf` 自绘）；
2. 需要**装配级**的干涉检查、运动学仿真、BOM 输出；
3. 需要读取/写回客户给的 `.FCStd` 或大量异构 CAD 格式；
4. 流程里必须有人**手工改特征**并把结果交回给 Agent。

反之，如果只是"零件建模 + 静力/热分析 + 云图"，**不要引入 FreeCAD**。

---

## 第二部分：首轮部署失败复盘

### 6. 事实清单：13 个失败点

按"环境 / 工具缺陷 / 我方失误"分类，全部有现场证据。

#### A. 环境问题（4 个）

| # | 现象 | 证据 | 根因 | 最终解法 |
|---|---|---|---|---|
| A1 | `winget install MSYS2.MSYS2` 挂起 20+ 分钟 | 下载缓存文件 0 字节；`winget list MSYS2` 查不到；进程 CPU 几乎为 0 | 旧网络拉大安装包不稳定，winget 无进度反馈 | 便携 tarball：清华镜像 `msys2-x86_64-latest.tar.xz`（43 MB）→ 解压 → `pacman -Sy` + `pacman -S` |
| A2 | 手工解包 MSYS2 包后 `ccx.exe` 起不来 | 退出码 `-1073741515`（0xC0000135，DLL not found）；`pefile` 递归依赖图列出缺 `libgfortran-5`、`libgcc_s_seh-1`、`libgomp-1`、`libquadmath-0`、`libhwloc-15`、`libmetis`、`libscotch`、`libstarpu` 等 9 个 | 逐包下载时踩了"虚拟包/传递依赖"（`gcc-libgfortran` 是 virtual package，真实提供者是 `libgfortran`） | 放弃手工解包，用 `pacman` 一次装齐 |
| A3 | `winget install astral-sh.uv` 挂起 | 后台任务 5 分钟无输出 | 同 A1：GitHub Releases 直链不可达 | 放弃 uv；用已存在的 venv + 镜像源 |
| A4 | `python -m venv $env:TEMP\venv_probe` 报 `WinError 5 拒绝访问` | `exit=1`；同一命令在工作区内 `exit=0` 且 pip 可用 | 进程对 `%TEMP%` 子目录无写权限 | venv 建在工作区内；不要默认 `%TEMP%` 可用 |

#### B. 工具链缺陷（5 个，都是真 bug）

| # | 现象 | 证据 | 根因 | 最终解法 |
|---|---|---|---|---|
| B1 | `*ERROR in gen3delem. ... plane stress ... should lie in z=0` | `part.inp` 里有 `*ELEMENT, type=CPS6, ELSET=Surface1` | gmsh 的 Abaqus 写出器默认把面单元也写进去，ccx 当平面应力 | 只给"体"建 Physical Group + `Mesh.SaveAll=0` |
| B2 | `*WARNING reading *STEP: parameter not recognized: NAME=STATIC` | deck 是 `*STEP, NAME=STATIC, INC=200` | CalculiX 的 `*STEP` 卡不接受 Abaqus 的 `NAME=`/`INC=` | 裸 `*STEP` + 独立 `*STATIC` 卡 |
| B3 | `*ERROR in e_c3d: nonpositive jacobian`（大量） | 自己拼的 C3D10 连接表，element 21079 起全负 | 二阶四面体 10 节点顺序不是"先 4 角点再 6 边中点"那么简单 | 用 gmsh 自带 Abaqus 写出器（它在写出时做节点重排） |
| B4 | `ccx.exe` 直接崩，退出码 `-1073741819`（0xC0000005） | 6 单元小模型也崩；`ccx_i8.exe` 同一模型 13.2 s 收敛 | MSYS2 的 CalculiX 2.23 `ccx.exe`（32 位整数）在 PaStiX 分解阶段的缺陷 | 默认调用 `ccx_i8.exe` |
| B5 | `ccx2paraview` 抛 `TypeError: '<' not supported between instances of 'complex' and 'complex'` | 栈在 `common.py:784 calculate_principal()` | ccx2paraview 3.2.0 与 numpy ≥2 不兼容 | 自写 `frd_reader.py`，去掉该依赖 |

#### C. 我方失误（4 个，必须认账）

| # | 失误 | 后果 | 教训 |
|---|---|---|---|
| C1 | **误诊 Python venv**：把一次 `9009` 归因为"Store 版 Python 缺 venv/ensurepip" | 放弃 venv，改用全局 pip，埋下污染隐患；并浪费约 2 小时在 uv/micromamba 等替代路径上 | **先验证再归因**：`python -c "import venv, ensurepip"`；复测证明 Store Python 3.13.9 完全正常，工作区内建 venv 成功 |
| C2 | PowerShell 单行命令解析错误（引号未闭合） | 首条环境探测命令直接失败 | 复杂命令拆多行；用 here-string 传脚本 |
| C3 | `param()` 块最后一个参数后**缺逗号** + 脚本无 BOM 被 5.1 按 ANSI 读 | `run_job.ps1` 报 `Unexpected token '}'` / 中文乱码 / 字符串截断 | `.ps1` 正文用英文；最后参数加 `,`；存 UTF-8 with BOM 或纯 ASCII |
| C4 | FRD 解析连写 3 个 bug：① `"100CL" in line` 把"恰好 100 字符的数据行"误判成块头 → 位移全 0；② 用 `split()` 解析定宽字段 → `5-5.05751E-04` 解析失败，357 节点只读到 30 个；③ 复数排序 | 最大位移显示 0.0，一度误判求解失败 | 定宽格式必须按列切；判块头要锚定行首；写最小样例单测 |

### 7. 根因归纳：5 条

| # | 根因 | 说明 | 影响 |
|---|---|---|---|
| R1 | **缺少分层验收门（gate）** | 环境层没验就装 CAD/CAE；工具层没跑最小样例就上 35k 节点模型 | 放大 A1–A4、B1–B5 |
| R2 | **误诊后不回溯** | 一旦归因为"Store Python 缺陷"，就再没回头验证 | C1（浪费最大） |
| R3 | **Windows 特有的隐式契约** | 路径、`%TEMP%` 权限、执行策略、无 BOM 的 UTF-8、DLL 依赖不透明 | A4、C2、C3 |
| R4 | **工具真实行为 ≠ 文档** | gmsh 多写面单元、CalculiX 不认 `*STEP` 参数、`ccx.exe` PaStiX 崩、ccx2paraview 与 numpy 2 冲突、TechDraw 不能出 PDF | B1–B5 |
| R5 | **没有"已知答案"基准** | 直到最后才做"载荷 ×1.6 ⇒ 结果 ×1.6"的线性自检 | 排查时间翻倍 |

### 8. 改进：把 13 个坑变成 6 道门

下次部署（或换机器）按这个顺序做，每道门有**可执行的验收命令**，不过门不进入下一层：

| 门 | 验收命令 | 通过标准 |
|---|---|---|
| **G0 基础环境** | `python -c "import venv, ensurepip"`；`python -m venv .\_v`；`.\_v\Scripts\python -m pip -V` | 三行都成功；**失败先查路径/权限，不要归因解释器** |
| **G1 包安装** | `pip install -i <镜像> build123d gmsh pyvista` | `import build123d, gmsh, pyvista` 成功 |
| **G2 建模** | `model.py` 输出 STEP | `is_valid`、体积 > 0、bbox 与参数一致 |
| **G3 网格** | `mesh.py` 输出 `.inp` + `groups.json` | `part.inp` **只含 C3D4/C3D10**（grep 不到 `CPS6`）；固定/加载节点 > 0 |
| **G4 求解器冒烟** | 在 `scripts/` 里跑 `ccx_i8.exe -i smoke`（1 mm 立方体、1 N，max\|U\| ≈ 5.17e-6 mm） | 退出码 0；`.sta` 有 1 个增量；**< 0.1 s 完成** |
| **G5 全链路 + 已知答案** | `run_job.ps1` + 线性自检（载荷 ×1.6） | 位移/应力比值 1.6±1%；`.dat` 无 `*ERROR` |
| **G6（可选）制图** | `run_job.ps1 -WithFreeCAD` | `freecad/report.json` 体积一致；`drawing.pdf` 图框/标题栏/尺寸齐全 |

配套的 3 条工程习惯：

1. **最小可复现优先**：任何"工具疑似坏了"，先跑 `scripts/smoke.inp`（8 节点 / 1 个 C3D8 单元，< 0.1 s），能跑再怪模型。
   注意：一阶六面体 C3D8 的节点顺序可以手写；但**二阶四面体 C3D10 的连接表必须由 gmsh 写**（手拼会 `nonpositive jacobian`），见 `mesh.py` 文件头。
2. **产物断言 > 退出码**：CalculiX 返回 0 不代表成功，FreeCADCmd 异常也返回 0；一律查 `.dat`/`.sta`/产物。
3. **固定版本 + 记录版本**：`ccx_i8 2.23`、`gmsh 4.15.2`、`build123d 0.13.0`、`numpy 2.5.4`、`pyvista 0.49.2`、`FreeCAD 1.1.4`。

### 9. FreeCAD 二次部署记录（v1.2，换网络后）

| 步骤 | 结果 |
|---|---|
| 网络探测 | GitHub 可达但极慢（0.03 MB/s）；清华 GitHub-release 镜像 **28 s 下完 399 MB** |
| 下载 | `FreeCAD_1.1.4-Windows-x86_64-py311.7z`，SHA256 `4828741f…4d6d` **与官方一致** |
| 解压 | 7-Zip，194 s，解压到工作区 `apps/` |
| 首次启动 | ❌ `Could not create directories ... Access is denied` —— 工作区 ACL 有 `Everyone: Deny DeleteSubdirectoriesAndFiles` |
| 迁移 | 复制到 `C:\FreeCAD\1.1.4`（144 s），`FreeCADCmd --version` → **FreeCAD 1.1.4 Revision 20260928** |
| 建模验证 | `Part.makeBox(40,20,10)` → 体积 7770.36 mm³（40×20×10 减 2 mm 圆角），26 面 |
| STEP 导入 | 读 `results/box-cantilever-500N/part.step` → 体积 38358.796 mm³，与 build123d 完全一致 |
| TechDraw | `writeDXFPage` 成功：A4、1:1、Front+Top，80×12 / 80×40 均正确；**无标题栏、无尺寸** |
| PDF/SVG | ❌ `writeSVG`/`writePDF` 不存在；`getSVGFile` 也不在 `DrawPage` 方法里 |
| 退出码 | 未捕获异常 → **仍返回 0**；`sys.exit(3)` → 3 |
| 标题栏 | `setEditFieldContent` 可用（字段名如 `DRAWING_NAME`/`PARTNAME`），但**不写进 DXF** |
| 补全方案 | `annotate_dxf.py`：ezdxf 加图框/标题栏/总长总高尺寸 → matplotlib 出 A4 PDF（中文用 SimHei，实测通过） |

**最终产物**（`results/box-cantilever-500N/freecad/`）：`model.FCStd`、`drawing.dxf`、`drawing_annotated.dxf`、`drawing.pdf`、`drawing_preview.png`。

### 10. 如果重来一次，时间线会是这样

| 阶段 | 原方案（实际） | 改进后 | 预计耗时 |
|---|---|---|---|
| 环境 | winget 装 MSYS2（挂起 20 min）→ 手工解包（DLL 地狱）→ 便携 tarball | 直接便携 tarball + pacman | 15 min |
| Python | 误判 venv → uv（挂起）→ 全局 pip | G0 门验证 venv，工作区内建 | 5 min |
| 网格 | CPS6 污染 → 改 Physical Group → C3D10 负雅可比 → 换 gmsh 写出器 | 一开始就用"只建体组 + SaveAll=0 + gmsh 写出器" | 20 min |
| 求解 | 卡 `*STEP` 参数 → ccx.exe 崩 → 试 ccx_i8 | 先 G4 冒烟，直接锁定 ccx_i8 | 15 min |
| 后处理 | ccx2paraview 崩 → 自写 FRD 解析（3 个 bug） | 直接 `frd_reader.py` + 最小样例单测 | 30 min |
| FreeCAD | 安装到工作区 → Access denied → 迁 C:\FreeCAD → 试出 API 边界 | 直接装 `C:\FreeCAD`，先跑 `writeDXFPage` 探边界 | 25 min |
| **合计** | **约 6–7 小时（含试错）** | **约 2 小时** | **−70%** |

---

## 附录：证据与来源

- `ccx.exe` 崩溃复现：`results/box-cantilever-500N` 内 `ccx.exe -i job` → `-1073741819`；`ccx_i8.exe -i job` → 13.2 s 收敛。
- `venv` 误诊复测：`python -c "import venv, ensurepip"` → OK；工作区内建 venv 成功且 `pip 25.2` 可用。
- FreeCAD 无头：官方 Headless FreeCAD 文档说明无 GUI 时**没有 view provider**；
  本机实测 `dir(TechDraw)` 无 `writeSVG`/`writePDF`，`DrawPage` 无 `getSVGFile`。
- build123d 约束能力：官方 "Drawing with Constraints" 教程——**无全局草图求解器**，
  提供 `ConstrainedArcs`/`ConstrainedLines`/`Triangle`/`BlendCurve` 等局部求解器，复杂关系建议 `sympy`。
- FreeCAD 装配：1.0 起内置 Assembly 工作台，基于 **Ondsel solver**。
- 版本快照：build123d 0.13.0 / cadquery-ocp-novtk 8.0.1.1.0 / gmsh 4.15.2 / ccx 2.23 /
  numpy 2.5.4 / pyvista 0.49.2 / vtk 9.7.1 / ezdxf 1.4.5 / FreeCAD 1.1.4。
