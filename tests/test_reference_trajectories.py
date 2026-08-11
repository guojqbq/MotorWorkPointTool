from dataclasses import replace

import numpy as np

from calculation.equations import dq_voltage, torque_per_iq
from calculation.envelope_solver import EnvelopeSolver, SolverSettings
from calculation.reference_trajectories import (
    generate_local_mtpv_trajectory,
    generate_mtpa_trajectory,
    generate_mtpv_envelope,
    solve_mtpa_point,
    solve_mtpv_point,
)
from models.motor_parameters import MotorParameters


def _iq_for_torque(parameters, torque_nm, id_a):
    coefficient = float(torque_per_iq(id_a, parameters))
    assert coefficient > 0.0
    return torque_nm / coefficient


def _voltage_squared(parameters, speed_rpm, torque_nm, id_a):
    iq_a = _iq_for_torque(parameters, torque_nm, id_a)
    ud_v, uq_v = dq_voltage(id_a, iq_a, speed_rpm, parameters)
    return float(ud_v) ** 2 + float(uq_v) ** 2


def test_spmsm_mtpa_is_id_zero(spmsm_parameters):
    trajectory = generate_mtpa_trajectory(spmsm_parameters, samples=41)
    assert np.max(np.abs(trajectory["Id_A"].to_numpy())) < 1e-6
    assert np.all(np.isfinite(trajectory[["Id_A", "Iq_A", "Is_A"]]))


def test_typical_ipmsm_mtpa_is_negative_and_matches_analytic_relation(
    ipmsm_parameters,
):
    point = solve_mtpa_point(ipmsm_parameters, 50.0)
    assert point.id_a < 0.0
    delta_l = ipmsm_parameters.ld_h - ipmsm_parameters.lq_h
    analytic_rhs = (
        point.id_a**2
        + ipmsm_parameters.flux_pm_wb * point.id_a / delta_l
    )
    assert point.iq_a**2 == pytest_approx(analytic_rhs, rel=2e-7, abs=2e-7)


def test_mtpa_current_is_locally_minimal_for_equal_torque(ipmsm_parameters):
    target = 60.0
    point = solve_mtpa_point(ipmsm_parameters, target)
    optimum = point.id_a**2 + point.iq_a**2
    for perturbation in (-0.5, -0.1, 0.1, 0.5):
        id_a = point.id_a + perturbation
        iq_a = _iq_for_torque(ipmsm_parameters, target, id_a)
        assert optimum <= id_a**2 + iq_a**2 + 1e-7


def test_mtpv_voltage_is_locally_minimal_for_equal_torque(ipmsm_parameters):
    speed_rpm = 9000.0
    target = 30.0
    point = solve_mtpv_point(ipmsm_parameters, speed_rpm, target)
    optimum = _voltage_squared(
        ipmsm_parameters, speed_rpm, target, point.id_a
    )
    for perturbation in (-0.5, -0.1, 0.1, 0.5):
        neighbor = _voltage_squared(
            ipmsm_parameters,
            speed_rpm,
            target,
            point.id_a + perturbation,
        )
        assert optimum <= neighbor + 1e-7


def test_mtpa_mtpv_and_actual_trajectory_are_independent_data(
    ipmsm_parameters, fast_settings
):
    actual = EnvelopeSolver(ipmsm_parameters, fast_settings).solve()
    mtpa = generate_mtpa_trajectory(ipmsm_parameters, samples=43)
    mtpv = generate_mtpv_envelope(ipmsm_parameters, actual)
    actual_ids = actual["Id_A"].to_numpy()
    mtpa_ids = mtpa["Id_A"].to_numpy()
    mtpv_ids = mtpv["Id_A"].to_numpy()
    assert not np.shares_memory(actual_ids, mtpa_ids)
    assert not np.shares_memory(actual_ids, mtpv_ids)
    assert not np.shares_memory(mtpa_ids, mtpv_ids)
    assert not np.array_equal(actual_ids[: len(mtpa_ids)], mtpa_ids)


def test_low_speed_actual_point_is_near_mtpa(
    ipmsm_parameters, fast_settings
):
    dataframe = EnvelopeSolver(ipmsm_parameters, fast_settings).solve()
    assert bool(dataframe.iloc[0]["NearMTPA"])
    assert dataframe.iloc[0]["MTPADistance_A"] < 1e-3


def test_deep_field_weakening_approaches_and_reaches_mtpv(
    ipmsm_parameters, fast_settings
):
    dataframe = EnvelopeSolver(ipmsm_parameters, fast_settings).solve()
    high_speed = dataframe.tail(6)
    assert (
        high_speed.iloc[-1]["MTPVDistance_A"]
        < high_speed.iloc[0]["MTPVDistance_A"]
    )
    assert (
        high_speed.iloc[-1]["MTPVDistance_A"]
        < high_speed.iloc[-1]["MTPADistance_A"]
    )


def test_local_mtpv_changes_with_selected_speed(ipmsm_parameters):
    low = generate_local_mtpv_trajectory(
        ipmsm_parameters, 3000.0, samples=31
    )
    high = generate_local_mtpv_trajectory(
        ipmsm_parameters, 12000.0, samples=31
    )
    assert np.all(low["Speed_rpm"] == 3000.0)
    assert np.all(high["Speed_rpm"] == 12000.0)
    assert not np.allclose(low["Id_A"], high["Id_A"], rtol=0, atol=1e-3)


def test_spmsm_ipmsm_and_near_equal_inductance_are_finite(
    spmsm_parameters, ipmsm_parameters
):
    near_equal = replace(
        spmsm_parameters,
        lq_mh=spmsm_parameters.ld_mh * (1.0 + 1e-7),
    )
    for parameters in (spmsm_parameters, ipmsm_parameters, near_equal):
        mtpa = generate_mtpa_trajectory(parameters, samples=21)
        mtpv = generate_local_mtpv_trajectory(
            parameters, 8000.0, samples=21
        )
        assert np.all(np.isfinite(mtpa[["Id_A", "Iq_A", "Is_A"]]))
        assert np.all(np.isfinite(mtpv[["Id_A", "Iq_A", "Is_A", "Us_V"]]))


def test_actual_rows_record_reference_and_constraint_flags(
    ipmsm_parameters, fast_settings
):
    dataframe = EnvelopeSolver(ipmsm_parameters, fast_settings).solve()
    required = {
        "NearMTPA",
        "NearMTPV",
        "CurrentConstraintActive",
        "VoltageConstraintActive",
        "PowerConstraintActive",
        "MTPADistance_A",
        "MTPVDistance_A",
    }
    assert required.issubset(dataframe.columns)
    assert dataframe["CurrentConstraintActive"].any()
    assert dataframe["VoltageConstraintActive"].any()


def pytest_approx(value, *, rel, abs):
    import pytest

    return pytest.approx(value, rel=rel, abs=abs)
