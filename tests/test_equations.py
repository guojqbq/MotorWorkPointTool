from math import sqrt

import numpy as np

from calculation.equations import (
    copper_loss,
    current_magnitude,
    dq_voltage,
    electromagnetic_torque,
    electrical_angular_speed,
    mechanical_angular_speed,
    mechanical_power,
    voltage_magnitude,
)
from models.motor_parameters import MotorParameters


def test_torque_equation_matches_requirement(ipmsm_parameters):
    p = ipmsm_parameters
    id_a = -35.0
    iq_a = 120.0
    expected = (
        1.5
        * p.pole_pairs
        * (p.flux_pm_wb * iq_a + (p.ld_h - p.lq_h) * id_a * iq_a)
    )
    assert float(electromagnetic_torque(id_a, iq_a, p)) == pytest_approx(expected)


def test_dq_voltage_equations_match_requirement(ipmsm_parameters):
    p = ipmsm_parameters
    speed_rpm = 3600.0
    id_a = -42.0
    iq_a = 135.0
    omega_e = float(electrical_angular_speed(speed_rpm, p.pole_pairs))
    expected_ud = p.rs_ohm * id_a - omega_e * p.lq_h * iq_a
    expected_uq = p.rs_ohm * iq_a + omega_e * (
        p.ld_h * id_a + p.flux_pm_wb
    )
    ud_v, uq_v = dq_voltage(id_a, iq_a, speed_rpm, p)
    assert float(ud_v) == pytest_approx(expected_ud)
    assert float(uq_v) == pytest_approx(expected_uq)


def test_magnitudes_power_and_copper_loss(ipmsm_parameters):
    p = ipmsm_parameters
    assert float(current_magnitude(3.0, 4.0)) == pytest_approx(5.0)
    assert float(voltage_magnitude(5.0, 12.0)) == pytest_approx(13.0)
    omega_m = float(mechanical_angular_speed(3000.0))
    assert float(mechanical_power(10.0, 3000.0)) == pytest_approx(
        10.0 * omega_m
    )
    assert float(copper_loss(3.0, 4.0, p)) == pytest_approx(
        1.5 * p.rs_ohm * 25.0
    )


def test_rms_current_and_modulation_conversions():
    rms = MotorParameters(
        imax_a=100.0,
        id_min_a=-80.0,
        current_definition="rms",
        modulation="SPWM",
        udc_v=400.0,
        voltage_utilization=0.9,
    ).validated()
    assert rms.imax_peak_a == pytest_approx(100.0 * sqrt(2.0))
    assert rms.id_min_peak_a == pytest_approx(-80.0 * sqrt(2.0))
    assert rms.umax_v == pytest_approx(180.0)

    svpwm = MotorParameters(
        udc_v=400.0,
        voltage_utilization=0.9,
        modulation="SVPWM",
    ).validated()
    assert svpwm.umax_v == pytest_approx(0.9 * 400.0 / sqrt(3.0))


def test_speed_conversion():
    assert float(mechanical_angular_speed(60.0)) == pytest_approx(2.0 * np.pi)


def pytest_approx(value):
    # Keeps this module importable outside pytest while retaining strict tests.
    import pytest

    return pytest.approx(value, rel=1e-12, abs=1e-12)
