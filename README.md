# PMSM 性能分析工具 V0.2

面向 Windows 的本地 PMSM 外特性与内部工况分析软件。软件同时计算：

- 最大转矩—转速外包络及其实际最优 dq 工作轨迹；
- 独立数值求解的 MTPA 理论轨迹、MTPV 高速包络和当前转速局部 MTPV；
- 统一实际转矩轴上的二维工况 Map；
- 铜耗、可选铁耗估算、总电机损耗与电机效率估算 Map；
- 电流圆、当前转速电压极限、当前转矩恒转矩曲线及选中点。

实际外包络和内部工况点均由完整电流、电压、Id 下限及可选功率约束独立求解，不通过拼接 MTPA/MTPV 曲线生成。

## 内部工况 Map

正式 Map 默认使用所有转速共享的非均匀实际转矩轴；低转矩区、中间区域和外特性附近均有采样点。每个不超过当前 `Tmax` 的速度—目标转矩组合都会独立求解，并在固定转矩条件下最小化 `Id² + Iq²`。若 MTPA 点违反电压限制，求解器自动进入弱磁，并在高速区逐渐接近 MTPV。归一化转矩比例模式仅作为兼容选项保留。

计算只由用户点击“开始计算”或“重新计算”触发，默认全量网格为
81×121，用户可修改全量转速和转矩点数。参数编辑只执行校验，不会启动预览、定时器或后台任务；已有结果仍可查看，但外特性、Map 页签和状态栏会明确显示“结果已过期”。

所有完整计算均在后台线程运行。计算期间开始按钮禁用，并提供进度和取消按钮。任务带参数版本号；参数在计算期间发生变化时，旧任务结果不能覆盖新参数状态。色彩图变量、表格筛选、dq 内部散点显示等纯显示操作不会触发数值重算。

Map 可显示：

- 效率、总损耗、铜耗、铁耗估算；
- `Id`、`Iq`、电流幅值；
- 电压利用率、电流利用率。

外特性转矩—转速图和 dq 图均使用三组独立散点显示实际 MTPA、普通弱磁和实际 MTPV 工作点。分类由到理论轨迹的归一化距离、电压利用率和约束状态共同决定，不会用负 `Id` 直接判定弱磁。点击任一类别的内部点会通过同一个原始 `map_index` 同步更新两张图、MTPA/MTPV、电压极限、恒转矩曲线、损耗效率信息和内部数据表；点击左图内部空白区域时会按屏幕像素距离选择邻近有效点。

dq 内部点菜单提供“全部内部点”“当前转速轨迹”和“全部内部点 + 当前转速高亮”三种主要显示方式，程序接口仍保留当前转矩轨迹能力。低功率点即使效率为 `NaN`，仍保留完整 dq、电压、损耗、区域和索引数据。

## 外特性输入方式

界面支持两种 Udc 输入模式，且都会先转换成计算层统一使用的 `Umax`、`Is_max` 和 `nmax`：

- `Udc + Tmax + nmax`：根据 Udc、调制方式和电压利用系数换算 dq 电压上限；最大转矩点按数值 MTPA 求解，并将该点的电流幅值作为等效 `Is_max`。
- `Udc + Is_max + nmax`：根据 Udc 换算 dq 电压上限，用户输入直接解释为定子电流矢量幅值限制。

结果面板显示 Udc、最终 `Umax`、`Is_max`、最大转矩点 `Id/Iq`、基速和功率。目标转矩模式明确提示电流是依据目标最大转矩反算的等效限制。电流输入可选择峰值或 RMS；进入计算层前统一换算为相电流峰值。

左侧参数采用“电机参数、特性输入、高级设置”折叠分组；特性输入默认展开，高级设置默认折叠。两张主图使用可拖动水平分割器并以接近 1:1 的面积启动。dq 坐标锁定为等比例，电流圆始终显示为正圆；曲线和内部点开关集中在“显示选项”菜单中。

## 损耗与效率口径

内部统一使用 SI 单位、相电流峰值和 dq 相电压峰值。

铜耗：

```text
Pcu = 1.5 * Rs * (Id² + Iq²)
```

可选的绕组温度修正：

```text
Rs(T) = Rs_ref * (1 + copper_alpha * (T - T_ref))
```

磁链与电频率：

```text
Psi_d = Ld * Id + flux_pm
Psi_q = Lq * Iq
Psi_s = hypot(Psi_d, Psi_q)
f_e   = pole_pairs * speed_rpm / 60
```

三项铁耗经验模型：

```text
Pfe = Kh*f_e*Psi_s^alpha
    + Ke*f_e²*Psi_s²
    + Kex*f_e^1.5*Psi_s^1.5
```

也可选简化二项模型。铁耗系数被解释为全电机经验系数，必须通过实测损耗数据标定；因此铁耗默认关闭，软件和导出文件始终明确标记为“估算”。

效率：

```text
Pout = TorqueActual * omega_m
Efficiency = Pout / (Pout + Pcu + Pfe)
```

低于默认 100 W 输出阈值、零速或零转矩点的效率显示为空值。效率被限制在 `[0, 1]`。界面名称为“电机效率估算Map（铜耗+铁耗）”，不代表驱动系统效率，且不包含逆变器、机械和杂散损耗。

## dq 图轨迹

dq 图可分别开关并用不同线型显示：

- Current Limit；
- MTPA；
- MTPV；
- MTPV (Selected Speed)；
- Optimal Operating Trajectory；
- Voltage Limit；
- Constant Torque；
- Selected Point。

MTPA、MTPV 与实际轨迹使用独立数据。点击理论曲线只显示理论参考点，不会将其识别成实际运行点。

## 表格与导出

表格分为“外特性工作点”和“全部内部工况点”。内部表格支持转速、转矩范围、仅可行点、电流/电压约束、弱磁/MTPV 和效率范围筛选。

支持：

- 外特性 CSV；
- 内部工况长表 CSV；
- NPZ 矩阵：`SpeedGrid`、`TorqueGrid`、`IdMap`、`IqMap`、`EfficiencyMap`、`CopperLossMap`、`IronLossMap`、`FeasibleMask` 等；
- Excel：`Parameters`、`ExternalCharacteristic`、`InternalOperatingPoints`、`EfficiencyMap`、`CopperLossMap`、`IronLossMap`；
- 外特性、dq 和内部 Map PNG。

CSV、NPZ 和 Excel 均记录计算档位。当前界面只执行用户手动启动的全量计算；预览字段仅为兼容既有 V0.2 项目与程序化调用保留。

项目 JSON 格式仍属于 major version 1，当前保存为 schema 1.3，并记录 `input_mode`。旧 1.0–1.2 文件会自动迁移；历史 `iq_max` 会按原 MTPA 口径换算为等效电流矢量，历史 `Imax/Umax` 会转换为 Udc + Is_max 兼容模式。

## 安装与运行

建议使用 64 位 Python 3.11 或 3.12：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

项目提供旧版 1.0 兼容示例 `examples/ipmsm_parameters.json` 和 V0.2 完整项目示例 `examples/ipmsm_v02_project.json`。

## 自动测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

测试覆盖 SPMSM/IPMSM/`Ld≈Lq`、两种 Udc 输入模式、MTPA等效电流反算、dq 1:1 坐标、主图初始比例、折叠布局和显示菜单、MTPA/MTPV 最优性与独立数据、81×121 实际转矩 Map、运行区域分类、低效率点保留、手动后台计算、stale 标记、三类散点点击联动、JSON兼容及 CSV/NPZ/Excel 导出。

## 生成 Windows EXE

```powershell
.\build_exe.bat
```

输出：

```text
dist\PMSMPerformanceTool.exe
```

EXE 为无控制台窗口的本地程序。项目不包含代码签名证书。
