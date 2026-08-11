"""Independent numerical MTPA and MTPV reference trajectories.

Both optimizations use the torque equality to express ``Iq`` as a function of
``Id`` and then perform a robust one-dimensional numerical minimization.  A
dense grid supplies a safe bracket and SciPy refines the local optimum.  The
actual speed-envelope solver does not consume these trajectories as a stitched
operating strategy; they are references and proximity metrics only.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

import numpy as np
import pandas as pd
try:
    from scipy.optimize import minimize_scalar
except ImportError:  # packaged build intentionally omits SciPy
    from calculation.scalar_optimize import minimize_scalar

from calculation.equations import (
    dq_voltage,
    electromagnetic_torque,
    torque_per_iq,
    voltage_magnitude,
)
from models.motor_parameters import MotorParameters
from models.resolved_characteristic_limits import ResolvedCharacteristicLimits


REFERENCE_COLUMNS = [
    "Kind",
    "Speed_rpm",
    "Torque_Nm",
    "Id_A",
    "Iq_A",
    "Is_A",
    "Us_V",
]


@dataclass(frozen=True, slots=True)
class ReferencePoint:
    kind: str
    speed_rpm: float
    torque_nm: float
    id_a: float
    iq_a: float
    is_a: float
    us_v: float

    def as_record(self) -> dict[str, float | str]:
        return {
            "Kind": self.kind,
            "Speed_rpm": self.speed_rpm,
            "Torque_Nm": self.torque_nm,
            "Id_A": self.id_a,
            "Iq_A": self.iq_a,
            "Is_A": self.is_a,
            "Us_V": self.us_v,
        }


def _resolved_limits(
    parameters: MotorParameters,
    limits: ResolvedCharacteristicLimits | None,
) -> ResolvedCharacteristicLimits:
    return limits or ResolvedCharacteristicLimits.from_legacy_motor(parameters)


def _id_search_bound(
    parameters: MotorParameters,
    limits: ResolvedCharacteristicLimits | None,
    current_hint_a: float | None = None,
) -> float:
    resolved = _resolved_limits(parameters, limits)
    current = max(
        float(
            resolved.max_current_vector_a
            if current_hint_a is None
            else current_hint_a
        ),
        1e-6,
    )
    characteristic = parameters.flux_pm_wb / max(
        min(parameters.ld_h, parameters.lq_h), 1e-12
    )
    return min(max(3.0 * current, 2.0 * characteristic), 50.0 * current)


def _maximum_mtpa_torque_at_current_limit(
    parameters: MotorParameters,
    limits: ResolvedCharacteristicLimits | None = None,
) -> float:
    resolved = _resolved_limits(parameters, limits)
    theta = np.linspace(0.0, np.pi, 4001)
    ids = resolved.max_current_vector_a * np.cos(theta)
    iqs = resolved.max_current_vector_a * np.sin(theta)
    torque = electromagnetic_torque(ids, iqs, parameters)
    return max(0.0, float(np.nanmax(torque)))


def _candidate_iq(
    parameters: MotorParameters,
    target_torque_nm: float,
    id_values_a: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    if parameters.has_saturation_data:
        ids = np.asarray(id_values_a, dtype=float).reshape(-1)
        if target_torque_nm <= 0.0:
            return np.zeros_like(ids), np.ones_like(ids, dtype=bool)
        linear_guess = target_torque_nm / max(
            1.5 * parameters.pole_pairs * parameters.flux_pm_wb,
            1e-12,
        )
        assert parameters.ld_saturation_map is not None
        assert parameters.lq_saturation_map is not None
        map_iq_upper = min(
            parameters.ld_saturation_map.iq_axis_a[-1],
            parameters.lq_saturation_map.iq_axis_a[-1],
        )
        iq_bound = min(
            max(4.0 * linear_guess, 2.0 * float(np.max(np.abs(ids))), 1.0),
            float(map_iq_upper),
        )
        # The imported Map axes define all possible interpolation breakpoints.
        # A modest guard grid locates the first torque crossing; the following
        # bisection retains the same torque tolerance as the old 257-point scan.
        axis_points = max(
            len(parameters.ld_saturation_map.iq_axis_a),
            len(parameters.lq_saturation_map.iq_axis_a),
        )
        crossing_points = min(257, max(65, 4 * axis_points + 1))
        fractions = np.linspace(0.0, 1.0, crossing_points)
        candidates = np.broadcast_to(
            iq_bound * fractions[None, :], (ids.size, fractions.size)
        )
        candidate_ids = np.broadcast_to(ids[:, None], candidates.shape)
        torque = electromagnetic_torque(candidate_ids, candidates, parameters)
        crosses = np.isfinite(torque) & (torque >= target_torque_nm)
        has_crossing = np.any(crosses, axis=1)
        upper_index = np.argmax(crosses, axis=1)
        upper_index = np.maximum(upper_index, 1)
        row = np.arange(ids.size)
        lower = candidates[row, upper_index - 1]
        upper = candidates[row, upper_index]
        for _ in range(32):
            middle = 0.5 * (lower + upper)
            middle_torque = electromagnetic_torque(ids, middle, parameters)
            above = middle_torque >= target_torque_nm
            upper = np.where(above, middle, upper)
            lower = np.where(above, lower, middle)
        iq_values = 0.5 * (lower + upper)
        actual = electromagnetic_torque(ids, iq_values, parameters)
        tolerance = max(1e-7, abs(target_torque_nm) * 2e-7)
        valid = (
            has_crossing
            & np.isfinite(iq_values)
            & (iq_values >= 0.0)
            & (np.abs(actual - target_torque_nm) <= tolerance)
        )
        iq_values = np.where(valid, iq_values, np.nan)
        return iq_values, valid
    coefficient = torque_per_iq(id_values_a, parameters)
    threshold = max(
        np.finfo(float).eps * 100.0,
        abs(parameters.flux_pm_wb)
        * parameters.pole_pairs
        * np.finfo(float).eps
        * 100.0,
    )
    valid = coefficient > threshold
    iq_values = np.divide(
        target_torque_nm,
        coefficient,
        out=np.full_like(id_values_a, np.nan, dtype=float),
        where=valid,
    )
    valid &= np.isfinite(iq_values) & (iq_values >= 0.0)
    return iq_values, valid


def _numeric_reference_point(
    parameters: MotorParameters,
    target_torque_nm: float,
    *,
    kind: str,
    speed_rpm: float,
    grid_points: int = 1001,
    limits: ResolvedCharacteristicLimits | None = None,
    current_hint_a: float | None = None,
) -> ReferencePoint:
    if not np.isfinite(target_torque_nm) or target_torque_nm < 0:
        raise ValueError("目标转矩必须是有限的非负数。")
    resolved = _resolved_limits(parameters, limits)
    bound = _id_search_bound(parameters, resolved, current_hint_a)
    id_lower = -bound
    id_upper = bound
    if parameters.has_saturation_data:
        assert parameters.ld_saturation_map is not None
        assert parameters.lq_saturation_map is not None
        id_lower = max(
            id_lower,
            parameters.ld_saturation_map.id_axis_a[0],
            parameters.lq_saturation_map.id_axis_a[0],
        )
        id_upper = min(
            id_upper,
            parameters.ld_saturation_map.id_axis_a[-1],
            parameters.lq_saturation_map.id_axis_a[-1],
        )
        if id_upper <= id_lower:
            raise ArithmeticError("饱和电感Map没有可用的Id搜索范围。")
    search_points = max(101, int(grid_points) | 1)
    if parameters.has_saturation_data:
        assert parameters.ld_saturation_map is not None
        assert parameters.lq_saturation_map is not None
        id_cells = max(
            len(parameters.ld_saturation_map.id_axis_a) - 1,
            len(parameters.lq_saturation_map.id_axis_a) - 1,
        )
        # The interpolation model is piecewise bilinear. Eight brackets per
        # imported Id cell plus bounded refinement preserves the final xatol
        # while avoiding a fixed 1001-point scan for small engineering Maps.
        search_points = min(search_points, max(201, 8 * id_cells + 1))
    ids = np.linspace(id_lower, id_upper, search_points)
    iqs, valid = _candidate_iq(parameters, target_torque_nm, ids)

    def array_objective(
        candidate_ids: np.ndarray,
        candidate_iqs: np.ndarray,
        candidate_valid: np.ndarray,
    ) -> np.ndarray:
        if kind == "MTPA":
            values = candidate_ids**2 + candidate_iqs**2
        elif kind == "MTPV":
            ud_v, uq_v = dq_voltage(
                candidate_ids, candidate_iqs, speed_rpm, parameters
            )
            tie_scale = (
                np.finfo(float).eps
                * max(resolved.max_voltage_dq_v**2, 1.0)
                / max(resolved.max_current_vector_a**2, 1.0)
            )
            values = (
                ud_v**2
                + uq_v**2
                + tie_scale * (candidate_ids**2 + candidate_iqs**2)
            )
        else:
            raise ValueError(f"未知理论轨迹类型：{kind}")
        return np.where(candidate_valid, values, np.inf)

    objective = array_objective(ids, iqs, valid)
    if not np.any(np.isfinite(objective)):
        raise ArithmeticError(f"无法为 {target_torque_nm:g} N·m 求得{kind}参考点。")
    best_index = int(np.argmin(objective))
    step = (id_upper - id_lower) / (len(ids) - 1)
    lower = max(id_lower, float(ids[best_index] - 2.0 * step))
    upper = min(id_upper, float(ids[best_index] + 2.0 * step))

    def scalar_objective(id_a: float) -> float:
        id_array = np.array([id_a], dtype=float)
        iq_array, point_valid = _candidate_iq(
            parameters, target_torque_nm, id_array
        )
        if not point_valid[0]:
            return 1e300
        iq_a = float(iq_array[0])
        if kind == "MTPA":
            return id_a**2 + iq_a**2
        ud_v, uq_v = dq_voltage(id_a, iq_a, speed_rpm, parameters)
        voltage_squared = float(ud_v) ** 2 + float(uq_v) ** 2
        tie_scale = (
            np.finfo(float).eps
            * max(resolved.max_voltage_dq_v**2, 1.0)
            / max(resolved.max_current_vector_a**2, 1.0)
        )
        return voltage_squared + tie_scale * (id_a**2 + iq_a**2)

    if parameters.has_saturation_data:
        # SciPy's scalar optimizer repeatedly rebuilt the torque root for one
        # Id at a time. Three vectorized local refinements reach sub-milliamp
        # Id resolution on typical Maps with far fewer interpolation calls.
        center = float(ids[best_index])
        local_step = step
        best_iq = float(iqs[best_index])
        for samples in (101, 81, 61):
            local_lower = max(id_lower, center - 2.0 * local_step)
            local_upper = min(id_upper, center + 2.0 * local_step)
            local_ids = np.linspace(local_lower, local_upper, samples)
            local_iqs, local_valid = _candidate_iq(
                parameters, target_torque_nm, local_ids
            )
            local_objective = array_objective(
                local_ids, local_iqs, local_valid
            )
            local_best = int(np.argmin(local_objective))
            center = float(local_ids[local_best])
            best_iq = float(local_iqs[local_best])
            local_step = (local_upper - local_lower) / max(samples - 1, 1)
        id_a = center
        iq_values = np.array([best_iq], dtype=float)
        point_valid = np.array([np.isfinite(best_iq)], dtype=bool)
    else:
        candidates = [float(ids[best_index]), lower, upper]
        if upper > lower:
            refined = minimize_scalar(
                scalar_objective,
                bounds=(lower, upper),
                method="bounded",
                options={
                    "xatol": max(
                        1e-11, resolved.max_current_vector_a * 1e-11
                    ),
                    "maxiter": 200,
                },
            )
            if refined.success:
                candidates.append(float(refined.x))
        id_a = min(candidates, key=scalar_objective)
        iq_values, point_valid = _candidate_iq(
            parameters, target_torque_nm, np.array([id_a], dtype=float)
        )
    if not point_valid[0]:
        raise ArithmeticError(f"{kind}局部优化返回了不可行点。")
    iq_a = float(iq_values[0])
    torque_nm = float(electromagnetic_torque(id_a, iq_a, parameters))
    ud_v, uq_v = dq_voltage(id_a, iq_a, speed_rpm, parameters)
    us_v = float(voltage_magnitude(ud_v, uq_v))
    return ReferencePoint(
        kind=kind,
        speed_rpm=float(speed_rpm) if kind == "MTPV" else float("nan"),
        torque_nm=torque_nm,
        id_a=id_a,
        iq_a=iq_a,
        is_a=hypot(id_a, iq_a),
        us_v=us_v if kind == "MTPV" else float("nan"),
    )


def solve_mtpa_point(
    parameters: MotorParameters,
    target_torque_nm: float,
    limits: ResolvedCharacteristicLimits | None = None,
    *,
    current_hint_a: float | None = None,
) -> ReferencePoint:
    """Minimize stator-current magnitude for the requested torque."""

    return _numeric_reference_point(
        parameters,
        target_torque_nm,
        kind="MTPA",
        speed_rpm=0.0,
        limits=limits,
        current_hint_a=current_hint_a,
    )


def solve_mtpv_point(
    parameters: MotorParameters,
    speed_rpm: float,
    target_torque_nm: float,
    limits: ResolvedCharacteristicLimits | None = None,
) -> ReferencePoint:
    """Minimize full-model voltage magnitude for torque at one speed."""

    if not np.isfinite(speed_rpm) or speed_rpm < 0:
        raise ValueError("MTPV参考转速必须是有限的非负数。")
    return _numeric_reference_point(
        parameters,
        target_torque_nm,
        kind="MTPV",
        speed_rpm=float(speed_rpm),
        limits=limits,
    )


def generate_mtpa_trajectory(
    parameters: MotorParameters,
    *,
    limits: ResolvedCharacteristicLimits | None = None,
    samples: int = 161,
    max_torque_nm: float | None = None,
) -> pd.DataFrame:
    """Generate a current-limited theoretical MTPA reference trajectory."""

    maximum = (
        _maximum_mtpa_torque_at_current_limit(parameters, limits)
        if max_torque_nm is None
        else float(max_torque_nm)
    )
    targets = np.linspace(0.0, max(maximum, 0.0), max(2, int(samples)))
    points = [
        solve_mtpa_point(parameters, float(target), limits)
        for target in targets
    ]
    return pd.DataFrame.from_records(
        [point.as_record() for point in points],
        columns=REFERENCE_COLUMNS,
    )


def generate_local_mtpv_trajectory(
    parameters: MotorParameters,
    speed_rpm: float,
    *,
    limits: ResolvedCharacteristicLimits | None = None,
    samples: int = 121,
    max_torque_nm: float | None = None,
) -> pd.DataFrame:
    """Generate the MTPV locus at the currently selected speed."""

    maximum = (
        _maximum_mtpa_torque_at_current_limit(parameters, limits)
        if max_torque_nm is None
        else float(max_torque_nm)
    )
    targets = np.linspace(0.0, max(maximum, 0.0), max(2, int(samples)))
    points = [
        solve_mtpv_point(parameters, float(speed_rpm), float(target), limits)
        for target in targets
    ]
    return pd.DataFrame.from_records(
        [point.as_record() for point in points],
        columns=REFERENCE_COLUMNS,
    )


def generate_mtpv_envelope(
    parameters: MotorParameters,
    operating_points: pd.DataFrame,
    limits: ResolvedCharacteristicLimits | None = None,
) -> pd.DataFrame:
    """Create a high-speed MTPV reference envelope independent of actual Id/Iq.

    For each voltage-active high-speed operating torque, this computes the
    voltage-minimizing current combination at that row's speed.  If the supplied
    case never reaches its voltage limit, the upper third of valid speeds is
    used so the theoretical reference remains available.
    """

    valid = operating_points.dropna(subset=["Torque_Nm", "Id_A", "Iq_A"])
    if valid.empty:
        return pd.DataFrame(columns=REFERENCE_COLUMNS)
    if "VoltageConstraintActive" in valid.columns:
        high_speed = valid[valid["VoltageConstraintActive"].astype(bool)]
    else:
        high_speed = valid[
            valid["ActiveConstraint"].astype(str).str.contains("电压", regex=False)
        ]
    if len(high_speed) < 4:
        count = max(4, len(valid) // 3)
        high_speed = valid.tail(min(count, len(valid)))

    points = [
        solve_mtpv_point(
            parameters,
            float(row["Speed_rpm"]),
            float(row["Torque_Nm"]),
            limits,
        )
        for _, row in high_speed.iterrows()
    ]
    return pd.DataFrame.from_records(
        [point.as_record() for point in points],
        columns=REFERENCE_COLUMNS,
    )


def reference_distance_a(
    id_a: float,
    iq_a: float,
    reference: ReferencePoint,
) -> float:
    return hypot(id_a - reference.id_a, iq_a - reference.iq_a)
