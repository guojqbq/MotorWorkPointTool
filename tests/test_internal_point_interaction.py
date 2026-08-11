import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from calculation.envelope_solver import EnvelopeSolver, SolverSettings
from calculation.operating_map_solver import OperatingMapSolver
from models.analysis_result import AnalysisResult
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings
from models.motor_parameters import MotorParameters
from models.operating_map import dataframe_to_matrices
from ui.main_window import MainWindow
from ui.map_index_utils import clicked_flat_index, normalize_flat_index


class _AcceptedEvent:
    def __init__(self):
        self.accepted = False

    def accept(self):
        self.accepted = True


class _PointData:
    def __init__(self, data):
        self._data = data

    def data(self):
        return self._data


@pytest.fixture
def analysis_case():
    motor = replace(
        MotorParameters.example_ipmsm(),
        speed_points=7,
        max_speed_rpm=12000.0,
    )
    settings = MapCalculationSettings(
        preview_speed_points=5,
        preview_torque_points=6,
        full_speed_points=7,
        full_torque_points=9,
    )
    operating_map = OperatingMapSolver(
        motor, LossModelParameters(), settings
    ).solve("full")
    external = EnvelopeSolver(
        motor, SolverSettings(coarse_id_points=101, fine_id_points=51)
    ).solve()
    result = AnalysisResult(
        calculation_parameters=motor,
        external_characteristic=external,
        operating_map=operating_map,
        profile="full",
        cache_key="interaction-case",
    )
    return motor, settings, result


@pytest.fixture
def populated_window(analysis_case):
    app = QApplication.instance() or QApplication([])
    _motor, _settings, result = analysis_case
    window = MainWindow(auto_calculate=False)
    window._apply_analysis_result(window._request_version, result)
    yield app, window, result
    window.close()
    window.deleteLater()
    app.processEvents()


def _item_and_point_with_map_index(plot, map_index):
    for item in plot.operating_region_items.values():
        for point in item.points():
            if int(point.data()) == map_index:
                return item, point
    raise LookupError(f"map_index {map_index} is not displayed")


def _scatter_point_count(plot):
    return sum(
        len(item.getData()[0]) for item in plot.operating_region_items.values()
    )


def _all_scatter_points(plot):
    return [
        point
        for item in plot.operating_region_items.values()
        for point in item.points()
    ]


def test_map_contains_many_independent_interior_points(analysis_case):
    _motor, _settings, result = analysis_case
    frame = result.operating_map.dataframe
    feasible = frame["IsFeasible"].to_numpy(bool)
    torque = frame["TorqueActual_Nm"].to_numpy(float)
    maximum = result.operating_map.maximum_torque_nm[
        frame["SpeedIndex"].to_numpy(int)
    ]
    interior = feasible & (torque > 1e-9) & (torque < maximum - 1e-8)
    assert feasible.sum() > len(result.external_characteristic)
    assert np.any(interior)
    assert frame[feasible].groupby("SpeedIndex")["TorqueIndex"].nunique().min() > 2


def test_left_and_dq_scatter_lengths_equal_feasible_count(populated_window):
    _app, window, result = populated_window
    feasible_count = int(result.operating_map.dataframe["IsFeasible"].sum())
    assert _scatter_point_count(window.torque_speed_plot) == feasible_count
    assert _scatter_point_count(window.dq_plot) == feasible_count
    assert window.torque_speed_plot.internal_point_count == feasible_count
    assert window.dq_plot.internal_point_count == feasible_count
    assert all(
        item.isVisible()
        for item in window.dq_plot.operating_region_items.values()
    )
    assert all(
        type(point.data()) is int
        for point in _all_scatter_points(window.torque_speed_plot)
    )
    assert all(
        type(point.data()) is int
        for point in _all_scatter_points(window.dq_plot)
    )


def test_left_and_dq_click_emit_same_exact_map_index(populated_window):
    _app, window, result = populated_window
    feasible = result.operating_map.feasible_map_indices()
    map_index = int(feasible[len(feasible) // 2])
    left_item, left_point = _item_and_point_with_map_index(
        window.torque_speed_plot, map_index
    )
    event = _AcceptedEvent()
    left_item.sigClicked.emit(
        left_item,
        np.asarray([left_point], dtype=object),
        event,
    )
    assert event.accepted
    assert window._selected_map_index == map_index
    dq_item, dq_point = _item_and_point_with_map_index(window.dq_plot, map_index)
    event = _AcceptedEvent()
    dq_item.sigClicked.emit(
        dq_item,
        np.asarray([dq_point], dtype=object),
        event,
    )
    assert event.accepted
    assert window._selected_map_index == map_index


def test_first_middle_and_last_flat_indices_are_selectable(populated_window):
    _app, window, result = populated_window
    feasible = result.operating_map.feasible_map_indices()
    assert feasible[0] == 0
    map_indices = (
        int(feasible[0]),
        int(feasible[len(feasible) // 2]),
        int(feasible[-1]),
    )
    for map_index in map_indices:
        item, point = _item_and_point_with_map_index(
            window.torque_speed_plot, map_index
        )
        event = _AcceptedEvent()
        window.torque_speed_plot._on_internal_points_clicked(
            item,
            np.asarray([point], dtype=object),
            event,
        )
        assert event.accepted
        assert window._selected_map_index == map_index


def test_multiple_clicked_spots_ndarray_selects_first_without_ambiguity(
    populated_window,
):
    _app, window, _result = populated_window
    item = next(
        scatter
        for scatter in window.torque_speed_plot.operating_region_items.values()
        if len(scatter.points()) >= 2
    )
    first_point, second_point = item.points()[:2]
    first_index = int(first_point.data())
    event = _AcceptedEvent()
    window.torque_speed_plot._on_internal_points_clicked(
        item,
        np.asarray([first_point, second_point], dtype=object),
        event,
    )
    assert event.accepted
    assert window._selected_map_index == first_index


def test_clicked_index_conversion_accepts_one_value_and_rejects_many():
    assert normalize_flat_index(np.asarray([7], dtype=np.int64)) == 7
    assert clicked_flat_index(
        np.asarray([_PointData(np.asarray([8], dtype=np.int64))], dtype=object)
    ) == 8
    with pytest.raises(ValueError, match="只包含一个 flat_index"):
        clicked_flat_index(
            np.asarray(
                [_PointData(np.asarray([1, 2], dtype=np.int64))],
                dtype=object,
            )
        )


def test_select_operating_point_accepts_numpy_scalar_array_at_index_zero(
    populated_window,
):
    _app, window, _result = populated_window
    window.select_operating_point(np.asarray([0], dtype=np.int64))
    assert window._selected_map_index == 0


def test_empty_click_and_nearest_candidates_do_not_use_array_truth_value(
    populated_window,
):
    _app, window, _result = populated_window
    assert clicked_flat_index(np.asarray([], dtype=object)) is None

    window.torque_speed_plot._internal_flat_indices = np.asarray([], dtype=int)
    assert (
        window.torque_speed_plot._nearest_internal_map_index(QPointF(), 12.0)
        is None
    )
    window.dq_plot._internal_valid_indices = np.asarray([], dtype=int)
    window.dq_plot._displayed_internal_indices = np.asarray([], dtype=int)
    assert window.dq_plot._nearest_internal_index(QPointF(), 9.0) is None
    window.operating_map_plot._visible_flat_indices = np.asarray([], dtype=int)
    assert window.operating_map_plot._nearest_flat_index(QPointF(), 14.0) is None


def test_blank_click_nearest_internal_point_and_far_click_rejected(
    populated_window,
):
    _app, window, result = populated_window
    feasible = result.operating_map.feasible_map_indices()
    map_index = int(feasible[len(feasible) // 2])
    row = result.operating_map.point_by_map_index(map_index)
    scene_point = window.torque_speed_plot.plotItem.vb.mapViewToScene(
        QPointF(float(row["Speed_rpm"]), float(row["TorqueActual_Nm"]))
    )
    assert (
        window.torque_speed_plot._nearest_internal_map_index(scene_point, 12.0)
        == map_index
    )
    far_point = QPointF(scene_point.x() + 1000.0, scene_point.y() + 1000.0)
    assert (
        window.torque_speed_plot._nearest_internal_map_index(far_point, 12.0)
        is None
    )

    dq_item, dq_point = _item_and_point_with_map_index(
        window.dq_plot, map_index
    )
    event = _AcceptedEvent()
    dq_item.sigClicked.emit(
        dq_item,
        np.asarray([dq_point], dtype=object),
        event,
    )
    assert event.accepted
    assert window._selected_map_index == map_index


def test_selected_internal_point_matches_map_and_updates_links(populated_window):
    _app, window, result = populated_window
    feasible = result.operating_map.feasible_map_indices()
    map_index = int(feasible[len(feasible) // 2])
    expected = result.operating_map.point_by_map_index(map_index)
    window.select_operating_point(map_index)

    selected_speed, selected_torque = window.torque_speed_plot._selected.getData()
    selected_id, selected_iq = window.dq_plot._selected.getData()
    assert np.isclose(selected_speed[0], expected["Speed_rpm"])
    assert np.isclose(selected_torque[0], expected["TorqueActual_Nm"])
    assert np.isclose(selected_id[0], expected["Id_A"])
    assert np.isclose(selected_iq[0], expected["Iq_A"])
    assert len(window.dq_plot._voltage_limit.getData()[0]) > 0
    assert len(window.dq_plot._constant_torque.getData()[0]) > 0
    assert np.isclose(
        window.dq_plot.local_mtpv_dataframe["Speed_rpm"].iloc[0],
        expected["Speed_rpm"],
    )


def test_default_selection_is_nonzero_near_half_speed_and_torque(populated_window):
    _app, window, result = populated_window
    assert window._selected_map_index is not None
    row = result.operating_map.point_by_map_index(window._selected_map_index)
    speed_fraction = row["Speed_rpm"] / result.operating_map.speed_grid_rpm[-1]
    local_maximum = result.operating_map.maximum_torque_nm[int(row["SpeedIndex"])]
    torque_fraction = row["TorqueActual_Nm"] / local_maximum
    assert row["TorqueActual_Nm"] > 0
    assert abs(speed_fraction - 0.5) <= 0.2
    assert abs(torque_fraction - 0.5) <= 0.2


def test_parameter_change_keeps_old_results_and_marks_stale(populated_window):
    app, window, result = populated_window
    old_map = window._analysis_result.operating_map
    window.parameter_panel.flux_pm_wb.setValue(
        window.parameter_panel.flux_pm_wb.value() * 1.01
    )
    app.processEvents()
    assert window._analysis_result.operating_map is old_map
    assert window._results_stale
    assert window._dirty
    assert "结果已过期" in window.view_tabs.tabText(0)
    assert "结果已过期" in window.operating_map_plot.profile_label.text()
    assert window.statusBar().currentMessage() == "参数已修改，请点击开始计算"
    assert result.operating_map is old_map


def test_compact_display_menu_controls_internal_points_and_speed_highlight(
    populated_window,
):
    app, window, result = populated_window
    controls = window.dq_curve_controls
    controls.internal_points_action.setChecked(False)
    app.processEvents()
    assert all(
        not item.isVisible()
        for item in window.dq_plot.operating_region_items.values()
    )

    controls.internal_points_action.setChecked(True)
    feasible = result.operating_map.feasible_map_indices()
    window.select_operating_point(int(feasible[len(feasible) // 2]))
    controls.display_mode_actions["current_speed"].setChecked(True)
    app.processEvents()
    assert 0 < window.dq_plot.displayed_internal_point_count < len(feasible)

    controls.current_speed_highlight_action.setChecked(False)
    app.processEvents()
    assert not window.dq_plot._current_speed_trace.isVisible()
    controls.current_speed_highlight_action.setChecked(True)
    app.processEvents()
    assert window.dq_plot._current_speed_trace.isVisible()


def test_start_button_requests_one_full_calculation(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(auto_calculate=False)
    requests = []
    monkeypatch.setattr(window, "_start_request", lambda request: requests.append(request))
    window.parameter_panel.calculate_button.click()
    assert len(requests) == 1
    assert requests[0].profile == "full"
    assert requests[0].force
    window.close()
    window.deleteLater()
    app.processEvents()


def test_manual_worker_keeps_gui_event_loop_responsive():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(auto_calculate=False)
    window.parameter_panel.speed_points.setValue(17)
    window.parameter_panel.full_speed_points.setValue(13)
    window.parameter_panel.full_torque_points.setValue(15)

    heartbeats = []
    heartbeat = QTimer()
    heartbeat.setInterval(2)
    heartbeat.timeout.connect(lambda: heartbeats.append(1))
    heartbeat.start()

    window.parameter_panel.calculate_button.click()
    assert window._thread is not None
    assert not window.parameter_panel.calculate_button.isEnabled()
    assert window.parameter_panel.cancel_button.isEnabled()

    loop = QEventLoop()
    window._thread.finished.connect(loop.quit)
    QTimer.singleShot(20000, loop.quit)
    loop.exec()
    heartbeat.stop()
    app.processEvents()

    assert window._analysis_result is not None
    assert window._analysis_result.profile == "full"
    assert window._last_map_diagnostics["feasible_points"] > 0
    assert len(heartbeats) > 0
    assert window.parameter_panel.calculate_button.isEnabled()
    assert not window.parameter_panel.cancel_button.isEnabled()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_zero_feasible_map_shows_explicit_error(analysis_case, monkeypatch):
    app = QApplication.instance() or QApplication([])
    motor, _settings, result = analysis_case
    frame = result.operating_map.dataframe.copy()
    frame["IsFeasible"] = False
    frame["SolverStatus"] = "Infeasible"
    bad_map = replace(
        result.operating_map,
        dataframe=frame,
        matrices=dataframe_to_matrices(frame, result.operating_map.shape),
    )
    bad_result = replace(result, operating_map=bad_map, cache_key="bad-map")
    window = MainWindow(auto_calculate=False)
    errors = []
    monkeypatch.setattr(
        window, "_show_error", lambda title, message: errors.append((title, message))
    )
    window._apply_analysis_result(window._request_version, bad_result)
    assert errors
    assert errors[0][0] == "内部 Map 求解失败"
    assert "没有任何可行点" in errors[0][1]
    assert "没有任何可行点" in window.statusBar().currentMessage()
    window.close()
    window.deleteLater()
    app.processEvents()
