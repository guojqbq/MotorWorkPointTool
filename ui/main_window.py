"""Main desktop window and cross-view/realtime calculation coordination."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app_version import __version__
from calculation.operating_map_solver import OPERATING_MAP_ALGORITHM_VERSION
from models.analysis_result import AnalysisResult
from models.characteristic_input import CharacteristicInput
from models.characteristic_summary import CharacteristicSummary
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings
from models.motor_parameters import MotorParameters, ParameterValidationError
from models.resolved_characteristic_limits import ResolvedCharacteristicLimits
from services.export_service import (
    export_analysis_excel,
    export_operating_map_csv,
    export_operating_map_npz,
    export_operating_points_csv,
)
from services.project_io import load_project_with_characteristic, save_project
from services.saturation_map_io import load_ld_lq_workbook, write_ld_lq_template
from services.case_repository import (
    CaseRepository,
    SavedCase,
    default_cases_directory,
)
from ui.calculation_worker import CalculationErrorDetails, CalculationWorker
from ui.characteristic_summary_panel import CharacteristicSummaryPanel
from ui.current_point_panel import CurrentPointPanel
from ui.dq_curve_controls import DqCurveControls
from ui.dq_plot import DqPlot
from ui.map_index_utils import normalize_flat_index
from ui.operating_map_plot import OperatingMapPlot
from ui.operating_map_table import OperatingMapTable
from ui.operating_point_table import OperatingPointTable
from ui.parameter_panel import ParameterPanel
from ui.saturation_map_dialog import (
    SaturationMapFormatDialog,
    SaturationMapPreviewDialog,
)
from ui.case_comparison_widget import CaseComparisonWidget
from ui.case_selection_dialog import CaseSelectionDialog
from ui.styles import APP_STYLESHEET
from ui.torque_speed_plot import TorqueSpeedPlot


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _CalculationRequest:
    version: int
    profile: str
    force: bool
    cache_key: str
    parameters: MotorParameters
    characteristic_input: CharacteristicInput
    losses: LossModelParameters
    settings: MapCalculationSettings


class MainWindow(QMainWindow):
    def __init__(self, *, auto_calculate: bool = False, parent=None) -> None:
        super().__init__(parent)
        # Kept in the constructor for source compatibility only.  Calculations
        # are intentionally never started during window construction.
        _ = auto_calculate
        self.setWindowTitle(f"PMSM 性能分析工具 v{__version__}")
        self.resize(1600, 960)
        self.setMinimumSize(1150, 760)
        self.setStyleSheet(APP_STYLESHEET)

        self.parameter_panel = ParameterPanel()
        self.torque_speed_plot = TorqueSpeedPlot()
        self.operating_map_plot = OperatingMapPlot()
        self.case_comparison_widget = CaseComparisonWidget()
        self.dq_plot = DqPlot()
        self.dq_curve_controls = DqCurveControls()
        self.characteristic_summary_panel = CharacteristicSummaryPanel()
        self.current_point_panel = CurrentPointPanel()
        self.operating_point_table = OperatingPointTable()
        self.operating_map_table = OperatingMapTable()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximumWidth(230)
        self.progress_bar.setFormat("%p%")
        self.stage_label = QLabel("就绪")
        self.stage_label.setMinimumWidth(270)
        self.elapsed_label = QLabel("总耗时 00:00.0")
        self.elapsed_label.setMinimumWidth(110)

        dq_container = QFrame()
        dq_container.setProperty("role", "plotCard")
        dq_layout = QVBoxLayout(dq_container)
        dq_layout.setContentsMargins(6, 6, 6, 6)
        dq_layout.setSpacing(5)
        dq_toolbar = QHBoxLayout()
        dq_toolbar.setContentsMargins(0, 0, 2, 0)
        dq_title = QLabel("dq 电流平面")
        dq_title.setProperty("role", "cardTitle")
        dq_toolbar.addWidget(dq_title)
        dq_toolbar.addStretch(1)
        dq_toolbar.addWidget(self.dq_curve_controls)
        dq_layout.addLayout(dq_toolbar)
        dq_layout.addWidget(self.dq_plot, 1)
        self.dq_plot.setTitle("")

        self.view_tabs = QTabWidget()
        self.view_tabs.addTab(self.torque_speed_plot, "外特性")
        self.view_tabs.addTab(self.operating_map_plot, "内部工况 Map")
        self.view_tabs.addTab(self.case_comparison_widget, "案例对比")
        self.view_tabs.setTabVisible(2, False)
        left_plot_card = QFrame()
        left_plot_card.setProperty("role", "plotCard")
        left_plot_layout = QVBoxLayout(left_plot_card)
        left_plot_layout.setContentsMargins(6, 6, 6, 6)
        left_plot_layout.setSpacing(5)
        left_plot_layout.addWidget(self.view_tabs)

        self.plot_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.plot_splitter.setObjectName("mainPlotSplitter")
        self.plot_splitter.addWidget(left_plot_card)
        self.plot_splitter.addWidget(dq_container)
        self.plot_splitter.setStretchFactor(0, 1)
        self.plot_splitter.setStretchFactor(1, 1)
        self.plot_splitter.setSizes([700, 700])

        self.table_tabs = QTabWidget()
        self.table_tabs.addTab(self.operating_point_table, "外特性工作点")
        self.table_tabs.addTab(self.operating_map_table, "全部内部工况点")

        lower_panel = QWidget()
        lower_layout = QVBoxLayout(lower_panel)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.setSpacing(6)
        summary_row = QWidget()
        summary_layout = QHBoxLayout(summary_row)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(6)
        summary_layout.addWidget(self.characteristic_summary_panel, 1)
        summary_layout.addWidget(self.current_point_panel, 1)
        lower_layout.addWidget(summary_row, 0)
        lower_layout.addWidget(self.table_tabs, 1)

        self.content_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_splitter.setObjectName("contentVerticalSplitter")
        self.content_splitter.addWidget(self.plot_splitter)
        self.content_splitter.addWidget(lower_panel)
        self.content_splitter.setStretchFactor(0, 7)
        self.content_splitter.setStretchFactor(1, 3)
        self.content_splitter.setSizes([650, 280])

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.content_splitter, 1)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.addWidget(self.parameter_panel)
        self.main_splitter.addWidget(right_panel)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([340, 1260])
        central_widget = QWidget()
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        self.top_action_bar = self.parameter_panel.fixed_calculation_area
        central_layout.addWidget(self.top_action_bar, 0)
        central_layout.addWidget(self.main_splitter, 1)
        self.setCentralWidget(central_widget)
        self.statusBar().addPermanentWidget(self.stage_label, 1)
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().addPermanentWidget(self.elapsed_label)
        self.statusBar().showMessage("参数已就绪，请点击开始计算")

        self._dataframe = pd.DataFrame()
        self._analysis_result: AnalysisResult | None = None
        self._current_parameters: MotorParameters | None = None
        self._last_input_parameters: MotorParameters | None = None
        self._last_characteristic_input: CharacteristicInput | None = None
        self._last_losses: LossModelParameters | None = None
        self._last_settings: MapCalculationSettings | None = None
        self._thread: QThread | None = None
        self._worker: CalculationWorker | None = None
        self._active_request: _CalculationRequest | None = None
        self._cache: dict[str, AnalysisResult] = {}
        self._request_version = 1
        self._results_stale = False
        self._dirty = True
        self._last_map_diagnostics: dict[str, int | str] | None = None
        self._selected_map_index: int | None = None
        self._selecting = False
        self._close_when_finished = False
        self._calculation_started_at: float | None = None
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(200)
        self._elapsed_timer.timeout.connect(self._update_elapsed_display)
        self._case_repository = CaseRepository(default_cases_directory())
        self._comparison_cases: list[SavedCase] = []

        self._connect_signals()
        self.parameter_panel.set_export_enabled(False)
        self.parameter_panel.set_result_available(False)

    def _connect_signals(self) -> None:
        panel = self.parameter_panel
        panel.calculateRequested.connect(self.start_calculation)
        panel.cancelRequested.connect(self.cancel_calculation)
        panel.clearCacheRequested.connect(self.clear_cache)
        panel.parametersChanged.connect(self._parameters_changed)
        panel.displaySettingsChanged.connect(self._display_settings_changed)
        panel.restoreRequested.connect(self.restore_example)
        panel.saveRequested.connect(self.save_parameter_file)
        panel.loadRequested.connect(self.load_parameter_file)
        panel.exportCsvRequested.connect(self.export_csv)
        panel.exportMapCsvRequested.connect(self.export_map_csv)
        panel.exportNpzRequested.connect(self.export_npz)
        panel.exportExcelRequested.connect(self.export_excel)
        panel.exportImagesRequested.connect(self.export_images)
        panel.importSaturationRequested.connect(self.import_saturation_maps)
        panel.previewSaturationRequested.connect(self.preview_saturation_maps)
        panel.showSaturationFormatRequested.connect(
            self.show_saturation_map_format
        )
        panel.exportSaturationTemplateRequested.connect(
            self.export_saturation_template
        )
        panel.saveCaseRequested.connect(self.save_current_case)
        panel.loadCaseRequested.connect(self.load_saved_case)
        panel.deleteCaseRequested.connect(self.delete_saved_case)
        panel.compareCasesRequested.connect(self.compare_saved_cases)
        panel.exitRequested.connect(self.close)
        self.torque_speed_plot.pointSelected.connect(self.select_point)
        self.torque_speed_plot.internalPointSelected.connect(
            self.select_operating_point
        )
        self.dq_plot.pointSelected.connect(self.select_point)
        self.dq_plot.internalPointSelected.connect(self.select_operating_point)
        self.dq_plot.referencePointSelected.connect(self.show_reference_point)
        self.dq_curve_controls.curveVisibilityChanged.connect(
            self.dq_plot.set_curve_visible
        )
        self.dq_curve_controls.operatingPointDisplayModeChanged.connect(
            self.dq_plot.set_internal_display_mode
        )
        self.dq_curve_controls.internalPointsVisibilityChanged.connect(
            self.dq_plot.set_internal_points_visible
        )
        self.dq_curve_controls.currentSpeedHighlightChanged.connect(
            self.dq_plot.set_current_speed_highlight_visible
        )
        self.operating_point_table.pointSelected.connect(self.select_point)
        self.operating_map_plot.pointSelected.connect(
            self.select_operating_point
        )
        self.operating_map_table.pointSelected.connect(
            self.select_operating_point
        )

    def import_saturation_maps(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入 Ld/Lq 饱和电感工作簿",
            "",
            "Excel 工作簿 (*.xlsx *.xlsm)",
        )
        if not path:
            return
        try:
            ld_map, lq_map = load_ld_lq_workbook(
                path,
                unit=self.parameter_panel.inductance_map_unit.currentText(),
            )
            self.parameter_panel.set_saturation_maps(ld_map, lq_map)
        except Exception as exc:
            self._show_error("饱和电感 Map 导入失败", str(exc))
            return
        self.statusBar().showMessage(
            f"Ld/Lq 饱和 Map 已导入：{Path(path).name}；请点击开始计算",
            6000,
        )

    def preview_saturation_maps(self) -> None:
        ld_map, lq_map = self.parameter_panel.saturation_maps()
        if ld_map is None or lq_map is None:
            self._show_error("没有可预览数据", "请先导入包含 Ld、Lq 工作表的 Excel。")
            return
        dialog = SaturationMapPreviewDialog(ld_map, lq_map, self)
        dialog.exec()

    def show_saturation_map_format(self) -> None:
        dialog = SaturationMapFormatDialog(
            self.parameter_panel.inductance_map_unit.currentText(), self
        )
        dialog.exec()

    def export_saturation_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 Ld/Lq Excel 模板",
            "Ld_Lq饱和电感模板.xlsx",
            "Excel 工作簿 (*.xlsx)",
        )
        if not path:
            return
        try:
            target = write_ld_lq_template(path)
        except Exception as exc:
            self._show_error("模板导出失败", str(exc))
            return
        QMessageBox.information(
            self,
            "模板已生成",
            f"已生成空白 Ld/Lq 模板：\n{target}",
        )

    def save_current_case(self) -> None:
        if (
            self._analysis_result is None
            or self._last_input_parameters is None
            or self._last_characteristic_input is None
            or self._last_losses is None
            or self._last_settings is None
        ):
            self._show_error("无法保存案例", "请先完成一次正式计算。")
            return
        name, accepted = QInputDialog.getText(self, "保存当前案例", "案例名称：")
        if not accepted or not name.strip():
            return
        note, accepted = QInputDialog.getMultiLineText(
            self, "案例备注", "备注（可留空）：", ""
        )
        if not accepted:
            return
        try:
            target = self._case_repository.save(
                name,
                note,
                self._last_input_parameters,
                self._last_characteristic_input,
                self._last_losses,
                self._last_settings,
                self._analysis_result,
            )
        except Exception as exc:
            self._show_error("案例保存失败", str(exc))
            return
        self.statusBar().showMessage(f"案例已保存：{target}", 6000)

    def _select_case_names(self, *, multiple: bool, title: str) -> list[str]:
        names = self._case_repository.list_cases()
        if not names:
            self._show_error("没有已保存案例", "请先完成计算并保存当前案例。")
            return []
        dialog = CaseSelectionDialog(
            names, multiple=multiple, title=title, parent=self
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return []
        return dialog.selected_names()

    def _display_comparison_cases(self, cases: list[SavedCase]) -> None:
        self._comparison_cases = list(cases)
        self.torque_speed_plot.set_comparison_cases(cases)
        self.dq_plot.set_comparison_cases(cases)
        self.case_comparison_widget.set_cases(cases)
        self.view_tabs.setTabVisible(2, bool(cases))

    def load_saved_case(self) -> None:
        names = self._select_case_names(multiple=False, title="加载案例")
        if not names:
            return
        try:
            case = self._case_repository.load(names[0])
        except Exception as exc:
            self._show_error("案例加载失败", str(exc))
            return
        self._display_comparison_cases([case])
        self.view_tabs.setCurrentIndex(0)
        self.statusBar().showMessage(
            f"案例已加载并叠加：{case.legend_label}", 6000
        )

    def delete_saved_case(self) -> None:
        names = self._select_case_names(multiple=False, title="删除案例")
        if not names:
            return
        answer = QMessageBox.question(
            self,
            "确认删除案例",
            f"确定删除案例“{names[0]}”吗？此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._case_repository.delete(names[0])
        except Exception as exc:
            self._show_error("案例删除失败", str(exc))
            return
        self.statusBar().showMessage(f"案例已删除：{names[0]}", 5000)

    def compare_saved_cases(self) -> None:
        names = self._select_case_names(multiple=True, title="多选案例对比")
        if len(names) < 2:
            if names:
                self._show_error("案例数量不足", "多选对比至少需要两个案例。")
            return
        try:
            cases = [self._case_repository.load(name) for name in names]
        except Exception as exc:
            self._show_error("案例对比加载失败", str(exc))
            return
        self._display_comparison_cases(cases)
        self.view_tabs.setCurrentIndex(2)
        self.statusBar().showMessage(f"正在对比 {len(cases)} 个案例", 5000)

    @staticmethod
    def _cache_key(
        parameters: MotorParameters,
        losses: LossModelParameters,
        settings: MapCalculationSettings,
        profile: str,
        characteristic_input: CharacteristicInput | None = None,
    ) -> str:
        characteristic = characteristic_input
        motor_values = parameters.as_input_dict()
        for legacy_constraint_field in (
            "Udc",
            "Imax",
            "max_speed_rpm",
        ):
            motor_values.pop(legacy_constraint_field, None)
        payload = {
            "motor": motor_values,
            "characteristic": (
                characteristic.calculation_dict()
                if characteristic is not None
                else {
                    "input_mode": "LEGACY",
                    "Umax": parameters.umax_v,
                    "Is_max": parameters.imax_peak_a,
                    "speed_scan_max": parameters.max_speed_rpm,
                }
            ),
            "loss": losses.as_dict(),
            "map": settings.calculation_dict(),
            "profile": profile,
            "algorithm": OPERATING_MAP_ALGORITHM_VERSION,
            "external_algorithm": "envelope-2.2",
        }
        serialized = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _build_request(
        self, profile: str, *, force: bool = False
    ) -> _CalculationRequest | None:
        try:
            parameters = self.parameter_panel.parameters()
            characteristic_input = (
                self.parameter_panel.characteristic_input()
            )
            losses = self.parameter_panel.loss_parameters()
            settings = self.parameter_panel.map_settings()
        except (ParameterValidationError, ValueError) as exc:
            errors = getattr(exc, "errors", None)
            self._show_error(
                "参数输入错误", "\n".join(errors) if errors else str(exc)
            )
            return None
        return _CalculationRequest(
            version=self._request_version,
            profile=profile,
            force=force,
            cache_key=self._cache_key(
                parameters,
                losses,
                settings,
                profile,
                characteristic_input,
            ),
            parameters=parameters,
            characteristic_input=characteristic_input,
            losses=losses,
            settings=settings,
        )

    def start_calculation(self) -> None:
        """Start exactly one full-resolution calculation after a user action."""

        self._queue_calculation("full", force=True)

    def _queue_calculation(self, profile: str, *, force: bool = False) -> None:
        request = self._build_request(profile, force=force)
        if request is None:
            return
        if not force and request.cache_key in self._cache:
            self._apply_analysis_result(
                request.version, self._cache[request.cache_key]
            )
            return
        if self._thread is not None and self._thread.isRunning():
            self.statusBar().showMessage("计算正在进行，请等待或点击取消")
            return
        self._start_request(request)

    def _start_request(self, request: _CalculationRequest) -> None:
        if request.version != self._request_version:
            return
        self.parameter_panel.set_calculating(True)
        self.parameter_panel.start_progress()
        self.progress_bar.setValue(0)
        self.stage_label.setText("正在准备计算…")
        self.elapsed_label.setText("总耗时 00:00.0")
        self.statusBar().showMessage("正在后台计算外特性和内部工作点 Map…")

        thread = QThread(self)
        worker = CalculationWorker(
            request.parameters,
            request.losses,
            request.settings,
            request.profile,
            request.version,
            request.cache_key,
            request.characteristic_input,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._calculation_progress)
        worker.stage.connect(self._calculation_stage)
        worker.finished.connect(self._calculation_finished)
        worker.failed.connect(self._calculation_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._thread = thread
        self._worker = worker
        self._active_request = request
        self._calculation_started_at = perf_counter()
        self._elapsed_timer.start()
        thread.start()

    def _parameters_changed(self) -> None:
        self._request_version += 1
        try:
            self.parameter_panel.parameters()
            self.parameter_panel.characteristic_input()
            self.parameter_panel.loss_parameters()
            self.parameter_panel.map_settings()
        except (ParameterValidationError, ValueError) as exc:
            self._dirty = True
            self._set_results_stale(self._analysis_result is not None)
            self.statusBar().showMessage(
                f"参数无效：{str(exc).splitlines()[0]}；旧结果已过期"
            )
            self.parameter_panel.set_action_status(
                "参数无效，结果已过期", state="stale"
            )
            return
        self._dirty = True
        self._set_results_stale(self._analysis_result is not None)
        self.statusBar().showMessage("参数已修改，请点击开始计算")
        self.parameter_panel.set_action_status(
            "参数已修改，结果已过期", state="stale"
        )

    def _set_results_stale(self, stale: bool) -> None:
        self._results_stale = bool(stale)
        suffix = "（结果已过期）" if self._results_stale else ""
        self.view_tabs.setTabText(0, f"外特性{suffix}")
        self.view_tabs.setTabText(1, f"内部工况 Map{suffix}")
        self.operating_map_plot.set_stale(self._results_stale)

    def _display_settings_changed(self) -> None:
        try:
            visible = self.parameter_panel.map_settings().show_internal_points_in_dq
        except ValueError:
            return
        self.dq_plot.set_internal_points_visible(visible)
        self.statusBar().showMessage("显示设置已更新；数值缓存保持有效", 3000)

    def cancel_calculation(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.requestInterruption()
            self.statusBar().showMessage("正在取消当前计算…")
        else:
            self.statusBar().showMessage("当前没有运行中的计算", 3000)

    def clear_cache(self) -> None:
        count = len(self._cache)
        self._cache.clear()
        self.statusBar().showMessage(f"已清除 {count} 个计算缓存结果", 3000)

    def restore_example(self) -> None:
        self.parameter_panel.set_all_settings(
            MotorParameters.example_ipmsm(),
            LossModelParameters(),
            MapCalculationSettings(),
        )
        self._parameters_changed()
        self.statusBar().showMessage(
            "已恢复 IPMSM 示例参数，请点击开始计算"
        )

    def select_point(self, index: int) -> None:
        if self._selecting or not 0 <= index < len(self._dataframe):
            return
        self._selecting = True
        try:
            self._selected_map_index = None
            self.torque_speed_plot.set_selected_index(index)
            self.dq_plot.set_selected_index(index)
            self.operating_point_table.select_index(index)
            self.current_point_panel.set_record(self._dataframe.iloc[index])
            row = self._dataframe.iloc[index]
            self.statusBar().showMessage(
                f"外特性点：{row['Speed_rpm']:.1f} rpm；"
                f"{row['Region']}；约束 {row['ActiveConstraint']}"
            )
        finally:
            self._selecting = False

    def select_operating_point(
        self, map_index: object | None, *, update_status: bool = True
    ) -> None:
        if map_index is None:
            return
        flat_index = normalize_flat_index(map_index)
        if self._selecting or self._analysis_result is None:
            return
        result = self._analysis_result.operating_map
        if not 0 <= flat_index < len(result.dataframe):
            return
        row = result.point_by_map_index(flat_index)
        if not bool(row["IsFeasible"]):
            return
        self._selecting = True
        try:
            self._selected_map_index = flat_index
            self.torque_speed_plot.set_selected_map_index(flat_index)
            self.operating_map_plot.set_selected_map_index(flat_index)
            self.dq_plot.set_selected_map_index(flat_index)
            self.operating_map_table.select_map_index(flat_index)
            self.current_point_panel.set_record(row)
            efficiency = float(row["Efficiency"])
            efficiency_text = (
                f"{efficiency * 100.0:.2f}%"
                if np.isfinite(efficiency)
                else "—"
            )
            if update_status:
                stale_text = "；结果已过期" if self._results_stale else ""
                self.statusBar().showMessage(
                    f"内部工况点：{row['Speed_rpm']:.1f} rpm，"
                    f"{row['TorqueActual_Nm']:.3f} N·m，效率估算 {efficiency_text}；"
                    f"{row['ControlRegion']} / {row['ActiveConstraint']}"
                    f"{stale_text}"
                )
        finally:
            self._selecting = False

    def select_map_point(self, speed_index: int, torque_index: int) -> None:
        """Compatibility wrapper; all internal selection uses one map index."""

        if self._analysis_result is None:
            return
        map_index = self._analysis_result.operating_map.flat_index(
            speed_index, torque_index
        )
        self.select_operating_point(map_index)

    def show_reference_point(self, kind: str, record: dict) -> None:
        self.current_point_panel.set_reference_point(kind, record)
        speed = record.get("Speed_rpm")
        speed_text = ""
        try:
            if pd.notna(speed):
                speed_text = f"，{float(speed):.1f} rpm"
        except (TypeError, ValueError):
            pass
        self.statusBar().showMessage(
            f"{kind}理论参考点{speed_text}；未改变实际工作点选择"
        )

    def save_parameter_file(self) -> None:
        try:
            parameters = self.parameter_panel.parameters()
            characteristic_input = (
                self.parameter_panel.characteristic_input()
            )
            losses = self.parameter_panel.loss_parameters()
            settings = self.parameter_panel.map_settings()
        except (ParameterValidationError, ValueError) as exc:
            self._show_error("无法保存项目", str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 PMSM 分析项目", "pmsm_analysis.json", "JSON 项目 (*.json)"
        )
        if not path:
            return
        try:
            save_project(
                parameters,
                losses,
                settings,
                path,
                characteristic_input=characteristic_input,
            )
        except Exception as exc:
            self._show_error("保存失败", str(exc))
            return
        self.statusBar().showMessage(f"项目已保存：{path}", 5000)

    def load_parameter_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "加载 PMSM 分析项目", "", "JSON 项目 (*.json)"
        )
        if not path:
            return
        try:
            parameters, losses, settings, characteristic_input = (
                load_project_with_characteristic(path)
            )
        except (OSError, ParameterValidationError, ValueError) as exc:
            self._show_error("加载失败", str(exc))
            return
        self.parameter_panel.set_all_settings(
            parameters, losses, settings, characteristic_input
        )
        self._parameters_changed()
        self.statusBar().showMessage(
            f"项目已加载：{path}；请点击开始计算"
        )

    def export_csv(self) -> None:
        if self._dataframe.empty:
            self._show_error("没有可导出数据", "请先完成计算。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出外特性工作点",
            "pmsm_external_characteristic.csv",
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        try:
            export_operating_points_csv(self._dataframe, path)
        except Exception as exc:
            self._show_error("CSV 导出失败", str(exc))
            return
        self.statusBar().showMessage(f"外特性 CSV 已导出：{path}", 5000)

    def export_map_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出内部工况长表",
            "pmsm_internal_operating_points.csv",
            "CSV 文件 (*.csv)",
        )
        if path:
            self._prepare_map_export("csv", path)

    def export_npz(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 Map 数组",
            "pmsm_operating_map.npz",
            "NumPy 压缩数组 (*.npz)",
        )
        if path:
            self._prepare_map_export("npz", path)

    def export_excel(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出完整分析工作簿",
            "pmsm_analysis.xlsx",
            "Excel 工作簿 (*.xlsx)",
        )
        if path:
            self._prepare_map_export("excel", path)

    def _prepare_map_export(self, kind: str, path: str) -> None:
        if self._analysis_result is None:
            self._show_error("没有可导出数据", "请先完成计算。")
            return
        if self._analysis_result.profile == "preview":
            answer = QMessageBox.question(
                self,
                "当前为预览结果",
                "当前只有低分辨率预览 Map。\n"
                "选择“是”导出并明确标记为预览；选择“否”返回，"
                "请点击重新计算生成全量结果。",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.No:
                self.statusBar().showMessage(
                    "未导出预览结果；请点击重新计算生成全量结果"
                )
                return
        self._perform_map_export(kind, path)

    def _perform_map_export(self, kind: str, path: str) -> None:
        if self._analysis_result is None:
            return
        result = self._analysis_result.operating_map
        try:
            if kind == "csv":
                export_operating_map_csv(result, path)
            elif kind == "npz":
                export_operating_map_npz(result, path)
            elif kind == "excel":
                if (
                    self._last_input_parameters is None
                    or self._last_losses is None
                    or self._last_settings is None
                ):
                    raise RuntimeError("缺少与结果对应的参数快照。")
                export_analysis_excel(
                    self._last_input_parameters,
                    self._last_losses,
                    self._last_settings,
                    result,
                    path,
                    characteristic_input=self._last_characteristic_input,
                    resolved_limits=self._analysis_result.resolved_limits,
                )
            else:
                raise ValueError(f"未知导出类型：{kind}")
        except Exception as exc:
            self._show_error("Map 导出失败", str(exc))
            return
        profile_text = "预览" if result.is_preview else "全量"
        self.statusBar().showMessage(
            f"{profile_text} Map 已导出：{path}", 5000
        )

    def export_images(self) -> None:
        if self._dataframe.empty:
            self._show_error("没有可导出图形", "请先完成计算。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "选择图片文件名前缀", "pmsm_analysis.png", "PNG 图片 (*.png)"
        )
        if not path:
            return
        base = Path(path)
        if base.suffix.lower() == ".png":
            base = base.with_suffix("")
        torque_path = str(base) + "_torque_speed.png"
        dq_path = str(base) + "_dq.png"
        map_path = str(base) + "_operating_map.png"
        try:
            self.torque_speed_plot.export_png(torque_path)
            self.dq_plot.export_png(dq_path)
            if self._analysis_result is not None:
                self.operating_map_plot.export_png(map_path)
        except Exception as exc:
            self._show_error("图片导出失败", str(exc))
            return
        QMessageBox.information(
            self,
            "导出完成",
            f"已生成：\n{torque_path}\n{dq_path}\n{map_path}",
        )

    def _calculation_progress(self, version: int, progress: int) -> None:
        if version == self._request_version:
            self.progress_bar.setValue(progress)
            self.parameter_panel.update_progress(progress)

    def _update_elapsed_display(self) -> None:
        if self._calculation_started_at is None:
            return
        elapsed = max(0.0, perf_counter() - self._calculation_started_at)
        minutes = int(elapsed // 60.0)
        seconds = elapsed - 60.0 * minutes
        self.elapsed_label.setText(
            f"总耗时 {minutes:02d}:{seconds:04.1f}"
        )
        self.parameter_panel.update_progress_elapsed(elapsed)

    def _calculation_stage(
        self, version: int, stage: str, completed: int, total: int
    ) -> None:
        if version != self._request_version:
            return
        self.parameter_panel.update_progress_stage(stage, completed, total)
        if total > 0:
            percent = min(100.0, max(0.0, 100.0 * completed / total))
            if stage == "内部 Map":
                text = (
                    f"正在计算内部工况 {completed}/{total} "
                    f"（{percent:.0f}%）"
                )
            else:
                text = f"{stage}：{completed}/{total}（{percent:.0f}%）"
            self.stage_label.setText(text)
            self.statusBar().showMessage(
                text
            )
        else:
            self.stage_label.setText(stage)
            self.statusBar().showMessage(stage)

    def _calculation_finished(self, version_or_parameters, result) -> None:
        """Apply versioned results; retain the old test/integration entry point."""

        if isinstance(version_or_parameters, MotorParameters) and isinstance(
            result, pd.DataFrame
        ):
            self._apply_legacy_result(version_or_parameters, result)
            return
        version = int(version_or_parameters)
        if not isinstance(result, AnalysisResult):
            return
        diagnostics = result.operating_map.diagnostics()
        self._last_map_diagnostics = diagnostics
        LOGGER.info(
            "Operating map: profile=%s speed=%d torque=%d total=%d "
            "feasible=%d nonzero_torque=%d solver_failed=%d",
            diagnostics["profile"],
            diagnostics["speed_points"],
            diagnostics["torque_points"],
            diagnostics["total_points"],
            diagnostics["feasible_points"],
            diagnostics["nonzero_torque_points"],
            diagnostics["solver_failed_points"],
        )
        self._cache[result.cache_key] = result
        self._apply_analysis_result(version, result)

    def _apply_analysis_result(
        self, version: int, result: AnalysisResult
    ) -> None:
        if version != self._request_version:
            return
        drawing_started = perf_counter()
        self.parameter_panel.update_progress_stage("绘图刷新", 0, 1)
        self.parameter_panel.update_progress(98)
        self.statusBar().showMessage("绘图刷新：0/1")
        request = self._active_request
        if request is None:
            try:
                input_parameters = self.parameter_panel.parameters()
                characteristic_input = (
                    self.parameter_panel.characteristic_input()
                )
                losses = self.parameter_panel.loss_parameters()
                settings = self.parameter_panel.map_settings()
            except Exception:
                return
        elif request is not None and request.version == version:
            input_parameters = request.parameters
            characteristic_input = request.characteristic_input
            losses = request.losses
            settings = request.settings
        else:
            try:
                input_parameters = self.parameter_panel.parameters()
                characteristic_input = (
                    self.parameter_panel.characteristic_input()
                )
                losses = self.parameter_panel.loss_parameters()
                settings = self.parameter_panel.map_settings()
            except Exception:
                return

        diagnostics = result.operating_map.diagnostics()
        self._last_map_diagnostics = diagnostics

        if int(diagnostics["feasible_points"]) == 0:
            self.progress_bar.setValue(0)
            self._dirty = True
            self._set_results_stale(True)
            message = (
                "内部工作点 Map 没有任何可行点。请检查电压、电流、"
                "Id 下限和功率约束。"
            )
            self._show_error("内部 Map 求解失败", message)
            self.statusBar().showMessage(message)
            elapsed = (
                perf_counter() - self._calculation_started_at
                if self._calculation_started_at is not None
                else 0.0
            )
            self.parameter_panel.finish_progress("failed", elapsed)
            return

        # Save only a complete, feasible result.  Failed/cancelled work never
        # replaces the last complete analysis visible in the GUI.
        self._analysis_result = result
        self._current_parameters = result.calculation_parameters
        self._last_input_parameters = input_parameters
        self._last_characteristic_input = characteristic_input
        self._last_losses = losses
        self._last_settings = settings

        # 2. Update the external envelope and its independent internal scatter.
        self._dataframe = result.external_characteristic.reset_index(drop=True)
        self.torque_speed_plot.set_dataframe(self._dataframe)
        self.torque_speed_plot.set_operating_map(result.operating_map)

        # 3. Update the color operating map.
        self.operating_map_plot.set_result(result.operating_map)

        # 4. Update dq references, external trajectory, and internal scatter.
        resolved_limits = (
            result.resolved_limits
            or ResolvedCharacteristicLimits.from_legacy_motor(
                result.calculation_parameters
            )
        )
        summary = (
            result.characteristic_summary
            or CharacteristicSummary.from_external_characteristic(
                self._dataframe, resolved_limits
            )
        )
        self.dq_plot.set_results(
            result.calculation_parameters,
            self._dataframe,
            resolved_limits,
            mtpa_dataframe=result.mtpa_trajectory,
            mtpv_dataframe=result.mtpv_envelope,
        )
        self.dq_plot.set_operating_map(result.operating_map, visible=True)
        self.characteristic_summary_panel.set_result(
            resolved_limits, summary
        )
        diagnostics["left_drawn_points"] = (
            self.torque_speed_plot.internal_point_count
        )
        diagnostics["dq_drawn_points"] = self.dq_plot.internal_point_count
        diagnostics["display_thinned_points"] = (
            int(diagnostics["feasible_points"])
            - self.dq_plot.displayed_internal_point_count
        )
        self._last_map_diagnostics = diagnostics
        for label, key in (
            ("MTPA", "mtpa_points"),
            ("普通弱磁", "field_weakening_points"),
            ("MTPV", "mtpv_points"),
        ):
            if int(diagnostics[key]) == 0:
                LOGGER.warning(
                    "Operating map has zero %s points; check limits, "
                    "speed range, reference validity, and region tolerances.",
                    label,
                )

        # 5. Update both result tables.
        self.operating_point_table.set_dataframe(self._dataframe)
        self.operating_map_table.set_result(result.operating_map)

        self.parameter_panel.set_export_enabled(True)
        self.parameter_panel.set_result_available(True)
        self.progress_bar.setValue(100)
        self.stage_label.setText("计算完成")
        self._dirty = False
        self._set_results_stale(False)

        # 6-8. Select a feasible non-zero point around 50% speed and 50% of
        # the local maximum torque, then update every linked view.
        map_index = self._default_internal_map_index(result.operating_map)
        self.select_operating_point(map_index, update_status=False)

        # 9. Only now publish the final complete state.
        self.statusBar().showMessage(
            "计算完成："
            f"{diagnostics['speed_points']}×{diagnostics['torque_points']}，"
            f"总点数 {diagnostics['total_points']}，"
            f"可行点 {diagnostics['feasible_points']}，"
            f"MTPA {diagnostics['mtpa_points']}，"
            f"弱磁 {diagnostics['field_weakening_points']}，"
            f"MTPV {diagnostics['mtpv_points']}，"
            f"OTHER {diagnostics['other_points']}，"
            f"求解失败 {diagnostics['solver_failed_points']}"
        )
        drawing_elapsed = perf_counter() - drawing_started
        total_elapsed = (
            perf_counter() - self._calculation_started_at
            if self._calculation_started_at is not None
            else float("nan")
        )
        LOGGER.info(
            "绘图刷新耗时 %.3f s，含 GUI 刷新总耗时 %.3f s",
            drawing_elapsed,
            total_elapsed,
        )
        self._update_elapsed_display()
        self.parameter_panel.update_progress_stage("绘图刷新", 1, 1)
        self.parameter_panel.finish_progress("completed", total_elapsed)
        QTimer.singleShot(
            5000, self.parameter_panel.hide_completed_progress
        )
        self._elapsed_timer.stop()
        self._calculation_started_at = None

    @staticmethod
    def _default_internal_map_index(operating_map) -> int:
        target_speed_index = int(
            np.argmin(
                np.abs(
                    operating_map.speed_grid_rpm
                    - 0.5 * float(np.nanmax(operating_map.speed_grid_rpm))
                )
            )
        )
        target_torque = 0.5 * float(
            operating_map.maximum_torque_nm[target_speed_index]
        )
        row_start = operating_map.flat_index(target_speed_index, 0)
        row_end = row_start + operating_map.shape[1]
        row = operating_map.dataframe.iloc[row_start:row_end]
        valid = (
            row["IsFeasible"].to_numpy(dtype=bool)
            & np.isfinite(row["TorqueActual_Nm"].to_numpy(dtype=float))
            & (row["TorqueActual_Nm"].to_numpy(dtype=float) > 1e-9)
        )
        if np.any(valid):
            local_positions = np.flatnonzero(valid)
            torque = row["TorqueActual_Nm"].to_numpy(dtype=float)[valid]
            local_index = int(
                local_positions[int(np.argmin(np.abs(torque - target_torque)))]
            )
            return row_start + local_index
        feasible = operating_map.feasible_map_indices()
        nonzero = operating_map.dataframe.iloc[feasible][
            "TorqueActual_Nm"
        ].to_numpy(dtype=float) > 1e-9
        candidates = feasible[nonzero]
        if candidates.size:
            return int(candidates[len(candidates) // 2])
        return int(feasible[0])

    def _apply_legacy_result(
        self, parameters: MotorParameters, dataframe: pd.DataFrame
    ) -> None:
        self._current_parameters = parameters
        self._dataframe = dataframe.reset_index(drop=True)
        self.torque_speed_plot.set_dataframe(self._dataframe)
        self.dq_plot.set_results(parameters, self._dataframe)
        self.operating_point_table.set_dataframe(self._dataframe)
        self.parameter_panel.set_calculating(False)
        self.parameter_panel.set_export_enabled(True)
        self.parameter_panel.set_result_available(True)
        self.progress_bar.setValue(100)
        valid = self._dataframe["Torque_Nm"].notna()
        if valid.any():
            self.select_point(int(valid.idxmax()))
        else:
            self.current_point_panel.clear_values()

    def _calculation_failed(self, version: int, error) -> None:
        active_version = (
            self._active_request.version
            if self._active_request is not None
            else None
        )
        if version != self._request_version and version != active_version:
            return
        self.progress_bar.setValue(0)
        self._elapsed_timer.stop()
        self._update_elapsed_display()
        self.parameter_panel.set_calculating(False)
        self.parameter_panel.set_result_available(
            self._analysis_result is not None
        )
        cancelled = False
        if isinstance(error, CalculationErrorDetails):
            message = error.message
            cancelled = error.cancelled
            if not error.cancelled:
                LOGGER.error(
                    "GUI 收到后台异常：%s:%d %s\n%s",
                    error.filename,
                    error.line_number,
                    error.exception_type,
                    error.traceback_text,
                )
                self._show_error("计算失败", error.dialog_text())
        else:  # Backward-compatible entry point used by integrations/tests.
            message = str(error)
            if message != "计算已取消。":
                LOGGER.error("后台计算失败：%s", message)
                self._show_error("计算失败", message)
        suffix = "；已保留旧结果" if self._analysis_result is not None else ""
        self.stage_label.setText(
            "计算已取消" if cancelled or message == "计算已取消。" else "计算失败"
        )
        elapsed = (
            perf_counter() - self._calculation_started_at
            if self._calculation_started_at is not None
            else 0.0
        )
        self.parameter_panel.finish_progress(
            "cancelled"
            if cancelled or message == "计算已取消。"
            else "failed",
            elapsed,
        )
        self.statusBar().showMessage(f"{message}{suffix}")
        self._calculation_started_at = None

    def _thread_finished(self) -> None:
        self._update_elapsed_display()
        self._elapsed_timer.stop()
        if (
            self.parameter_panel.calculation_progress_card.property("state")
            == "running"
        ):
            elapsed = (
                perf_counter() - self._calculation_started_at
                if self._calculation_started_at is not None
                else 0.0
            )
            self.parameter_panel.finish_progress("cancelled", elapsed)
        self._thread = None
        self._worker = None
        self._active_request = None
        self.parameter_panel.set_calculating(False)
        self.parameter_panel.set_result_available(
            self._analysis_result is not None
        )
        if self._close_when_finished:
            self._close_when_finished = False
            QTimer.singleShot(0, self.close)

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def closeEvent(self, event) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._thread.requestInterruption()
            self._close_when_finished = True
            self.statusBar().showMessage("正在取消计算并安全退出…")
            event.ignore()
            return
        super().closeEvent(event)
