import json
import os
from dataclasses import replace
from math import sqrt

import numpy as np
import pytest

from calculation.characteristic_limit_resolver import (
    CharacteristicResolutionError,
    resolve_characteristic_limits,
)
from calculation.envelope_solver import EnvelopeSolver
from calculation.operating_map_solver import OperatingMapSolver
from models.characteristic_input import (
    CharacteristicInput,
    CharacteristicInputMode,
)
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings
from models.motor_parameters import MotorParameters
from models.resolved_characteristic_limits import ResolvedCharacteristicLimits
from services.project_io import (
    PROJECT_FORMAT,
    SCHEMA_VERSION,
    load_project_with_characteristic,
    save_project,
)


def _target_input(
    torque_nm: float = 80.0,
    speed_rpm: float = 12000.0,
    udc_v: float = 320.0,
    hidden_current_a: float = 180.0,
) -> CharacteristicInput:
    return CharacteristicInput(
        input_mode=CharacteristicInputMode.UDC_TMAX_NMAX,
        dc_bus_voltage_v=udc_v,
        max_torque_nm=torque_nm,
        max_current_vector_a=hidden_current_a,
        max_speed_rpm=speed_rpm,
    )


def _current_input(
    current_a: float = 150.0,
    speed_rpm: float = 12000.0,
    udc_v: float = 320.0,
    hidden_torque_nm: float = 100.0,
) -> CharacteristicInput:
    return CharacteristicInput(
        input_mode=CharacteristicInputMode.UDC_IMAX_NMAX,
        dc_bus_voltage_v=udc_v,
        max_torque_nm=hidden_torque_nm,
        max_current_vector_a=current_a,
        max_speed_rpm=speed_rpm,
    )


def test_udc_tmax_nmax_spmsm_derives_current_and_target_torque():
    parameters = replace(MotorParameters.example_spmsm(), speed_points=9)
    limits = resolve_characteristic_limits(
        parameters, _target_input(torque_nm=50.0)
    )
    expected_current = 50.0 / (
        1.5 * parameters.pole_pairs * parameters.flux_pm_wb
    )
    assert isinstance(limits, ResolvedCharacteristicLimits)
    assert limits.input_mode == CharacteristicInputMode.UDC_TMAX_NMAX
    assert limits.derived_current
    assert limits.target_max_torque_nm == 50.0
    assert np.isclose(
        limits.max_current_vector_a, expected_current, rtol=2e-7
    )
    point = EnvelopeSolver(parameters, limits=limits).solve_speed(0.0)
    assert abs(point.id_a) <= 1e-5
    assert np.isclose(point.torque_nm, 50.0, rtol=2e-4, atol=2e-3)


def test_udc_tmax_nmax_ipmsm_uses_negative_id_mtpa_point():
    parameters = replace(MotorParameters.example_ipmsm(), speed_points=9)
    limits = resolve_characteristic_limits(parameters, _target_input())
    point = EnvelopeSolver(parameters, limits=limits).solve_speed(0.0)
    assert point.id_a < 0.0
    assert np.isclose(point.torque_nm, 80.0, rtol=2e-4, atol=2e-3)


def test_udc_imax_nmax_uses_direct_vector_current():
    for parameters in (
        MotorParameters.example_spmsm(),
        MotorParameters.example_ipmsm(),
    ):
        limits = resolve_characteristic_limits(
            parameters, _current_input(current_a=100.0)
        )
        assert limits.input_mode == CharacteristicInputMode.UDC_IMAX_NMAX
        assert not limits.derived_current
        assert limits.target_max_torque_nm is None
        assert np.isclose(limits.max_current_vector_a, 100.0)


def test_udc_and_current_definitions_are_converted_to_peak_limits():
    svpwm = replace(
        MotorParameters.example_spmsm(),
        voltage_utilization=0.9,
        modulation="SVPWM",
        current_definition="rms",
    )
    limits = resolve_characteristic_limits(
        svpwm, _current_input(current_a=100.0, udc_v=400.0)
    )
    assert np.isclose(limits.max_voltage_dq_v, 0.9 * 400.0 / sqrt(3.0))
    assert np.isclose(limits.max_current_vector_a, 100.0 * sqrt(2.0))

    spwm = replace(svpwm, modulation="SPWM", current_definition="peak")
    spwm_limits = resolve_characteristic_limits(
        spwm, _current_input(current_a=100.0, udc_v=400.0)
    )
    assert np.isclose(spwm_limits.max_voltage_dq_v, 0.9 * 400.0 / 2.0)


def test_downstream_solvers_depend_on_resolved_values_not_input_mode():
    parameters = replace(MotorParameters.example_ipmsm(), speed_points=7)
    direct_limits = resolve_characteristic_limits(parameters, _current_input())
    same_values_other_mode = replace(
        direct_limits,
        input_mode=CharacteristicInputMode.UDC_TMAX_NMAX,
        target_max_torque_nm=80.0,
        derived_current=True,
    )
    first = EnvelopeSolver(parameters, limits=direct_limits).solve()
    second = EnvelopeSolver(parameters, limits=same_values_other_mode).solve()
    columns = ["Torque_Nm", "Id_A", "Iq_A", "Us_V"]
    assert np.allclose(first[columns], second[columns], equal_nan=True)


def test_hidden_mode_values_do_not_affect_calculation_dict():
    target_a = _target_input(hidden_current_a=1.0)
    target_b = _target_input(hidden_current_a=9999.0)
    direct_a = _current_input(hidden_torque_nm=1.0)
    direct_b = _current_input(hidden_torque_nm=9999.0)
    assert target_a.calculation_dict() == target_b.calculation_dict()
    assert direct_a.calculation_dict() == direct_b.calculation_dict()


def test_old_v1_imax_umax_loads_as_direct_vector_mode(tmp_path):
    parameters = MotorParameters.example_ipmsm()
    old_values = parameters.as_input_dict()
    old_values["Umax"] = 123.5
    path = tmp_path / "old-vector-limits.json"
    path.write_text(
        json.dumps(
            {
                "format": PROJECT_FORMAT,
                "version": "1.0",
                "parameters": old_values,
            }
        ),
        encoding="utf-8",
    )
    loaded_parameters, _losses, _settings, inputs = (
        load_project_with_characteristic(path)
    )
    assert inputs.input_mode == CharacteristicInputMode.UDC_IMAX_NMAX
    limits = resolve_characteristic_limits(loaded_parameters, inputs)
    assert np.isclose(limits.max_voltage_dq_v, 123.5)
    assert np.isclose(
        limits.max_current_vector_a, loaded_parameters.imax_peak_a
    )


def test_old_12_iq_mode_migrates_to_equivalent_vector_current(tmp_path):
    parameters = MotorParameters.example_ipmsm()
    payload = {
        "format": PROJECT_FORMAT,
        "version": "1.2",
        "parameters": parameters.as_input_dict(),
        "characteristic_input": {
            "input_mode": "ELECTRICAL_LIMIT",
            "max_voltage_v": 150.0,
            "max_iq_a": 100.0,
            "speed_scan_max_rpm": 12000.0,
        },
    }
    path = tmp_path / "old-iq-mode.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded_parameters, _losses, _settings, inputs = (
        load_project_with_characteristic(path)
    )
    limits = resolve_characteristic_limits(loaded_parameters, inputs)
    assert inputs.input_mode == CharacteristicInputMode.UDC_IMAX_NMAX
    assert inputs.max_current_vector_a > 100.0
    assert np.isclose(limits.max_voltage_dq_v, 150.0)


def test_new_project_persists_schema_and_input_mode(tmp_path):
    parameters = MotorParameters.example_ipmsm()
    characteristic = _target_input()
    path = tmp_path / "udc-target.json"
    save_project(
        parameters,
        LossModelParameters(),
        MapCalculationSettings(),
        path,
        characteristic_input=characteristic,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["input_mode"] == "UDC_TMAX_NMAX"
    assert payload["characteristic_input"]["input_mode"] == (
        "UDC_TMAX_NMAX"
    )
    *_legacy_values, loaded = load_project_with_characteristic(path)
    assert loaded == characteristic


def test_parameter_panel_switches_compact_mode_pages():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QLabel

    from ui.parameter_panel import ParameterPanel

    app = QApplication.instance() or QApplication([])
    panel = ParameterPanel()
    labels = {label.text() for label in panel.findChildren(QLabel)}
    assert "逆变器线电流 Is_max" in labels
    assert "母线电压 Udc" in labels
    assert "最大转速 nmax" in labels

    target_index = panel.input_mode.findData("UDC_TMAX_NMAX")
    current_index = panel.input_mode.findData("UDC_IMAX_NMAX")
    panel.input_mode.setCurrentIndex(target_index)
    assert panel.input_mode_pages.currentIndex() == 0
    panel.max_current_vector.setValue(1.0)
    assert "max_current_vector_a" not in (
        panel.characteristic_input().calculation_dict()
    )

    panel.input_mode.setCurrentIndex(current_index)
    assert panel.input_mode_pages.currentIndex() == 1
    panel.target_max_torque.setValue(9999.0)
    assert "max_torque_nm" not in (
        panel.characteristic_input().calculation_dict()
    )
    assert panel.characteristic_section.is_expanded()
    assert not panel.advanced_section.is_expanded()
    assert panel.grid_definition_mode.count() == 2
    assert panel.grid_mode_pages.currentIndex() == 0
    assert "81 × 121" in panel.estimated_map_points.text()
    panel.grid_definition_mode.setCurrentIndex(
        panel.grid_definition_mode.findData("step")
    )
    assert panel.grid_mode_pages.currentIndex() == 1
    panel.close()
    panel.deleteLater()
    app.processEvents()


def test_new_application_defaults_match_required_motor_and_inputs():
    parameters = MotorParameters.example_ipmsm()
    inputs = CharacteristicInput()
    assert parameters.pole_pairs == 3
    assert parameters.rs_ohm == pytest.approx(0.0289)
    assert parameters.ld_mh == pytest.approx(0.442)
    assert parameters.lq_mh == pytest.approx(1.931)
    assert parameters.flux_pm_wb == pytest.approx(0.161)
    assert inputs.dc_bus_voltage_v == pytest.approx(844.0)
    assert inputs.max_speed_rpm == pytest.approx(30000.0)
    assert inputs.max_current_vector_a == pytest.approx(310.0)
    assert inputs.max_torque_nm == pytest.approx(486.0)


def test_both_modes_generate_constraint_compliant_operating_maps():
    parameters = replace(MotorParameters.example_ipmsm(), speed_points=7)
    settings = MapCalculationSettings(
        preview_speed_points=5,
        preview_torque_points=7,
        full_speed_points=7,
        full_torque_points=9,
    )
    for characteristic in (_target_input(), _current_input()):
        limits = resolve_characteristic_limits(parameters, characteristic)
        result = OperatingMapSolver(
            parameters, settings=settings, limits=limits
        ).solve("preview")
        valid = result.dataframe[result.dataframe["IsFeasible"]]
        assert not valid.empty
        assert (
            valid["Is_A"] <= limits.max_current_vector_a * (1.0 + 2e-8)
        ).all()
        assert (
            valid["Us_V"] <= limits.max_voltage_dq_v * (1.0 + 2e-8)
        ).all()


def test_invalid_or_infeasible_inputs_raise_explicit_errors():
    with pytest.raises(ValueError):
        replace(_target_input(), max_torque_nm=-1.0).validated()
    with pytest.raises(ValueError):
        replace(_current_input(), max_current_vector_a=0.0).validated()
    with pytest.raises(ValueError):
        replace(_current_input(), dc_bus_voltage_v=0.0).validated()
    with pytest.raises(CharacteristicResolutionError, match="Udc"):
        resolve_characteristic_limits(
            MotorParameters.example_ipmsm(),
            _target_input(torque_nm=80.0, udc_v=0.1),
        )
