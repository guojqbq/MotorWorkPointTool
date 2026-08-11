import numpy as np

from calculation.constraint_curves import (
    constant_torque_curve,
    voltage_boundary_residual,
    voltage_limit_curve,
)


def test_full_model_voltage_limit_curve_lies_on_boundary(ipmsm_parameters):
    ids, iqs = voltage_limit_curve(ipmsm_parameters, 6000.0, samples=361)
    assert len(ids) == 361
    residual = voltage_boundary_residual(
        ipmsm_parameters, 6000.0, ids, iqs
    )
    normalized = np.max(np.abs(residual)) / ipmsm_parameters.umax_v**2
    assert normalized < 1e-11


def test_constant_torque_curve_handles_singular_denominator(ipmsm_parameters):
    delta_l = ipmsm_parameters.ld_h - ipmsm_parameters.lq_h
    singular_id = -ipmsm_parameters.flux_pm_wb / delta_l
    ids = np.array([singular_id - 1e-6, singular_id, singular_id + 1e-6])
    iqs = constant_torque_curve(ipmsm_parameters, 10.0, ids)
    assert np.isnan(iqs[1])
