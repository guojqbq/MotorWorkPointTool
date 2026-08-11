import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from dataclasses import replace

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication, QToolButton

from calculation.envelope_solver import EnvelopeSolver, SolverSettings
from calculation.operating_map_solver import OperatingMapSolver
from models.analysis_result import AnalysisResult
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings
from models.motor_parameters import MotorParameters
from main import format_exception_details
from ui.main_window import MainWindow
from ui.plot_theme import (
    EXTERNAL_COLOR,
    FIELD_WEAKENING_COLOR,
    MTPA_COLOR,
    MTPV_COLOR,
    SELECTED_COLOR,
    ZERO_AXIS_COLOR,
)


def test_main_window_can_be_created_without_display():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(auto_calculate=False)
    assert window.windowTitle() == "PMSM 性能分析工具 v0.5.0"
    assert window.parameter_panel.parameters().motor_type == "IPMSM"
    assert not window.parameter_panel.export_csv_button.isEnabled()
    assert isinstance(window.dq_curve_controls, QToolButton)
    assert len(window.dq_curve_controls.actions) == 7
    assert all(
        action.isChecked()
        for action in window.dq_curve_controls.actions.values()
    )
    window.dq_curve_controls.actions["mtpa"].setChecked(False)
    assert not window.dq_plot._mtpa.isVisible()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_main_plots_start_equal_dq_is_one_to_one_and_menu_is_above_plot():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(auto_calculate=False)
    window.show()
    app.processEvents()

    left_size, right_size = window.plot_splitter.sizes()
    assert abs(left_size - right_size) <= 0.05 * max(
        left_size, right_size
    )
    assert window.dq_plot.plotItem.getViewBox().state["aspectLocked"] == 1
    pixel_width, pixel_height = (
        window.dq_plot.plotItem.getViewBox().viewPixelSize()
    )
    assert np.isclose(abs(pixel_width), abs(pixel_height), rtol=1e-9)
    assert (
        window.dq_curve_controls.geometry().bottom()
        <= window.dq_plot.geometry().top()
    )
    assert not hasattr(window.dq_curve_controls, "checkboxes")
    assert window.plot_splitter.widget(0).property("role") == "plotCard"
    assert window.plot_splitter.widget(1).property("role") == "plotCard"
    assert isinstance(window.operating_map_plot.display_button, QToolButton)
    assert window.operating_map_plot.variable_combo.isHidden()
    assert window.operating_map_plot.show_contours.isHidden()

    window.resize(1300, 800)
    app.processEvents()
    assert window.dq_plot.plotItem.getViewBox().state["aspectLocked"] == 1
    pixel_width, pixel_height = (
        window.dq_plot.plotItem.getViewBox().viewPixelSize()
    )
    assert np.isclose(abs(pixel_width), abs(pixel_height), rtol=1e-9)
    window.close()
    window.deleteLater()
    app.processEvents()


def test_operating_map_uses_nan_masked_filled_mesh_and_integer_hit_indices():
    from ui.operating_map_plot import OperatingMapPlot

    app = QApplication.instance() or QApplication([])
    parameters = replace(
        MotorParameters.example_ipmsm(),
        max_speed_rpm=12000.0,
        speed_points=7,
    )
    settings = MapCalculationSettings(
        full_speed_points=7,
        full_torque_points=9,
    )
    result = OperatingMapSolver(
        parameters, LossModelParameters(), settings
    ).solve("full")
    plot = OperatingMapPlot()
    plot.set_result(result)
    try:
        assert plot.selected_variable == "Efficiency"
        assert tuple(plot._cmap.map(0.0, mode="byte")[:3]) == (
            20,
            45,
            140,
        )
        assert tuple(plot._cmap.map(1.0, mode="byte")[:3]) == (
            220,
            38,
            38,
        )
        assert plot._mesh.z.shape == (
            result.shape[0] - 1,
            result.shape[1] - 1,
        )
        assert np.isfinite(plot._mesh.z).any()
        assert np.isnan(plot._mesh.z).any()
        assert plot._visible_flat_indices.size == int(
            result.dataframe["IsFeasible"].sum()
        )
        assert all(type(point.data()) is int for point in plot._points.points())
        total_loss_index = plot.variable_combo.findData(
            "TotalMotorLoss_kW"
        )
        plot.variable_combo.setCurrentIndex(total_loss_index)
        assert np.isfinite(plot._mesh.z).any()
        plot.contour_action.setChecked(True)
        assert any(len(item.getData()[0]) > 0 for item in plot._contour_items)
    finally:
        plot.close()
        plot.deleteLater()
        app.processEvents()


def test_plot_palette_legends_zero_axes_and_actual_point_styles():
    from ui.dq_plot import DqPlot
    from ui.operating_map_plot import OperatingMapPlot
    from ui.torque_speed_plot import TorqueSpeedPlot

    app = QApplication.instance() or QApplication([])
    torque_plot = TorqueSpeedPlot()
    dq_plot = DqPlot()
    map_plot = OperatingMapPlot()
    try:
        assert (
            torque_plot._envelope.opts["pen"].color().name().upper()
            == EXTERNAL_COLOR
        )
        assert torque_plot._legend.pos().x() == pytest.approx(10.0)
        assert torque_plot._legend.pos().y() == pytest.approx(10.0)
        expected_regions = {
            "MTPA": MTPA_COLOR,
            "FIELD_WEAKENING": FIELD_WEAKENING_COLOR,
            "MTPV": MTPV_COLOR,
        }
        for plot in (torque_plot, dq_plot):
            for region, color in expected_regions.items():
                brush = plot.operating_region_items[region].opts["brush"]
                assert brush.color().name().upper() == color
            assert plot._zero_x.pen.color().name().upper() == ZERO_AXIS_COLOR
            assert plot._zero_y.pen.color().name().upper() == ZERO_AXIS_COLOR
            assert plot._zero_x.pen.widthF() > 2.0
            assert plot._zero_y.pen.widthF() > 2.0

        assert dq_plot._mtpa.opts["pen"].color().name().upper() == MTPA_COLOR
        assert dq_plot._mtpv.opts["pen"].color().name().upper() == MTPV_COLOR
        assert dq_plot._trajectory.opts["pen"] is None
        assert (
            dq_plot._trajectory.opts["symbolBrush"].upper()
            == EXTERNAL_COLOR
        )
        assert (
            torque_plot._selected.opts["symbolBrush"].upper()
            == SELECTED_COLOR
        )
        assert map_plot._zero_x.pen.color().name().upper() == ZERO_AXIS_COLOR
        assert map_plot._zero_y.pen.widthF() > 2.0
        assert map_plot._envelope.opts["pen"].color().name().upper() == (
            EXTERNAL_COLOR
        )
        assert map_plot._selected.opts["symbolBrush"].upper() == (
            SELECTED_COLOR
        )
    finally:
        for plot in (torque_plot, dq_plot, map_plot):
            plot.close()
            plot.deleteLater()
        app.processEvents()


def test_dq_plot_updates_speed_dependent_local_mtpv():
    app = QApplication.instance() or QApplication([])
    parameters = MotorParameters.example_ipmsm()
    dataframe = EnvelopeSolver(
        parameters, SolverSettings(coarse_id_points=101, fine_id_points=51)
    ).solve()
    window = MainWindow(auto_calculate=False)
    window._calculation_finished(parameters, dataframe)
    window.select_point(20)
    low = window.dq_plot.local_mtpv_dataframe
    window.select_point(120)
    high = window.dq_plot.local_mtpv_dataframe
    assert float(low["Speed_rpm"].iloc[0]) == float(
        dataframe.iloc[20]["Speed_rpm"]
    )
    assert float(high["Speed_rpm"].iloc[0]) == float(
        dataframe.iloc[120]["Speed_rpm"]
    )
    assert not np.allclose(low["Id_A"], high["Id_A"], atol=1e-3)
    selected_row = window.operating_point_table.currentIndex().row()
    reference = window.dq_plot.mtpa_dataframe.iloc[20].to_dict()
    window.dq_plot.referencePointSelected.emit("MTPA", reference)
    assert window.current_point_panel.title() == "理论参考点：MTPA"
    assert window.operating_point_table.currentIndex().row() == selected_row
    window.close()
    window.deleteLater()
    app.processEvents()


def test_display_settings_do_not_change_numeric_cache_key_or_version():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(auto_calculate=False)
    motor = window.parameter_panel.parameters()
    losses = window.parameter_panel.loss_parameters()
    settings = window.parameter_panel.map_settings()
    display_only = replace(settings, show_internal_points_in_dq=True)
    numeric_change = replace(settings, preview_speed_points=31)
    assert window._cache_key(motor, losses, settings, "preview") == window._cache_key(
        motor, losses, display_only, "preview"
    )
    assert window._cache_key(motor, losses, settings, "preview") != window._cache_key(
        motor, losses, numeric_change, "preview"
    )
    version = window._request_version
    window.parameter_panel.show_internal_dq.setChecked(True)
    assert window._request_version == version
    window.close()
    window.deleteLater()
    app.processEvents()


def test_udc_modulation_and_utilization_are_in_numeric_cache_key():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(auto_calculate=False)
    motor = window.parameter_panel.parameters()
    characteristic = window.parameter_panel.characteristic_input()
    losses = window.parameter_panel.loss_parameters()
    settings = window.parameter_panel.map_settings()
    baseline = window._cache_key(
        motor, losses, settings, "full", characteristic
    )
    assert baseline != window._cache_key(
        replace(motor, modulation="SPWM"),
        losses,
        settings,
        "full",
        characteristic,
    )
    assert baseline != window._cache_key(
        replace(motor, voltage_utilization=0.9),
        losses,
        settings,
        "full",
        characteristic,
    )
    assert baseline != window._cache_key(
        motor,
        losses,
        settings,
        "full",
        replace(characteristic, dc_bus_voltage_v=300.0),
    )
    window.close()
    window.deleteLater()
    app.processEvents()


def test_parameter_changes_never_schedule_automatic_calculation(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(auto_calculate=True)
    starts = []
    monkeypatch.setattr(window, "_start_request", lambda request: starts.append(request))
    for offset in range(1, 8):
        window.parameter_panel.rs_ohm.setValue(0.03 + offset * 0.001)
    app.processEvents()
    assert starts == []
    assert window._thread is None
    assert not hasattr(window, "_debounce_timer")
    assert not hasattr(window, "_stable_full_timer")
    assert window.statusBar().currentMessage() == "参数已修改，请点击开始计算"
    assert window.parameter_panel.calculate_button.text() == "开始计算"
    window.close()
    window.deleteLater()
    app.processEvents()


def test_stale_analysis_result_cannot_overwrite_latest_version():
    app = QApplication.instance() or QApplication([])
    motor = MotorParameters.example_ipmsm()
    settings = MapCalculationSettings(
        preview_speed_points=4,
        preview_torque_points=5,
    )
    operating_map = OperatingMapSolver(
        motor, LossModelParameters(), settings
    ).solve("preview")
    external = EnvelopeSolver(
        motor, SolverSettings(coarse_id_points=101, fine_id_points=51)
    ).solve()
    result = AnalysisResult(
        calculation_parameters=motor,
        external_characteristic=external,
        operating_map=operating_map,
        profile="preview",
        cache_key="stale",
    )
    window = MainWindow(auto_calculate=False)
    window._request_version = 2
    window._apply_analysis_result(1, result)
    assert window._analysis_result is None
    window._apply_analysis_result(2, result)
    assert window._analysis_result is result
    assert window.operating_map_plot.profile_label.text() == "预览 4×5"
    window.close()
    window.deleteLater()
    app.processEvents()


def test_unhandled_exception_details_include_origin_and_full_traceback():
    try:
        raise RuntimeError("click callback failed")
    except RuntimeError as error:
        details, full_traceback = format_exception_details(
            type(error), error, error.__traceback__
        )

    assert "异常类型：RuntimeError" in details
    assert "文件名：" in details
    assert "test_gui_smoke.py" in details
    assert "行号：" in details
    assert "错误信息：click callback failed" in details
    assert "Traceback (most recent call last):" in full_traceback
    assert "RuntimeError: click callback failed" in full_traceback
def test_inductance_and_winding_controls_are_compact_and_default_safe():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from models.inductance_model import InductanceModel
    from models.winding_connection import WindingConnection
    from ui.parameter_panel import ParameterPanel

    app = QApplication.instance() or QApplication([])
    panel = ParameterPanel()
    parameters = panel.parameters()
    assert parameters.inductance_model is InductanceModel.CONSTANT
    assert parameters.winding_connection is WindingConnection.STAR
    assert not hasattr(panel, "inductance_section")
    assert panel.motor_section.is_expanded()
    assert not panel.saturation_map_controls.isVisible()
    assert not panel.ld_mh.isHidden()
    assert not panel.lq_mh.isHidden()
    assert not panel.winding_section.is_expanded()
    assert not panel.case_section.is_expanded()
    panel.winding_connection.setCurrentIndex(
        panel.winding_connection.findData("OPEN_WINDING")
    )
    assert panel.open_winding_topology.isEnabled()


def test_saturation_mode_hides_fixed_inductance_and_shows_format_help():
    from ui.parameter_panel import ParameterPanel

    app = QApplication.instance() or QApplication([])
    panel = ParameterPanel()
    panel.inductance_model.setCurrentIndex(
        panel.inductance_model.findData("SATURATION_MAP")
    )
    assert panel.ld_mh.isHidden()
    assert panel.lq_mh.isHidden()
    assert not panel.saturation_map_controls.isHidden()
    assert "第一行 = Iq(A)" in panel.saturation_format_hint.text()
    assert panel.saturation_format_button.text() == "查看格式示例"
    assert panel.saturation_template_button.text() == "导出 Excel 模板"
    panel.inductance_model.setCurrentIndex(
        panel.inductance_model.findData("CONSTANT")
    )
    assert not panel.ld_mh.isHidden()
    assert not panel.lq_mh.isHidden()


def test_saturation_format_dialog_and_prominent_progress_card():
    from ui.parameter_panel import ParameterPanel
    from ui.saturation_map_dialog import SaturationMapFormatDialog

    app = QApplication.instance() or QApplication([])
    dialog = SaturationMapFormatDialog("μH")
    assert dialog.windowTitle() == "Ld/Lq Excel 格式示例"
    assert "Id/Iq" in dialog.example_label.text()
    panel = ParameterPanel()
    panel.set_calculating(True)
    panel.start_progress()
    panel.update_progress_stage("内部 Map", 6665, 9801)
    panel.update_progress(68)
    panel.update_progress_elapsed(32.5)
    assert not panel.calculation_progress_card.isHidden()
    assert panel.calculation_progress_bar.minimumHeight() >= 22
    assert panel.calculation_progress_bar.value() == 68
    assert "内部工作点" in panel.calculation_stage_label.text()
    assert "6,665 / 9,801" in panel.calculation_point_label.text()
    assert "32.5 s" in panel.calculation_elapsed_label.text()
    panel.set_calculating(False)
    panel.finish_progress("completed", 40.0)
    assert panel.calculation_progress_bar.value() == 100
    assert panel.calculation_progress_card.property("state") == "completed"
    panel.finish_progress("failed", 41.0)
    assert panel.calculation_progress_card.property("state") == "failed"
    assert panel.calculation_stage_label.text() == "计算失败"


def test_modern_stylesheet_keeps_engineering_layout_contract():
    from ui.styles import APP_STYLESHEET

    assert "#F4F6F8" in APP_STYLESHEET
    assert "#2563EB" in APP_STYLESHEET
    assert 'QFrame[role="progressCard"]' in APP_STYLESHEET
    assert "min-height: 32px" in APP_STYLESHEET
    assert "border-radius: 7px" in APP_STYLESHEET


def test_saturation_preview_dialog_can_render_maps_offscreen():
    from models.saturation_map import InductanceSaturationMap
    from ui.saturation_map_dialog import SaturationMapPreviewDialog

    app = QApplication.instance() or QApplication([])
    data = InductanceSaturationMap.from_arrays(
        [-300.0, 0.0],
        [0.0, 300.0],
        np.array([[500e-6, 450e-6], [440e-6, 400e-6]]),
    )
    dialog = SaturationMapPreviewDialog(data, data)
    assert dialog.windowTitle() == "Ld/Lq 饱和 Map 预览"
