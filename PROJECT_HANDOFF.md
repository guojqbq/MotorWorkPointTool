# PROJECT HANDOFF

## 项目目标

PySide6 桌面 PMSM 性能分析工具：外特性、内部工况 Map、dq 工作点、MTPA/MTPV、损耗效率、饱和电感、绕组接法、案例对比和工程导出。

## 当前版本号

`0.5.0`（2026-08-11）。

## 技术栈

Python 3.12、NumPy、Pandas、PySide6、PyQtGraph、OpenPyXL、PyInstaller。`calculation/` 不依赖 UI，内部使用 SI 单位、物理绕组相电流峰值和 dq 电压峰值。发布包使用内置有限一维优化器，不包 SciPy。

## 关键目录和入口文件

- `main.py`：入口及 `--smoke-test`。
- `calculation/`：方程、约束、外特性、Map、MTPA/MTPV、损耗、已求参考轨迹复用。
- `models/`：参数、饱和 Map、接法、统一限制和结果。
- `ui/`：主窗口、参数面板、图形、进度和案例对比。
- `services/`：JSON、Excel Map、案例仓库和导出。
- `tests/`：回归测试；`build_release.ps1`：独立精简环境发布。

## PMSM核心公式与单位约定

- `Te=1.5*p*(ψf*Iq+(Ld-Lq)*Id*Iq)`
- `Ud=Rs*Id-ωe*Lq*Iq`
- `Uq=Rs*Iq+ωe*(Ld*Id+ψf)`
- `Is=sqrt(Id²+Iq²)`，`Us=sqrt(Ud²+Uq²)`

饱和模式统一调用 `MotorParameters.inductances_h(Id,Iq)`；ψf 固定，Map 外返回 NaN，不外推。

## 默认参数

`p=3`，`Rs=0.0289 Ω`，`Ld=442 μH`，`Lq=1931 μH`，`ψf=0.161 Wb`，`Udc=844 V`，`nmax=30000 rpm`，`Is_max=310 A`；`CONSTANT + STAR`，正式 Map `81×121=9801`点，支持按点数/按 rpm、N·m 步长。

## 两种输入模式

- `UDC_TMAX_NMAX`：Tmax 的 MTPA 点反算绕组 Is_max。
- `UDC_IMAX_NMAX`：输入逆变器线电流，经接法/RMS 换算为绕组峰值。

后续求解器只读 `ResolvedCharacteristicLimits`。

## 当前数据格式

- 项目 JSON：schema v1.4，保持 major v1 兼容，可嵌入 Ld/Lq Map 和接线拓扑。
- 饱和 Excel：`Ld`/`Lq` Sheet，首行 Iq、首列 Id、默认 μH。
- 案例：`cases/<name>/case.json + external.csv + operating_points.npz`，包含参数、Map/hash、接法、限制、外特性、工作点、效率/损耗及 MTPA/MTPV 参考坐标。
- 导出：CSV、NPZ、Excel、PNG。

## MTPA/弱磁/MTPV分类规则

dq 距离按 Is_max 归一化；默认 MTPA 阈值 0.015、MTPV 0.020、电压激活 0.98。电压未激活且接近 MTPA 为 MTPA；电压激活且接近 MTPV 为 MTPV；其余电压激活点为普通弱磁。

## 当前已完成功能

CONSTANT/SATURATION_MAP、Ld/Lq Excel导入/模板/格式示例/高对比预览/缓存双线性插值、STAR/DELTA/OPEN_WINDING、两种Udc输入、外特性、内部独立定转矩Map、MTPA/MTPV、三色区域、效率/损耗、点击联动、固定顶部真实进度/取消/异常日志/结果过期、无滚轮数值输入、默认最大化、案例管理和全部工程导出。

## 本次修改内容

profiling后优化饱和求解：Map数组一次缓存、有效域分层一维搜索、32轮容差匹配二分、MTPA/MTPV批量预计算/缓存、跨转速和相邻转矩热启动、窄边界高密度回退。顶部固定操作栏；全部SpinBox禁滚轮/无箭头；默认最大化。物理方程、约束和正式网格未改；算法版本`operating-map-3.2`、外特性`envelope-2.2`。

## 未完成

Ψd/Ψq 磁链 Map、差分电感模型、开绕组共模/环流约束、异网格案例二维重采样、代码签名。

## 已知问题

benchmark饱和81×121有1个原有不可行请求；共母线开绕组为理想协调调制口径；案例A-B仅直接比较共同坐标；铁耗系数需实测标定；发布包未签名。

## 下一步建议

当前27 s正式饱和Map以NumPy批量运算和内存带宽为主，暂不并行以避免峰值内存和取消复杂度；下一步优先增加Ψd/Ψq Map和开绕组共模/环流模型。

## 测试和打包命令

- `\.venv\Scripts\python.exe -m pytest -q`
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1`
- `PMSMPerformanceTool.exe --smoke-test <输出目录>`

## 最近一次测试结果

2026-08-11：开发环境全测`151 passed in 16.74s`；独立精简发布环境全测`151 passed in 18.14s`，打包程序`--smoke-test`通过；100%/125%/150%缩放截图无控件重叠。

## 最近性能数据

同机v0.4.2→v0.5.0：饱和11×11总计6.23→0.88 s（7.12×）；饱和81×121外特性41.92→3.70 s、Map301.05→23.74 s、总计342.97→27.44 s（12.5×），平均/最大点30.72/43.30→2.42/3.17 ms，失败1→1。固定81×121约1.8 s不变。详见`benchmarks/results_v0.5.0.json`。

## 最近一次发布包位置和大小

`release/PMSM_Performance_Tool_v0.5.0/`：144,074,681 bytes（137.40 MiB）；`release/PMSM_Performance_Tool_v0.5.0.zip`：56,532,529 bytes（53.91 MiB）。最大文件为NumPy OpenBLAS运行库，20,495,360 bytes（19.55 MiB）。SHA256清单已生成，发布包不含源码、测试、Git、构建目录、缓存或虚拟环境。
