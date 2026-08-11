from __future__ import annotations

import logging

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from calculation.envelope_solver import EnvelopeSolver, SolverSettings
from calculation.operating_map_solver import OperatingMapSolver
from models.characteristic_input import CharacteristicInput
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings
from models.motor_parameters import MotorParameters
from ui.calculation_worker import CalculationErrorDetails, CalculationWorker
from ui.main_window import MainWindow


def _worker(*, diagnostic_mode: bool = True) -> CalculationWorker:
    return CalculationWorker(
        MotorParameters(),
        LossModelParameters(),
        MapCalculationSettings(diagnostic_mode=diagnostic_mode),
        "full",
        1,
        "diagnostic-test",
        CharacteristicInput(),
    )


def test_worker_returns_complete_traceback(monkeypatch, caplog):
    def nested_failure():
        raise RuntimeError("diagnostic sentinel")

    def fail_solve(self, **_kwargs):
        nested_failure()

    monkeypatch.setattr(EnvelopeSolver, "solve", fail_solve)
    failures = []
    worker = _worker()
    worker.failed.connect(lambda version, error: failures.append((version, error)))
    with caplog.at_level(logging.ERROR):
        worker.run()

    assert len(failures) == 1
    version, details = failures[0]
    assert version == 1
    assert isinstance(details, CalculationErrorDetails)
    assert details.exception_type == "RuntimeError"
    assert details.filename.endswith("test_calculation_diagnostics.py")
    assert details.line_number > 0
    assert "nested_failure" in details.traceback_text
    assert "diagnostic sentinel" in details.dialog_text()
    assert "diagnostic sentinel" in caplog.text


def test_diagnostic_mode_runs_11_by_11_with_stage_and_point_progress(caplog):
    results = []
    failures = []
    stages = []
    worker = _worker()
    worker.finished.connect(lambda version, result: results.append((version, result)))
    worker.failed.connect(lambda version, error: failures.append((version, error)))
    worker.stage.connect(
        lambda version, name, done, total: stages.append(
            (version, name, done, total)
        )
    )
    with caplog.at_level(logging.INFO):
        worker.run()

    assert failures == []
    assert len(results) == 1
    result = results[0][1]
    assert result.external_characteristic.shape[0] == 11
    assert result.operating_map.shape == (11, 11)
    assert any(name == "参数校验" for _, name, _, _ in stages)
    assert any(name == "外特性" and done == 11 for _, name, done, _ in stages)
    assert any(name == "MTPA/MTPV" for _, name, _, _ in stages)
    assert any(
        name == "内部 Map" and done == 121 and total == 121
        for _, name, done, total in stages
    )
    assert any(name == "损耗效率" for _, name, _, _ in stages)
    assert any(name == "绘图刷新" for _, name, _, _ in stages)
    assert "speed_index=0 torque_index=0" in caplog.text
    assert "initial_id_a=" in caplog.text
    assert "iterations=" in caplog.text


def test_gui_error_restores_button_and_preserves_old_result(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(auto_calculate=False)
    old_result = object()
    window._analysis_result = old_result
    window.parameter_panel.set_result_available(True)
    window.parameter_panel.set_calculating(True)
    errors = []
    monkeypatch.setattr(
        window, "_show_error", lambda title, message: errors.append((title, message))
    )
    details = CalculationErrorDetails(
        exception_type="ValueError",
        filename="solver.py",
        line_number=42,
        message="bad point",
        traceback_text="Traceback sentinel",
    )
    window._calculation_failed(window._request_version, details)

    assert window._analysis_result is old_result
    assert window.parameter_panel.calculate_button.isEnabled()
    assert not window.parameter_panel.cancel_button.isEnabled()
    assert window.parameter_panel.calculate_button.text() == "重新计算"
    assert errors and "solver.py" in errors[0][1]
    assert "Traceback sentinel" in errors[0][1]
    assert "已保留旧结果" in window.statusBar().currentMessage()
    window.close()
    window.deleteLater()
    app.processEvents()


def test_envelope_solver_has_bounded_timeout(monkeypatch):
    solver = EnvelopeSolver(
        MotorParameters(speed_points=2),
        SolverSettings(timeout_seconds=1e-9, max_iterations=3),
    )
    original = solver.solve_speed

    def solve_speed(speed_rpm):
        return original(speed_rpm)

    monkeypatch.setattr(solver, "solve_speed", solve_speed)
    with pytest.raises(TimeoutError, match="speed_index=0"):
        solver.solve()


def test_diagnostic_settings_override_step_grid_without_changing_saved_values():
    settings = MapCalculationSettings(
        diagnostic_mode=True,
        grid_definition_mode="step",
        speed_step_rpm=1.0,
        torque_step_nm=1.0,
    )
    assert settings.grid_shape("full") == (11, 11)
    assert settings.resolved_grid_shape("full", 30000.0, 500.0) == (11, 11)
    assert settings.grid_definition_mode == "step"


def test_worker_returns_plot_ready_references_without_gui_search():
    results = []
    worker = _worker()
    worker.finished.connect(lambda _version, result: results.append(result))
    worker.run()
    result = results[0]
    assert result.mtpa_trajectory is not None
    assert not result.mtpa_trajectory.empty
    assert result.mtpv_envelope is not None
    assert not result.mtpv_envelope.empty
    for column in (
        "MTPAReferenceId_A",
        "MTPAReferenceIq_A",
        "MTPVReferenceId_A",
        "MTPVReferenceIq_A",
    ):
        assert column in result.operating_map.dataframe.columns


def test_dq_plot_uses_precomputed_references_for_refresh_and_selection(monkeypatch):
    app = QApplication.instance() or QApplication([])
    parameters = MotorParameters(speed_points=7)
    settings = MapCalculationSettings(
        full_speed_points=7,
        full_torque_points=9,
    )
    operating_map = OperatingMapSolver(parameters, settings=settings).solve("full")
    from calculation.dq_reference_data import (
        build_mtpa_trajectory_from_map,
        build_mtpv_envelope_from_external,
    )
    from ui.dq_plot import DqPlot
    import ui.dq_plot as dq_module

    mtpa = build_mtpa_trajectory_from_map(parameters, operating_map)
    mtpv = build_mtpv_envelope_from_external(
        parameters, operating_map.external_characteristic
    )
    monkeypatch.setattr(
        dq_module,
        "generate_mtpa_trajectory",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("GUI must not solve MTPA")
        ),
    )
    monkeypatch.setattr(
        dq_module,
        "generate_mtpv_envelope",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("GUI must not solve MTPV envelope")
        ),
    )
    monkeypatch.setattr(
        dq_module,
        "generate_local_mtpv_trajectory",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("GUI must not solve local MTPV")
        ),
    )
    plot = DqPlot()
    plot.set_results(
        parameters,
        operating_map.external_characteristic,
        mtpa_dataframe=mtpa,
        mtpv_dataframe=mtpv,
    )
    plot.set_operating_map(operating_map)
    selected = int(operating_map.feasible_map_indices()[0])
    plot.set_selected_map_index(selected)
    assert not plot.mtpa_dataframe.empty
    assert not plot.mtpv_dataframe.empty
    assert not plot.local_mtpv_dataframe.empty
    plot.close()
    plot.deleteLater()
    app.processEvents()


def test_operating_map_reuses_identical_external_grid(monkeypatch):
    parameters = MotorParameters(speed_points=11)
    settings = MapCalculationSettings(
        full_speed_points=11,
        full_torque_points=9,
    )
    envelope_settings = SolverSettings(
        coarse_id_points=1001,
        fine_id_points=301,
    )
    external = EnvelopeSolver(parameters, envelope_settings).solve()
    import calculation.operating_map_solver as map_module

    monkeypatch.setattr(
        map_module.EnvelopeSolver,
        "solve",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("matching external grid must be reused")
        ),
    )
    result = OperatingMapSolver(parameters, settings=settings).solve(
        "full", external_characteristic=external
    )
    assert result.shape == (11, 9)
    np.testing.assert_allclose(
        result.external_characteristic["Torque_Nm"], external["Torque_Nm"]
    )
