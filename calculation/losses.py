"""Flux, empirical iron-loss, and motor-efficiency calculations."""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

from models.loss_model_parameters import LossModelParameters
from models.motor_parameters import MotorParameters


def dq_flux_linkage(
    id_a: ArrayLike,
    iq_a: ArrayLike,
    parameters: MotorParameters,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    id_values = np.asarray(id_a, dtype=float)
    iq_values = np.asarray(iq_a, dtype=float)
    ld_h, lq_h = parameters.inductances_h(id_values, iq_values)
    psi_d = ld_h * id_values + parameters.flux_pm_wb
    psi_q = lq_h * iq_values
    return psi_d, psi_q, np.hypot(psi_d, psi_q)


def electrical_frequency_hz(
    speed_rpm: ArrayLike, pole_pairs: int
) -> NDArray[np.float64]:
    return pole_pairs * np.asarray(speed_rpm, dtype=float) / 60.0


def iron_loss_w(
    speed_rpm: ArrayLike,
    psi_s_wb: ArrayLike,
    pole_pairs: int,
    loss_parameters: LossModelParameters,
) -> NDArray[np.float64]:
    speed_values = np.asarray(speed_rpm, dtype=float)
    psi_values = np.abs(np.asarray(psi_s_wb, dtype=float))
    result_shape = np.broadcast_shapes(speed_values.shape, psi_values.shape)
    if not loss_parameters.iron_loss_enabled:
        return np.zeros(result_shape, dtype=float)
    frequency = electrical_frequency_hz(speed_values, pole_pairs)
    if loss_parameters.iron_loss_model == "simplified":
        return (
            loss_parameters.k1 * frequency * psi_values**2
            + loss_parameters.k2 * frequency**2 * psi_values**2
        )
    return (
        loss_parameters.kh * frequency * psi_values**loss_parameters.alpha
        + loss_parameters.ke * frequency**2 * psi_values**2
        + loss_parameters.kex * frequency**1.5 * psi_values**1.5
    )


def motor_efficiency(
    output_power_w: ArrayLike,
    copper_loss_w: ArrayLike,
    iron_loss_values_w: ArrayLike,
    *,
    minimum_output_w: float = 100.0,
) -> NDArray[np.float64]:
    output = np.asarray(output_power_w, dtype=float)
    total_loss = np.asarray(copper_loss_w, dtype=float) + np.asarray(
        iron_loss_values_w, dtype=float
    )
    denominator = output + total_loss
    efficiency = np.divide(
        output,
        denominator,
        out=np.full(np.broadcast_shapes(output.shape, total_loss.shape), np.nan),
        where=(output >= minimum_output_w) & (denominator > 0.0),
    )
    return np.clip(efficiency, 0.0, 1.0)
