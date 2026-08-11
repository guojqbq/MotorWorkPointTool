"""Curves shown in the dq-current plot."""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

from calculation.equations import dq_voltage, electrical_angular_speed
from models.motor_parameters import MotorParameters
from models.resolved_characteristic_limits import ResolvedCharacteristicLimits


def constant_torque_curve(
    parameters: MotorParameters,
    torque_nm: float,
    id_values_a: ArrayLike,
    *,
    iq_plot_limit_a: float | None = None,
    limits: ResolvedCharacteristicLimits | None = None,
) -> NDArray[np.float64]:
    resolved = limits or ResolvedCharacteristicLimits.from_legacy_motor(
        parameters
    )
    id_values = np.asarray(id_values_a, dtype=float)
    if parameters.has_saturation_data:
        iq_limit = float(
            iq_plot_limit_a
            if iq_plot_limit_a is not None
            else 3.0 * resolved.max_current_vector_a
        )
        scan = np.linspace(0.0, max(iq_limit, 1e-9), 257)
        iq_grid = np.broadcast_to(scan[None, :], (id_values.size, scan.size))
        id_grid = np.broadcast_to(id_values[:, None], iq_grid.shape)
        from calculation.equations import electromagnetic_torque

        torque_grid = electromagnetic_torque(id_grid, iq_grid, parameters)
        crosses = np.isfinite(torque_grid) & (torque_grid >= torque_nm)
        valid = np.any(crosses, axis=1)
        upper_index = np.maximum(np.argmax(crosses, axis=1), 1)
        lower = scan[upper_index - 1]
        upper = scan[upper_index]
        for _ in range(45):
            middle = 0.5 * (lower + upper)
            middle_torque = electromagnetic_torque(id_values, middle, parameters)
            above = middle_torque >= torque_nm
            upper = np.where(above, middle, upper)
            lower = np.where(above, lower, middle)
        return np.where(valid, 0.5 * (lower + upper), np.nan)
    denominator = (
        1.5
        * parameters.pole_pairs
        * (
            parameters.flux_pm_wb
            + (parameters.ld_h - parameters.lq_h) * id_values
        )
    )
    scale = max(
        abs(parameters.flux_pm_wb),
        abs(parameters.ld_h - parameters.lq_h)
        * max(resolved.max_current_vector_a, 1.0),
        1.0,
    )
    threshold = np.finfo(float).eps * scale * 100.0
    with np.errstate(divide="ignore", invalid="ignore"):
        iq_values = np.divide(
            torque_nm,
            denominator,
            out=np.full_like(id_values, np.nan),
            where=np.abs(denominator) > threshold,
        )
    iq_values[iq_values < 0] = np.nan
    if iq_plot_limit_a is not None:
        iq_values[np.abs(iq_values) > iq_plot_limit_a] = np.nan
    return iq_values


def voltage_limit_curve(
    parameters: MotorParameters,
    speed_rpm: float,
    *,
    samples: int = 721,
    limits: ResolvedCharacteristicLimits | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return the exact full-model voltage boundary in the dq current plane.

    ``[Ud, Uq]`` is an affine transformation of ``[Id, Iq]``.  Inverting that
    transformation for a voltage-vector circle gives the same contour as a
    dense grid calculation, without a marching-squares dependency.
    """

    resolved = limits or ResolvedCharacteristicLimits.from_legacy_motor(
        parameters
    )
    if parameters.has_saturation_data:
        current_extent = max(1.5 * resolved.max_current_vector_a, 1.0)
        id_min = (
            min(-current_extent, parameters.id_min_peak_a)
            if parameters.id_min_peak_a is not None
            else -current_extent
        )
        ids = np.linspace(id_min, current_extent, max(64, int(samples)))
        iqs = np.linspace(-current_extent, current_extent, 321)
        id_grid, iq_grid = np.meshgrid(ids, iqs, indexing="ij")
        ud_v, uq_v = dq_voltage(id_grid, iq_grid, speed_rpm, parameters)
        residual = ud_v**2 + uq_v**2 - resolved.max_voltage_dq_v**2
        lower = np.full(ids.shape, np.nan)
        upper = np.full(ids.shape, np.nan)
        for row_index, row in enumerate(residual):
            crossing = np.flatnonzero(row[:-1] * row[1:] <= 0.0)
            if crossing.size == 0:
                continue
            roots: list[float] = []
            for index in (int(crossing[0]), int(crossing[-1])):
                y0, y1 = float(row[index]), float(row[index + 1])
                fraction = 0.0 if y1 == y0 else -y0 / (y1 - y0)
                roots.append(float(iqs[index] + fraction * (iqs[index + 1] - iqs[index])))
            lower[row_index] = min(roots)
            upper[row_index] = max(roots)
        valid_lower = np.isfinite(lower)
        valid_upper = np.isfinite(upper)
        return (
            np.concatenate((ids[valid_lower], ids[valid_upper][::-1])),
            np.concatenate((lower[valid_lower], upper[valid_upper][::-1])),
        )
    omega_e = float(
        electrical_angular_speed(float(speed_rpm), parameters.pole_pairs)
    )
    matrix = np.array(
        [
            [parameters.rs_ohm, -omega_e * parameters.lq_h],
            [omega_e * parameters.ld_h, parameters.rs_ohm],
        ],
        dtype=float,
    )
    determinant = float(np.linalg.det(matrix))
    if abs(determinant) <= 1e-14:
        return np.array([], dtype=float), np.array([], dtype=float)

    theta = np.linspace(0.0, 2.0 * np.pi, max(16, int(samples)), endpoint=True)
    voltage_boundary = resolved.max_voltage_dq_v * np.vstack(
        (np.cos(theta), np.sin(theta))
    )
    offset = np.array([[0.0], [omega_e * parameters.flux_pm_wb]])
    currents = np.linalg.solve(matrix, voltage_boundary - offset)
    return currents[0], currents[1]


def voltage_boundary_residual(
    parameters: MotorParameters,
    speed_rpm: float,
    id_values_a: ArrayLike,
    iq_values_a: ArrayLike,
    *,
    limits: ResolvedCharacteristicLimits | None = None,
) -> NDArray[np.float64]:
    resolved = limits or ResolvedCharacteristicLimits.from_legacy_motor(
        parameters
    )
    ud_v, uq_v = dq_voltage(id_values_a, iq_values_a, speed_rpm, parameters)
    return ud_v**2 + uq_v**2 - resolved.max_voltage_dq_v**2
