import numpy as np

from calculation.losses import (
    dq_flux_linkage,
    electrical_frequency_hz,
    iron_loss_w,
    motor_efficiency,
)
from models.loss_model_parameters import LossModelParameters
from models.motor_parameters import MotorParameters


def test_flux_and_frequency_equations():
    parameters = MotorParameters.example_ipmsm()
    psi_d, psi_q, psi_s = dq_flux_linkage(-10.0, 20.0, parameters)
    assert np.isclose(psi_d, parameters.flux_pm_wb - 10.0 * parameters.ld_h)
    assert np.isclose(psi_q, 20.0 * parameters.lq_h)
    assert np.isclose(psi_s, np.hypot(psi_d, psi_q))
    assert np.isclose(
        electrical_frequency_hz(3000.0, parameters.pole_pairs),
        parameters.pole_pairs * 3000.0 / 60.0,
    )


def test_iron_loss_is_zero_when_disabled():
    losses = LossModelParameters(iron_loss_enabled=False, kh=100.0, ke=100.0)
    result = iron_loss_w([1000.0, 2000.0], 0.08, 4, losses)
    assert np.array_equal(result, np.zeros(2))


def test_iron_loss_increases_with_speed_and_flux():
    losses = LossModelParameters(
        iron_loss_enabled=True,
        kh=20.0,
        ke=0.05,
        kex=1.0,
        alpha=2.0,
    )
    speed_trend = iron_loss_w([1000.0, 2000.0, 4000.0], 0.08, 4, losses)
    flux_trend = iron_loss_w(3000.0, [0.04, 0.08, 0.12], 4, losses)
    assert np.all(np.diff(speed_trend) > 0)
    assert np.all(np.diff(flux_trend) > 0)


def test_temperature_corrected_resistance():
    losses = LossModelParameters(
        temperature_correction_enabled=True,
        reference_temperature_c=20.0,
        winding_temperature_c=120.0,
        copper_alpha_per_c=0.004,
    )
    assert np.isclose(losses.resistance_at_temperature(0.1), 0.14)


def test_efficiency_bounds_and_low_power_nan():
    result = motor_efficiency(
        [0.0, 99.0, 100.0, 1000.0],
        [10.0, 10.0, 10.0, 100.0],
        0.0,
        minimum_output_w=100.0,
    )
    assert np.isnan(result[0])
    assert np.isnan(result[1])
    assert np.isclose(result[2], 100.0 / 110.0)
    assert np.isclose(result[3], 1000.0 / 1100.0)
    assert np.nanmin(result) >= 0.0
    assert np.nanmax(result) <= 1.0
