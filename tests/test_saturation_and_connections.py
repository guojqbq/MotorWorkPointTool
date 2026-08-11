from __future__ import annotations

from math import sqrt

import numpy as np
import pandas as pd
import pytest

from calculation.characteristic_limit_resolver import (
    CharacteristicResolutionError,
    resolve_characteristic_limits,
)
from calculation.envelope_solver import EnvelopeSolver, SolverSettings
from calculation.equations import dq_voltage, electromagnetic_torque
from calculation.reference_trajectories import solve_mtpa_point, solve_mtpv_point
from calculation.operating_map_solver import OperatingMapSolver
from models.characteristic_input import CharacteristicInput, CharacteristicInputMode
from models.inductance_model import InductanceModel
from models.motor_parameters import MotorParameters
from models.saturation_map import InductanceSaturationMap
from models.winding_connection import OpenWindingTopology, WindingConnection
from services.saturation_map_io import load_ld_lq_workbook
from services.project_io import load_project, save_project
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings


def _map(values_uh) -> InductanceSaturationMap:
    return InductanceSaturationMap.from_arrays(
        [-400.0, -200.0, 0.0],
        [0.0, 200.0, 400.0],
        np.asarray(values_uh, dtype=float) * 1e-6,
    )


def _saturated_parameters(*, varying: bool = False) -> MotorParameters:
    if varying:
        ld = _map([[600, 560, 500], [520, 480, 430], [460, 420, 380]])
        lq = _map([[2100, 1800, 1450], [2000, 1650, 1250], [1900, 1500, 1050]])
    else:
        ld = _map(np.full((3, 3), 442.0))
        lq = _map(np.full((3, 3), 1931.0))
    return MotorParameters(
        inductance_model=InductanceModel.SATURATION_MAP,
        ld_saturation_map=ld,
        lq_saturation_map=lq,
        imax_a=300.0,
    ).validated()


def test_map_nodes_and_midpoint_bilinear_interpolation():
    table = _map([[100, 200, 300], [300, 500, 700], [500, 800, 1100]])
    assert float(table.interpolate_h(-200.0, 200.0)) == pytest.approx(500e-6)
    expected = np.mean([100.0, 200.0, 300.0, 500.0]) * 1e-6
    assert float(table.interpolate_h(-300.0, 100.0)) == pytest.approx(expected)


def test_excel_ld_lq_workbook_import(tmp_path):
    frame_ld = np.array(
        [["Id/Iq [A]", 0.0, 200.0], [-200.0, 500.0, 450.0], [0.0, 440.0, 400.0]],
        dtype=object,
    )
    frame_lq = np.array(
        [["Id/Iq [A]", 0.0, 200.0], [-200.0, 1900.0, 1600.0], [0.0, 1800.0, 1500.0]],
        dtype=object,
    )
    path = tmp_path / "saturation.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(frame_ld).to_excel(writer, sheet_name="Ld", header=False, index=False)
        pd.DataFrame(frame_lq).to_excel(writer, sheet_name="Lq", header=False, index=False)
    ld_map, lq_map = load_ld_lq_workbook(path)
    assert float(ld_map.interpolate_h(-200.0, 0.0)) == pytest.approx(500e-6)
    assert float(lq_map.interpolate_h(0.0, 200.0)) == pytest.approx(1500e-6)


def test_saturation_and_connection_project_round_trip(tmp_path):
    parameters = _saturated_parameters(varying=True)
    parameters = MotorParameters.from_input_dict(
        {
            **parameters.as_input_dict(),
            "winding_connection": "OPEN_WINDING",
            "open_winding_topology": "CUSTOM_DUAL_UDC",
            "open_winding_udc2_v": 600.0,
        }
    )
    path = tmp_path / "project.json"
    losses = LossModelParameters()
    settings = MapCalculationSettings()
    save_project(parameters, losses, settings, path)
    loaded, loaded_losses, loaded_settings = load_project(path)
    assert loaded == parameters
    assert loaded_losses == losses
    assert loaded_settings == settings


def test_map_outside_is_nan_and_constraint_resolution_reports_range():
    table = _map(np.full((3, 3), 442.0))
    assert np.isnan(float(table.interpolate_h(-401.0, 10.0)))
    parameters = _saturated_parameters()
    inputs = CharacteristicInput(
        input_mode=CharacteristicInputMode.UDC_IMAX_NMAX,
        max_current_vector_a=450.0,
    )
    with pytest.raises(CharacteristicResolutionError, match="超出饱和电感Map范围"):
        resolve_characteristic_limits(parameters, inputs)


def test_constant_value_map_matches_constant_equations():
    constant = MotorParameters()
    saturation = _saturated_parameters()
    ids = np.array([-300.0, -150.0, 0.0])
    iqs = np.array([20.0, 160.0, 300.0])
    np.testing.assert_allclose(
        electromagnetic_torque(ids, iqs, saturation),
        electromagnetic_torque(ids, iqs, constant),
        rtol=1e-12,
    )
    sat_voltage = dq_voltage(ids, iqs, 8000.0, saturation)
    constant_voltage = dq_voltage(ids, iqs, 8000.0, constant)
    np.testing.assert_allclose(sat_voltage[0], constant_voltage[0], rtol=1e-12)
    np.testing.assert_allclose(sat_voltage[1], constant_voltage[1], rtol=1e-12)


def test_saturation_is_queried_at_each_working_point_and_references_use_it():
    parameters = _saturated_parameters(varying=True)
    ld_a, lq_a = parameters.inductances_h(-50.0, 50.0)
    ld_b, lq_b = parameters.inductances_h(-300.0, 300.0)
    assert float(ld_a) != float(ld_b)
    assert float(lq_a) != float(lq_b)
    mtpa = solve_mtpa_point(parameters, 120.0, current_hint_a=300.0)
    mtpv = solve_mtpv_point(parameters, 12000.0, 60.0)
    assert float(electromagnetic_torque(mtpa.id_a, mtpa.iq_a, parameters)) == pytest.approx(120.0, rel=2e-5)
    assert float(electromagnetic_torque(mtpv.id_a, mtpv.iq_a, parameters)) == pytest.approx(60.0, rel=2e-5)
    limits = resolve_characteristic_limits(
        parameters,
        CharacteristicInput(max_current_vector_a=300.0),
    )
    point = EnvelopeSolver(
        parameters,
        SolverSettings(coarse_id_points=101, fine_id_points=51),
        limits,
    ).solve_speed(10000.0)
    assert point.valid
    expected_ld, expected_lq = parameters.inductances_h(point.id_a, point.iq_a)
    assert point.ld_uh == pytest.approx(float(expected_ld) * 1e6)
    assert point.lq_uh == pytest.approx(float(expected_lq) * 1e6)


def test_saturated_internal_map_records_local_inductance_and_weakening():
    parameters = _saturated_parameters(varying=True)
    limits = resolve_characteristic_limits(
        parameters,
        CharacteristicInput(max_current_vector_a=300.0, max_speed_rpm=30000.0),
    )
    settings = MapCalculationSettings(
        preview_speed_points=6,
        preview_torque_points=7,
        full_speed_points=6,
        full_torque_points=7,
    )
    result = OperatingMapSolver(parameters, settings=settings, limits=limits).solve("preview")
    feasible = result.dataframe[result.dataframe["IsFeasible"].astype(bool)]
    assert not feasible.empty
    expected_ld, expected_lq = parameters.inductances_h(
        feasible["Id_A"].to_numpy(float), feasible["Iq_A"].to_numpy(float)
    )
    np.testing.assert_allclose(feasible["Ld_uH"], expected_ld * 1e6)
    np.testing.assert_allclose(feasible["Lq_uH"], expected_lq * 1e6)
    assert "FIELD_WEAKENING" in set(feasible["ControlRegion"].astype(str))


@pytest.mark.parametrize(
    ("connection", "topology", "udc2", "voltage_factor", "current_factor"),
    [
        (WindingConnection.STAR, OpenWindingTopology.DUAL_COMMON_DC, None, 1 / sqrt(3), 1.0),
        (WindingConnection.DELTA, OpenWindingTopology.DUAL_COMMON_DC, None, 1.0, 1 / sqrt(3)),
        (WindingConnection.OPEN_WINDING, OpenWindingTopology.DUAL_COMMON_DC, None, 2 / sqrt(3), 1.0),
        (WindingConnection.OPEN_WINDING, OpenWindingTopology.DUAL_ISOLATED_DC, None, 2 / sqrt(3), 1.0),
        (WindingConnection.OPEN_WINDING, OpenWindingTopology.CUSTOM_DUAL_UDC, 300.0, 700 / (400 * sqrt(3)), 1.0),
    ],
)
def test_winding_voltage_and_current_conversion(
    connection, topology, udc2, voltage_factor, current_factor
):
    parameters = MotorParameters(
        voltage_utilization=1.0,
        winding_connection=connection,
        open_winding_topology=topology,
        open_winding_udc2_v=udc2,
    )
    inputs = CharacteristicInput(
        input_mode=CharacteristicInputMode.UDC_IMAX_NMAX,
        dc_bus_voltage_v=400.0,
        max_current_vector_a=300.0,
    )
    limits = resolve_characteristic_limits(parameters, inputs)
    assert limits.max_voltage_dq_v == pytest.approx(400.0 * voltage_factor)
    assert limits.max_current_vector_a == pytest.approx(300.0 * current_factor)
