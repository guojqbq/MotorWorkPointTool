from dataclasses import replace

import numpy as np

from calculation.operating_map_solver import OperatingMapSolver
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings
from models.motor_parameters import MotorParameters


def _small_settings(**changes):
    values = {
        "preview_speed_points": 9,
        "preview_torque_points": 11,
        "full_speed_points": 13,
        "full_torque_points": 15,
    }
    values.update(changes)
    return MapCalculationSettings(**values)


def test_map_shape_columns_and_boundary_definition():
    parameters = MotorParameters.example_ipmsm()
    result = OperatingMapSolver(
        parameters, settings=_small_settings()
    ).solve("preview")
    assert result.shape == (9, 11)
    assert len(result.dataframe) == 99
    assert result.torque_coordinate_mode == "actual"
    assert np.all(np.diff(result.torque_axis_nm) > 0.0)
    assert np.isclose(result.torque_axis_nm[0], 0.0)
    assert np.isclose(result.torque_axis_nm[-1], np.max(result.maximum_torque_nm))
    requested = result.matrix("TorqueRequest_Nm")
    assert np.allclose(requested, result.torque_axis_nm[None, :])
    local_maximum = result.maximum_torque_nm[:, None]
    outside = requested > local_maximum + 1e-9
    assert np.all(result.matrix("SolverStatus")[outside] == "OutsideEnvelope")
    assert not np.any(result.matrix("IsFeasible")[outside])


def test_feasible_points_meet_torque_current_voltage_and_power_constraints():
    parameters = MotorParameters.example_ipmsm()
    result = OperatingMapSolver(
        parameters, settings=_small_settings()
    ).solve("preview")
    valid = result.dataframe[result.dataframe["IsFeasible"]]
    assert np.allclose(
        valid["TorqueActual_Nm"],
        valid["TorqueRequest_Nm"],
        rtol=1e-8,
        atol=1e-8,
    )
    assert (valid["CurrentUtilization"] <= 1.0 + 2e-8).all()
    assert (valid["VoltageUtilization"] <= 1.0 + 2e-8).all()

    power_parameters = replace(parameters, pmax_kw=15.0)
    power_result = OperatingMapSolver(
        power_parameters, settings=_small_settings()
    ).solve("preview")
    power_valid = power_result.dataframe[power_result.dataframe["IsFeasible"]]
    assert (power_valid["MechanicalPower_kW"] <= 15.0 + 1e-6).all()


def test_low_speed_points_are_near_mtpa_and_high_speed_moves_toward_mtpv():
    result = OperatingMapSolver(
        MotorParameters.example_ipmsm(), settings=_small_settings()
    ).solve("preview")
    usable = result.dataframe[
        result.dataframe["IsFeasible"] & (result.dataframe["TorqueRatio"] >= 0.5)
    ]
    low = usable[usable["SpeedIndex"] == 0]
    high = usable[usable["SpeedIndex"] >= 7]
    assert low["NearMTPA"].mean() >= 0.95
    assert high["MTPVDistance_A"].median() < high["MTPADistance_A"].median()


def test_step_defined_grid_uses_requested_steps_and_exact_endpoints():
    parameters = replace(
        MotorParameters.example_ipmsm(),
        max_speed_rpm=1000.0,
        speed_points=5,
    )
    settings = _small_settings(
        grid_definition_mode="step",
        speed_step_rpm=300.0,
        torque_step_nm=100.0,
    )
    result = OperatingMapSolver(parameters, settings=settings).solve("full")
    assert np.allclose(
        result.speed_grid_rpm, [0.0, 300.0, 600.0, 900.0, 1000.0]
    )
    assert np.allclose(np.diff(result.torque_axis_nm)[:-1], 100.0)
    assert result.torque_axis_nm[0] == 0.0
    assert np.isclose(
        result.torque_axis_nm[-1], np.max(result.maximum_torque_nm)
    )
    assert len(result.dataframe) == result.shape[0] * result.shape[1]


def test_efficiency_losses_and_iron_loss_toggle():
    parameters = MotorParameters.example_ipmsm()
    disabled = OperatingMapSolver(
        parameters,
        LossModelParameters(),
        _small_settings(),
    ).solve("preview")
    disabled_feasible = disabled.dataframe[disabled.dataframe["IsFeasible"]]
    assert np.allclose(disabled_feasible["IronLoss_kW"], 0.0)

    enabled = OperatingMapSolver(
        parameters,
        LossModelParameters(
            iron_loss_enabled=True,
            kh=20.0,
            ke=0.05,
            kex=1.0,
        ),
        _small_settings(),
    ).solve("preview")
    moving = enabled.dataframe[
        enabled.dataframe["IsFeasible"] & (enabled.dataframe["Speed_rpm"] > 0)
    ]
    assert (moving["IronLoss_kW"] > 0.0).all()
    assert np.allclose(
        moving["TotalMotorLoss_kW"],
        moving["CopperLoss_kW"] + moving["IronLoss_kW"],
    )
    efficiency = moving["Efficiency"].dropna()
    assert ((efficiency >= 0.0) & (efficiency <= 1.0)).all()


def test_spmsm_and_nearly_equal_inductance_are_finite():
    cases = [
        MotorParameters.example_spmsm(),
        MotorParameters(ld_mh=0.6, lq_mh=0.600000001),
    ]
    for parameters in cases:
        result = OperatingMapSolver(
            parameters, settings=_small_settings()
        ).solve("preview")
        valid = result.dataframe[result.dataframe["IsFeasible"]]
        assert not valid[["Id_A", "Iq_A", "Us_V"]].isna().any().any()
        assert np.isfinite(valid[["Id_A", "Iq_A", "Us_V"]]).all().all()


def test_cancel_check_interrupts_map_calculation():
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls >= 2

    solver = OperatingMapSolver(
        MotorParameters.example_ipmsm(), settings=_small_settings()
    )
    try:
        solver.solve("preview", cancel_check=cancelled)
    except InterruptedError:
        pass
    else:
        raise AssertionError("cancellation did not interrupt the calculation")


def test_preview_and_full_are_distinct_profiles():
    result_preview = OperatingMapSolver(
        MotorParameters.example_ipmsm(), settings=_small_settings()
    ).solve("preview")
    result_full = OperatingMapSolver(
        MotorParameters.example_ipmsm(), settings=_small_settings()
    ).solve("full")
    assert result_preview.is_preview
    assert not result_full.is_preview
    assert result_preview.shape == (9, 11)
    assert result_full.shape == (13, 15)


def test_single_point_solver_matches_request_and_constraints():
    parameters = MotorParameters.example_ipmsm()
    solver = OperatingMapSolver(parameters, settings=_small_settings())
    point = solver.solve_fixed_torque_point(3000.0, 20.0)
    assert point["IsFeasible"]
    assert np.isclose(point["TorqueActual_Nm"], 20.0, atol=1e-8)
    assert point["CurrentUtilization"] <= 1.0 + 2e-8
    assert point["VoltageUtilization"] <= 1.0 + 2e-8


def test_operating_map_diagnostics_and_unique_map_indices():
    result = OperatingMapSolver(
        MotorParameters.example_ipmsm(), settings=_small_settings()
    ).solve("preview")
    diagnostics = result.diagnostics()
    assert diagnostics["speed_points"] == 9
    assert diagnostics["torque_points"] == 11
    assert diagnostics["total_points"] == 99
    assert diagnostics["feasible_points"] == int(
        result.dataframe["IsFeasible"].sum()
    )
    assert diagnostics["nonzero_torque_points"] > 0
    assert diagnostics["solver_failed_points"] == 0
    for map_index in (0, 17, 98):
        speed_index, torque_index = result.unravel_index(map_index)
        assert result.flat_index(speed_index, torque_index) == map_index
        assert result.point_by_map_index(map_index).name == map_index
