# 温度场验证：发动机排气管热分析（CalculiX 热传导）

> 版本：v1.0 ｜ 2026-11-01
> 目标：用一篇温度场论文的参数，验证本地工具链的热传导求解精度，**发现并修正工具链的问题**，并给出 2D/3D 可视化。

---

## 0. 结论速览

| 验证项 | 参考解 | FEA | 误差 | 判定 |
|---|---|---|---|---|
| **A. 均匀气温 500 °C（解析解严格成立）** | 内壁 453.127 °C / 外壁 452.676 °C | 453.123 / 452.673 | **0.001 %** | ✅ 求解器精确 |
| **B. 轴向梯度 500→350 °C（考虑轴向导热）** | 440.85 °C（入口段）→ 329.46 °C（出口段） | 440.85 / 330.01 | **0.168 %** | ✅ |
| （对照）B 若用"逐段 1D 径向"参考 | 446.36 → 324.54 | 同上 | 1.685 % | ⚠️ **参考模型错，不是求解器错** |

**一句话：热传导求解器对精确解的误差是 0.001%；带轴向梯度时，只要参考解里包含轴向导热，误差也是 0.17%。中途出现的 1.7% 偏差，最后证明是"参考模型漏了轴向导热"，不是工具链算错。**

---

## 1. 论文与提取的参数

**论文**：S. D. Petković, R. B. Pešić, J. K. Lukić, *Heat Transfer in Exhaust System of a Cold Start Engine at Low Environmental Temperature*, **Thermal Science 14 (Suppl.): S219–S232, 2010**.
PDF：<http://is.fink.rs/podaci/Jovanka_Lukic/74/TSCI100505070P.pdf>

### 1.1 Table 1 — 排气管（元件 1）

| 参数 | 值 |
|---|---|
| 长度 L | 200 mm |
| 直径 D | 39 mm |
| 壁厚 t | 1.5 mm |
| 材料 | Č.4571（AISI 316Ti） |
| 密度 ρ | 7900 kg/m³ |
| 导热系数 λ | 15 W/(m·K) |
| 比热 c | 477 J/(kg·K) |

### 1.2 场景

论文研究**低温环境下的冷启动**：排气从环境温度升到工作温度，管壁温度随时间上升；
论文用有限差分求解"排气管 + 预催化器 + 消声器"的系统级模型，输出的是**随时间变化的部件温度曲线**。

> **为什么不能直接逐点对标**：论文给的是系统级 0D/1D 曲线（多部件、时间历程），不是"某点某时刻 = 某温度"的场数据；也没有给出可直接复现的 h 分布与网格。因此本报告把它作为**几何、材料与物理场景的来源**，精度验证改用同几何同边界条件下的**精确解**。

---

## 2. 模型与边界条件

- 几何：r_i = 18 mm、r_o = 19.5 mm、L = 0.2 m 的圆管（build123d 布尔 → STEP → gmsh 四面体，8,975 节点 / 26,717 单元）
- 单位制：**SI（m, N, Pa, kg, s, K）**——热分析必须用 SI，否则 *CONDUCTIVITY / *DENSITY / *SPECIFIC HEAT 极易混单位
- 内壁：`*FILM`，h_i = 100 W/(m²·K)，气体 500 °C（工况 B 沿轴向线性降到 350 °C）
- 外壁：`*FILM`，h_o = 10 W/(m²·K)，环境 20 °C
- 求解：`*HEAT TRANSFER, STEADY STATE`

### 2.1 参考解 A（均匀气温）——严格解析

两层对流边界下的 1D 径向解：

```
R_i = 1/(h_i·2πr_i·L),  R_w = ln(r_o/r_i)/(2πλL),  R_o = 1/(h_o·2πr_o·L)
q = (T_gas − T_amb)/(R_i + R_w + R_o)
T_wi = T_gas − q·R_i,   T_wo = T_amb + q·R_o
```

### 2.2 参考解 B（轴向梯度）——含轴向导热的肋片解

若把管道按轴向切成 10 段、每段独立做 1D 径向计算，就忽略了**轴向导热**。钢管里这个效应极强：

```
m = sqrt((h_oP_o + h_iP_i)/(λA_c)) ≈ 68.8 1/m  →  mL ≈ 13.8
```

即管壁在轴向上几乎是等温耦合的，热量会从入口段沿壁面流向出口段。正确的 1D 参考解是肋片方程：

```
λA_c T'' = h_oP_o(T − T_amb) + h_iP_i(T − T_gas(x)),   T_gas 线性
⇒ T'' − m²T = −m²(A + Bx)   通解 T = A + Bx + C·e^{mx} + D·e^{−mx}
边界 dT/dx = 0（两端绝热）定出 C、D
```

---

## 3. 验证结果

### 3.1 工况 A：均匀气温（解析解严格）

| 位置 | 解析 | FEA | 误差 |
|---|---|---|---|
| 内壁 | 453.127 °C | 453.123 °C | **0.001 %** |
| 外壁 | 452.676 °C | 452.673 °C | **0.001 %** |

**判定：✅ 通过。** 这说明 `*FILM` 的对流边界、`*CONDUCTIVITY` 的导热、以及 3D 网格的离散都是正确的。

### 3.2 工况 B：轴向梯度（10 段，500→350 °C）

| 段（z） | 气体 | FEA 内壁 | 肋片解（含轴向导热） | 误差 | 逐段 1D 参考 | 误差 |
|---|---|---|---|---|---|---|
| 10 mm | 492.5 | 440.85 | 441.37 | **0.118 %** | 446.36 | 1.24 % |
| 50 mm | 462.5 | 419.31 | 419.40 | 0.02 % | 421.20 | 0.45 % |
| 110 mm | 417.5 | 380.31 | 380.12 | 0.05 % | 383.69 | 0.89 % |
| 190 mm | 357.5 | 330.01 | 329.46 | **0.168 %** | 324.54 | 1.69 % |

- 对**肋片解**：最大误差 **0.168 %** ✅
- 对**逐段 1D**：最大误差 1.685 %——但这是参考模型漏掉轴向导热造成的，不是 FEA 的错

**判定：✅ 通过。** 而且这条对照本身就说明了：**钢管排气管的轴向导热不可忽略（mL≈14），用"逐段独立 1D"去校验热分析会得到假的 1.7% 误差。**

---

## 4. 工具链的改进（本轮真正修掉的问题）

| # | 问题 | 现象 | 根因 | 修正 |
|---|---|---|---|---|
| 1 | **`*FILM` 数据顺序** | 首轮全管温度 94.7 °C（应为 453 °C，差 4.8 倍） | 按 `(单元, 面, h, T_sink)` 写，CalculiX 实际按 `(单元, 面, **T_sink**, **h**)` 读 | 交换后两列；写进技能文档 |
| 2 | 参考模型漏轴向导热 | 出现 1.7% "误差" | 逐段独立 1D 忽略 mL≈14 的轴向耦合 | 增加肋片闭式解作参考，误差降到 0.17% |
| 3 | 几何 z 起点未归一 | 分段统计整段取不到节点（NaN） | build123d 布尔后管子位于 z = 0.1–0.3 m | 用 `z_min` 归一化 |
| 4 | 端盖节点混入分段均值 | 出口段温度被拉低 | 端盖（绝热）节点半径恰好等于 r_i/r_o | 排除 z 在两端 1 µm 内的节点 |
| 5 | 3D 点云可读性差 | 只有散点 | 直接画节点 | 由四面体建 `UnstructuredGrid` → `extract_surface` + 半剖切 |
| 6 | 瞬态 `*TRANSIENT` 未生效 | 只算 1 步（TOT TIME=1 s） | `*INITIAL CONDITIONS` 放在步内 + 数据行未被采纳 | 未解决，见 §6 局限 |

**第 1 条是最有价值的**：如果没有解析解兜底，94.7 °C 这个结果"看起来也像个温度"，很容易被当成通过。

---

## 5. 2D / 3D 可视化

### 5.1 2D

| 图 | 内容 |
|---|---|
| `viz/thermal_2d.png` | 左：管壁温度沿轴向——FEA 点 vs 肋片解（含轴向导热）vs 逐段 1D；右：气体/内壁/外壁温度汇总 |

![温度场2D](../results/exhaust-pipe-gradient/viz/thermal_2d.png)

### 5.2 3D

| 图 | 内容 |
|---|---|
| `viz/thermal_3d.png` | 管外表面温度云图，入口 443 °C → 出口 327 °C |
| `viz/thermal_3d_cut.png` | 半剖切，可见壁厚方向的径向梯度 |

![温度场3D](../results/exhaust-pipe-gradient/viz/thermal_3d.png)

![半剖切](../results/exhaust-pipe-gradient/viz/thermal_3d_cut.png)

---

## 6. 局限与未解决项

| 项 | 状态 | 说明 |
|---|---|---|
| 气体温度 | 给定（线性 500→350 °C） | 没有做**共轭传热**（CFD + 固体耦合）；真实排气管需要先算气流温降 |
| 对流系数 h | 取工程值（h_i=100、h_o=10） | 没有按 Re/Pr 关联式计算；论文也没给可直接用的 h 分布 |
| 瞬态冷启动 | **未跑通** | CalculiX 2.23 没接受 `*TRANSIENT` 的 (Δt, 总时间) 数据行，只算 1 步；需要再查 `*HEAT TRANSFER` 的 `DELTMX` 用法 |
| 与论文数值对标 | 未做 | 论文是系统级时间曲线，没有逐点场数据；本报告改用精确解对标 |
| 辐射 | 未计入 | 高温排气管辐射不可忽略（ε≈0.9）；`*RADIATE` 未使用 |

---

## 7. 复现命令

```powershell
$py = ".venv\Scripts\python.exe"
$env:PATH = ".\msys\msys64\ucrt64\bin;" + $env:PATH

# 工况 A：均匀气温（解析解验证）
& $py scripts\thermal_pipe.py mesh --job results\exhaust-pipe-uniform --h 0.0025 --tgas-in 500 --tgas-out 500
Push-Location results\exhaust-pipe-uniform\thermal; ccx_i8.exe -i steady; Pop-Location
& $py scripts\thermal_pipe.py post --job results\exhaust-pipe-uniform

# 工况 B：轴向梯度
& $py scripts\thermal_pipe.py mesh --job results\exhaust-pipe-gradient --h 0.0025 --seg 10
Push-Location results\exhaust-pipe-gradient\thermal; ccx_i8.exe -i steady; Pop-Location
& $py scripts\thermal_pipe.py post --job results\exhaust-pipe-gradient
```

产物：`thermal/pipe.step`、`pipe_mesh.inp`、`steady.inp`、`steady.frd`、`result.json`、`viz/thermal_2d.png`、`viz/thermal_3d.png`、`viz/thermal_3d_cut.png`。
