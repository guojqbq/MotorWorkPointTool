"""Steady-state PMSM equations using phase peak values and SI units."""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

from models.motor_parameters import MotorParameters


def mechanical_angular_speed(speed_rpm: ArrayLike) -> NDArray[np.float64]:
    return np.asarray(speed_rpm, dtype=float) * (2.0 * np.pi / 60.0)


def electrical_angular_speed(
    speed_rpm: ArrayLike, pole_pairs: int
) -> NDArray[np.float64]:
    return pole_pairs * mechanical_angular_speed(speed_rpm)


def electromagnetic_torque(
    id_a: ArrayLike, iq_a: ArrayLike, parameters: MotorParameters
) -> NDArray[np.float64]:
    id_array = np.asarray(id_a, dtype=float)
    iq_array = np.asarray(iq_a, dtype=float)
    ld_h, lq_h = parameters.inductances_h(id_array, iq_array)
    return (
        1.5
        * parameters.pole_pairs
        * (
            parameters.flux_pm_wb * iq_array
            + (ld_h - lq_h) * id_array * iq_array
        )
    )


def torque_per_iq(
    id_a: ArrayLike,
    parameters: MotorParameters,
    iq_a: ArrayLike = 0.0,
) -> NDArray[np.float64]:
    id_array = np.asarray(id_a, dtype=float)
    iq_array = np.asarray(iq_a, dtype=float)
    ld_h, lq_h = parameters.inductances_h(id_array, iq_array)
    return (
        1.5
        * parameters.pole_pairs
        * (
            parameters.flux_pm_wb
            + (ld_h - lq_h) * id_array
        )
    )


def dq_voltage(
    id_a: ArrayLike,
    iq_a: ArrayLike,
    speed_rpm: ArrayLike,
    parameters: MotorParameters,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    id_array = np.asarray(id_a, dtype=float)
    iq_array = np.asarray(iq_a, dtype=float)
    ld_h, lq_h = parameters.inductances_h(id_array, iq_array)
    omega_e = electrical_angular_speed(speed_rpm, parameters.pole_pairs)
    ud_v = parameters.rs_ohm * id_array - omega_e * lq_h * iq_array
    uq_v = (
        parameters.rs_ohm * iq_array
        + omega_e * (ld_h * id_array + parameters.flux_pm_wb)
    )
    return ud_v, uq_v


def current_magnitude(id_a: ArrayLike, iq_a: ArrayLike) -> NDArray[np.float64]:
    return np.hypot(np.asarray(id_a, dtype=float), np.asarray(iq_a, dtype=float))


def voltage_magnitude(ud_v: ArrayLike, uq_v: ArrayLike) -> NDArray[np.float64]:
    return np.hypot(np.asarray(ud_v, dtype=float), np.asarray(uq_v, dtype=float))


def mechanical_power(
    torque_nm: ArrayLike, speed_rpm: ArrayLike
) -> NDArray[np.float64]:
    return np.asarray(torque_nm, dtype=float) * mechanical_angular_speed(speed_rpm)


def copper_loss(
    id_a: ArrayLike, iq_a: ArrayLike, parameters: MotorParameters
) -> NDArray[np.float64]:
    id_array = np.asarray(id_a, dtype=float)
    iq_array = np.asarray(iq_a, dtype=float)
    return 1.5 * parameters.rs_ohm * (id_array**2 + iq_array**2)
