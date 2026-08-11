"""Deterministic operating-map coordinate generation."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from models.motor_parameters import MotorParameters
from calculation.equations import electromagnetic_torque


MAXIMUM_MAP_AXIS_POINTS = 401


def point_count_for_step(maximum: float, step: float) -> int:
    """Return the endpoint-inclusive point count for an exact requested step."""

    axis_maximum = float(maximum)
    axis_step = float(step)
    if not np.isfinite(axis_maximum) or axis_maximum <= 0.0:
        raise ValueError("网格轴上限必须是有限正数。")
    if not np.isfinite(axis_step) or axis_step <= 0.0:
        raise ValueError("网格步长必须是有限正数。")
    count = int(np.ceil(axis_maximum / axis_step - 1e-12)) + 1
    if count > MAXIMUM_MAP_AXIS_POINTS:
        raise ValueError(
            f"当前步长将生成 {count} 个轴点，超过上限 "
            f"{MAXIMUM_MAP_AXIS_POINTS}；请增大步长。"
        )
    return max(count, 2)


def generate_step_axis(maximum: float, step: float) -> NDArray[np.float64]:
    """Generate 0..maximum with the requested step and an exact final endpoint."""

    count = point_count_for_step(maximum, step)
    axis_maximum = float(maximum)
    axis_step = float(step)
    values = np.arange(count, dtype=float) * axis_step
    values = values[values < axis_maximum - max(1e-12, axis_maximum * 1e-12)]
    values = np.append(values, axis_maximum)
    if values.size > MAXIMUM_MAP_AXIS_POINTS:
        raise ValueError(
            f"当前步长将生成 {values.size} 个轴点，超过上限 "
            f"{MAXIMUM_MAP_AXIS_POINTS}；请增大步长。"
        )
    if values.size < 2:
        values = np.array([0.0, axis_maximum], dtype=float)
    return values.astype(float, copy=False)


def estimate_maximum_torque_for_current(
    parameters: MotorParameters, current_vector_peak_a: float
) -> float:
    """Cheap calculation-layer estimate used only for the UI grid preview."""

    current = float(current_vector_peak_a)
    if not np.isfinite(current) or current <= 0.0:
        raise ValueError("最大定子电流矢量必须是有限正数。")
    id_lower = max(
        -current,
        parameters.id_min_peak_a
        if parameters.id_min_peak_a is not None
        else -current,
    )
    ids = np.linspace(id_lower, current, 1441)
    iqs = np.sqrt(np.maximum(current**2 - ids**2, 0.0))
    torque = electromagnetic_torque(ids, iqs, parameters)
    return max(float(np.nanmax(torque)), 0.0)


def generate_nonuniform_ratios(point_count: int) -> NDArray[np.float64]:
    """Return exactly ``point_count`` sorted ratios with denser end regions."""

    count = int(point_count)
    if count < 2:
        raise ValueError("转矩轴点数至少为2。")
    base = np.linspace(0.0, 1.0, count)
    candidates = np.unique(
        np.concatenate((base, base**2, 1.0 - (1.0 - base) ** 2))
    )
    candidate_positions = np.linspace(0, len(candidates) - 1, count)
    selected = candidates[np.rint(candidate_positions).astype(int)]
    selected[0] = 0.0
    selected[-1] = 1.0
    if selected.size != count or not np.all(np.diff(selected) > 0.0):
        raise ArithmeticError("无法生成严格递增的非均匀转矩轴。")
    return selected.astype(float)


def generate_torque_axis(
    global_maximum_torque_nm: float, point_count: int
) -> NDArray[np.float64]:
    maximum = float(global_maximum_torque_nm)
    if not np.isfinite(maximum) or maximum < 0.0:
        raise ValueError("全局最大转矩必须是有限非负数。")
    return generate_nonuniform_ratios(point_count) * maximum
