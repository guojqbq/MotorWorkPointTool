# PMSM 性能分析工具｜需求与实现状态总表

> **文档性质**：持续维护的需求基线与实现追踪表（不是 `requirements.txt` 依赖文件）。  
> **仓库**：`guojqbq/MotorWorkPointTool`；**核对日期**：2026-11-02；**已检查版本**：v0.5.0（`VERSION.txt`，最近版本记录 2026-08-11）。  
> **范围**：PC 端 PMSM 性能计算、图形分析、效率/损耗估计、数据管理及 Windows 发布；**不包含** `MC_ScaleEV` 的 STM32/MESC 移植、VESC/VOFA 上位机及 `MC_RM108_Softswitch` 的继电器切换控制。  
> **来源**：此前用户讨论与要求、仓库现有 `PMSM性能分析工具软件需求说明.docx`、`README.md`、`README_用户说明.md`、`CHANGELOG.md`、`PROJECT_HANDOFF.md`、`models/`、`calculation/`、`ui/`、`services/`、`tests/`。
>
> **核对限制**：此表以主分支代码、文档与历史测试记录为依据，未在本次操作中实际启动 Windows GUI、重新运行全套测试或验证发布 ZIP。仓库内原有 Word 需求文件予以保留；本表以已知历史讨论和可读取的版本资料汇总，Word 文档尚需逐条复核是否存在未收录的原始需求。

## 1. 状态与优先级口径

- **已实现**：找到相应代码/界面/数据结构，且有文档或回归用例支撑；不代表本次重新通过测试。
- **部分实现**：有基础能力，但与完整工程需求仍有明确差距，或仅以理想化/估算模型覆盖。
- **未实现**：在 v0.5.0 仓库中没有找到目标功能的完整实现，或版本文档明确列为待办。
- **待验证**：历史诉求存在，但尚缺可复现验收证据；不等同于已完成。
- **P0**：影响物理正确性或主流程；**P1**：重要工程能力；**P2**：体验、扩展与交付增强。

按功能维度分组，每条保留稳定 ID；后续新增需求不重排已有 ID。状态更新时必须记录证据与日期。

## 2. 参数、物理模型和约束

| ID | 优先级 | 用户需求 / 验收口径 | v0.5.0 状态 | 实现依据与剩余工作 |
| --- | --- | --- | --- | --- |
| REQ-M01 | P0 | 输入 `Rs`、`Ld`、`Lq`、永磁体磁链 `ψf`、极对数、直流母线电压和最高转速；量纲明确 | **已实现** | `models/motor_parameters.py`、`ui/parameter_panel.py` |
| REQ-M02 | P0 | 示例默认参数：`Rs=0.0289 Ω`、`Ld=442 μH`、`Lq=1931 μH`、`ψf=0.161 Wb`、`p=3`、`Udc=844 V` | **已实现** | `models/motor_parameters.py`、`PROJECT_HANDOFF.md`；默认 `nmax=30000 rpm`、`Is_max=310 A` |
| REQ-M03 | P0 | 模式 A：`nmax + Tmax + Udc`；由指定最大转矩 MTPA 点反求等效电流限制 | **已实现** | `models/characteristic_input.py`、`calculation/characteristic_limit_resolver.py`、`tests/test_characteristic_input_modes.py` |
| REQ-M04 | P0 | 模式 B：`nmax + Is_max + Udc`；统一电流、电压和转速边界 | **已实现** | 同上；输入量应按“逆变器线电流/绕组电流峰值”定义严谨换算 |
| REQ-M05 | P0 | 支持峰值/RMS、SVPWM/SPWM、电压利用率和绕组接线换算，计算层使用 SI 单位 | **已实现** | `models/motor_parameters.py`、`models/winding_connection.py` |
| REQ-M06 | P0 | 可配置电流圆、电压极限、`Id` 下限及可选功率上限；求解与显示一致 | **已实现** | `calculation/constraint_curves.py`、`calculation/envelope_solver.py`、`tests/test_constraints.py` |
| REQ-M07 | P0 | 固定参数电感模型 `CONSTANT`，适用 IPMSM/SPMSM | **已实现** | `models/inductance_model.py`、`calculation/equations.py`、`tests/test_spmsm.py`、`tests/test_ipmsm.py` |
| REQ-M08 | P0 | 饱和参数 `SATURATION_MAP`：从 Excel 的 Ld、Lq Sheet 输入 `Ld(Id,Iq)`、`Lq(Id,Iq)`，包含格式样例、模板、预览和插值 | **已实现** | `services/saturation_map_io.py`、`models/saturation_map.py`、`ui/saturation_map_dialog.py`、`tests/test_saturation_and_connections.py`；双线性插值，范围外不外推 |
| REQ-M09 | P1 | 为后续磁饱和扩展预留 `ψf`/磁链变化模型，进一步支持 `Ψd(Id,Iq)`、`Ψq(Id,Iq)` 及差分电感 | **部分实现** | 目前仅 Ld/Lq 饱和、`ψf` 固定；磁链 Map 与差分电感**未实现**。详见 `CHANGELOG.md` Known Issues |
| REQ-M10 | P1 | 支持星接、角接、开绕组计算，明确线量/绕组量及母线约束 | **部分实现** | `models/winding_connection.py` 已实现三类连接、开绕组共母线/隔离母线/自定义双 Udc 的**理想电压、电流换算**；开绕组共模、零序、环流、实际调制边界未实现，不能视为完整双逆变器模型 |
| REQ-M11 | P1 | 电机参数修改后所有结果可追溯，旧结果不得被误当新参数结果 | **已实现** | 参数版本号、结果过期提示、任务取消和防止旧任务覆盖新结果；`ui/calculation_worker.py`、`ui/main_window.py` |
| REQ-M12 | P2 | 示例工作点 `Id=-193 A`、`Iq=241 A` 可用于复核 dq 方程与图形 | **待验证** | 历史讨论中的示例数值；未见单独的固定回归验收用例。可增加该输入的 `Te/Ud/Uq` 黄金向量测试 |

## 3. 外特性、MTPA/MTPV、内部工况

| ID | 优先级 | 用户需求 / 验收口径 | v0.5.0 状态 | 实现依据与剩余工作 |
| --- | --- | --- | --- | --- |
| REQ-C01 | P0 | 计算最大转矩—转速外包络，输出对应真实 `Id/Iq` 最优工作点 | **已实现** | `calculation/envelope_solver.py`；独立满足 `I/U/Id/P` 约束，不靠简单拼接轨迹 |
| REQ-C02 | P0 | 独立求解并显示理论 MTPA、MTPV、高速局部 MTPV、实际最优轨迹 | **已实现** | `calculation/reference_trajectories.py`、`ui/dq_plot.py` |
| REQ-C03 | P0 | 明确区分 MTPA、普通弱磁、MTPV 区域，颜色与工作点分类一致 | **已实现** | `calculation/operating_region_classifier.py`、`ui/plot_theme.py`；分类参考 dq 距离、电压激活而非仅 `Id<0` |
| REQ-C04 | P0 | 在转矩—转速平面计算二维内部工作点 Map；每个可行速度/目标转矩独立求 `Id/Iq` | **已实现** | `calculation/operating_map_solver.py`、`models/operating_map.py`；正式默认 81×121 |
| REQ-C05 | P1 | Map 网格点数和步长可配置；无效区域明确留白，不伪造可行数据 | **已实现** | `models/map_calculation_settings.py`、`calculation/operating_map_grid.py`、`ui/operating_map_plot.py` |
| REQ-C06 | P0 | dq 图展示电流圆、电压边界、恒转矩曲线、MTPA/MTPV、外特性轨迹与选中点 | **已实现** | `ui/dq_plot.py`、`ui/dq_curve_controls.py`；dq 轴等比例 |
| REQ-C07 | P0 | 点击外特性、内部 Map、dq 或数据表工作点，联动显示 `Id/Iq`、约束、损耗及局部轨迹 | **已实现** | `ui/main_window.py`、`ui/current_point_panel.py`、`tests/test_internal_point_interaction.py` |
| REQ-C08 | P1 | 饱和 Map 计算速度可接受，完整计算中界面保持响应且支持取消 | **已实现** | `benchmarks/results_v0.5.0.json` 和 `CHANGELOG.md`：历史同机 81×121 饱和计算约 27.44 s，固定电感约 1.8 s；该数据不是本次实测 |
| REQ-C09 | P1 | 大规模参数组合下的求解稳健性、边界可行性和结果可复现 | **部分实现** | 已有约束、诊断、性能测试和边界回退；历史 81×121 饱和 benchmark 保留 1 个原有不可行请求，尚需建立单独边界问题闭环 |

## 4. 损耗和效率

| ID | 优先级 | 用户需求 / 验收口径 | v0.5.0 状态 | 实现依据与剩余工作 |
| --- | --- | --- | --- | --- |
| REQ-E01 | P0 | 生成电机效率二维 Map，支持鼠标查看各工况数值、色条和可行边界 | **已实现** | `calculation/losses.py`、`ui/operating_map_plot.py`；仅为**电机效率估算** |
| REQ-E02 | P0 | 显示铜耗、可选铁耗、总损耗和 `Id/Iq`、电流/电压利用率 Map | **已实现** | `models/loss_model_parameters.py`、`ui/operating_map_plot.py` |
| REQ-E03 | P1 | 用绕组电阻/温度修正计算铜耗；铁耗系数可配置、未标定时注明估算 | **已实现** | `calculation/losses.py`、`README.md`；默认不把未经标定的铁耗当作实测 |
| REQ-E04 | P1 | 实现逆变器效率/损耗计算，考虑指定 IGBT 模块（历史提及 FZ900）、器件导通/开关损耗及工况依赖 | **未实现** | 本仓库有电机铜耗与经验铁耗，未见完整半导体器件/调制/温度损耗模型与逆变器效率 Map。需先冻结所选 FZ900 具体料号、曲线和开关条件 |
| REQ-E05 | P1 | 若计算系统总效率，需将电机效率与逆变器效率分别显示并合成，定义机械、杂散损耗口径 | **未实现** | 当前 `Efficiency` 为电机效率估计，**不等于驱动系统效率**；不得直接标为电驱总效率 |
| REQ-E06 | P1 | 将电机效率与真实台架或厂家数据对标，说明效率误差 | **待验证** | 现有回归以算法/一致性为主，未发现完整实测 Map 标定和误差报告 |

## 5. 界面、交互和视觉规范

| ID | 优先级 | 用户需求 / 验收口径 | v0.5.0 状态 | 实现依据与剩余工作 |
| --- | --- | --- | --- | --- |
| REQ-U01 | P1 | 工程桌面软件：电机参数、特性输入、高级设置折叠区域，曲线/内部 Map/案例对比区清晰 | **已实现** | `ui/parameter_panel.py`、`ui/main_window.py` |
| REQ-U02 | P1 | 外特性与 dq 主图接近 1:1 分屏，可手动拖拽比例 | **已实现** | `ui/main_window.py` 的水平 `QSplitter` |
| REQ-U03 | P1 | 软件启动时默认最大化 | **已实现** | `main.py` 中 `showMaximized()`；`tests/test_numeric_inputs_and_topbar.py` |
| REQ-U04 | P1 | 数值输入框禁用鼠标滚轮改值，同时保留表单正常滚动；不显示 SpinBox 上下箭头 | **已实现** | `ui/numeric_inputs.py` 与对应回归测试 |
| REQ-U05 | P1 | 外特性红、MTPA 蓝、弱磁绿、MTPV 橙，统一各图配色；效率热图连续高对比 | **已实现** | `ui/plot_theme.py`、`CHANGELOG.md` v0.3.0/v0.4.1 |
| REQ-U06 | P1 | 外特性、dq、Map 零轴明显加粗，普通网格淡化，图例合理避让 | **已实现** | `ui/torque_speed_plot.py`、`ui/dq_plot.py`、`ui/operating_map_plot.py` |
| REQ-U07 | P0 | 显示真实进度百分比、阶段、已算/总点数、耗时、取消；后台计算不冻界面 | **已实现** | 顶部固定操作栏，`ui/calculation_worker.py`；失败/取消恢复状态并尽量保留旧结果 |
| REQ-U08 | P1 | 参数变化不自动触发全量计算；明确“结果已过期”，用户手动开始/重算 | **已实现** | `ui/main_window.py`、`README.md` |
| REQ-U09 | P2 | 有自定义应用 Logo/图标，发布版视觉统一 | **未实现** | 仓库未见独立 Logo/图标资源及明确窗口图标配置；需要提供或设计素材并集成 EXE 图标 |
| REQ-U10 | P2 | 支持不同屏幕缩放，避免按钮遮挡或数值溢出 | **已实现（有历史验证）** | `PROJECT_HANDOFF.md` 记录 100%/125%/150% 截图无重叠；后续仍应在正式 Windows 发布环境复验 |

## 6. 保存、对比、导入导出和交付

| ID | 优先级 | 用户需求 / 验收口径 | v0.5.0 状态 | 实现依据与剩余工作 |
| --- | --- | --- | --- | --- |
| REQ-D01 | P0 | 保存/重新打开项目参数及配置，保持历史版本兼容 | **已实现** | `services/project_io.py`；当前 schema v1.4，对 major v1 兼容 |
| REQ-D02 | P1 | 将算好的外特性、内部 Map 作为“案例”保存、列出、加载、删除 | **已实现** | `services/case_repository.py`；案例存于 `cases/<name>/` |
| REQ-D03 | P1 | 多案例叠加外特性、dq 轨迹；展示效率 Map、效率差、转矩差 | **已实现** | `ui/case_comparison_widget.py`、`services/case_repository.py` |
| REQ-D04 | P1 | 不同转速/转矩网格的案例也能严格按同一物理工况比较 | **部分实现** | 目前仅直接比较共同坐标，**跨网格二维重采样**未实现；对比页面应明确“无共同网格”或限制 |
| REQ-D05 | P1 | 外特性 CSV、内部工况长表 CSV、矩阵 NPZ、Excel 多 Sheet 导出 | **已实现** | `services/export_service.py`、`tests/test_services.py` |
| REQ-D06 | P1 | 导出外特性/dq/内部 Map 的 PNG 图片；保持图形数据与计算层一致 | **已实现** | `ui/*plot.py`、`services/export_service.py` |
| REQ-D07 | P0 | 交付 Windows 可执行程序、完整发布包和交接文档，方便非 Python 用户启动 | **已实现（有历史构建记录）** | `build_exe.bat`、`build_release.ps1`、`PROJECT_HANDOFF.md`、`README_用户说明.md`；v0.5.0 历史 ZIP/EXE 构建及冒烟测试通过 |
| REQ-D08 | P1 | 发布时附版本号、完整测试、发布 ZIP、校验和/可复现构建信息 | **已实现（有历史构建记录）** | `build_release.ps1`、`tests/test_release_metadata.py`、`CHANGELOG.md` |
| REQ-D09 | P2 | 安装/发布文件代码签名，降低 Windows 信誉提示 | **未实现** | `PROJECT_HANDOFF.md` 明确发布包尚未签名 |
| REQ-D10 | P1 | 版本交接：维护变更记录、完成情况、已知问题、运行/构建/测试命令 | **已实现** | `CHANGELOG.md`、`PROJECT_HANDOFF.md`、`README_用户说明.md`；今后需同步更新本文件 |
| REQ-D11 | P1 | 所有物理方程、求解边界和 GUI 修改须有回归测试和可追溯结果 | **已实现（有历史测试）** | `tests/`；`PROJECT_HANDOFF.md` 记录 2026-08-11 开发/精简环境各 **151 passed**，但本次未重新运行 |

## 7. 关键已知限制与下一阶段建议

**产品边界必须清楚**：
1. **电机效率 Map ≠ 电驱系统效率 Map**；当前只估计绕组铜耗和可选经验铁耗，逆变器损耗需独立建模。
2. **饱和电感 Map ≠ 完整磁链 Map**；当前仍是固定 `ψf` 的 Ld/Lq 模型。
3. **开绕组双 Udc 换算 ≠ 完整开绕组电磁/调制模型**；尚缺共模、零序和环流等约束。
4. **已实现 ≠ 本次已验证**；v0.5.0 151 项测试和性能数据来自仓库保存的 2026-08-11 历史记录。
5. 原始 Word 需求说明已存在于根目录，此表不替代对其原条款的后续逐项核对。

建议按以下顺序推进（建议优先级，不代表用户已承诺开发）：

| 顺序 | 目标 | 关联需求 | 完成判据 |
| --- | --- | --- | --- |
| 1 | v0.5.0 重新验收及异常边界定位 | C09、D07、D11 | 本地全测、独立发布包冒烟、饱和 Map 原有不可行点分类与说明 |
| 2 | 逆变器效率模型需求细化 | E04、E05 | 确定器件料号、导通/开关损耗模型、开关频率、调制策略和热边界，并有基准测试 |
| 3 | 磁链 Map 模型扩展 | M09 | `Ψd/Ψq` 读入、插值、转矩和 dq 电压公式一致性及基准数据验证 |
| 4 | 完整开绕组约束 | M10 | 共母线/隔离母线、共模/环流约束和实际调制可行域分开建模验证 |
| 5 | 跨网格案例对比及台架标定 | D04、E06 | 两案例在共同坐标可比较且有明确插值/可行域规则；效率误差可量化 |
| 6 | 体验与交付收尾 | U09、D09 | 应用图标、Windows 发布版签名及缩放复验 |

## 8. 维护规则

1. 新增需求先分配下一个 `REQ-*` ID，记录**来源、验收标准、优先级、状态、证据路径**；不要仅把功能描述塞入 README。
2. **实现状态以提交的代码和可复现测试为准**。只有 UI 下拉框而没有物理模型时，不得标记“已实现”。
3. 功能更新时同步维护 `CHANGELOG.md` 和本表；每次发布更新版本、测试日期、数量及未解决问题。
4. 若修改单位、dq 定义、电压极限、绕组连接等物理口径，更新回归测试与示例数据。
5. 历史 Word 文件 `PMSM性能分析工具软件需求说明.docx` 保留为初始需求来源，本 Markdown 作为日常维护入口；若存在冲突，要保留差异并明确最终决策。
6. Windows 安装包之外的硬件调试、上位机通信、FOC 固件移植不应混进本仓库的需求完成率。

## 9. 证据索引

- [原始 Word 需求文件](../PMSM性能分析工具软件需求说明.docx)
- [版本及已知问题](../CHANGELOG.md)
- [工程交接、最近测试与 benchmark](../PROJECT_HANDOFF.md)
- [软件功能与计算口径](../README.md)
- [用户操作说明](../README_用户说明.md)
- [计算层](../calculation/) / [参数模型](../models/) / [UI](../ui/) / [服务](../services/) / [回归测试](../tests/)
- [性能基准结果](../benchmarks/results_v0.5.0.json)

**最后更新：2026-11-02。**
