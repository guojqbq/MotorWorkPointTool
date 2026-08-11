"""Maximum-torque envelope solver.

For each speed, Id is scanned over its physically allowed range.  The feasible
Iq interval is obtained analytically from current, voltage, and optional power
constraints.  A second dense scan and a bounded SciPy refinement are performed
around the best coarse point.  No constant-torque/constant-power curve stitching
is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable

import numpy as np
import pandas as pd

try:
    from scipy.optimize import minimize_scalar
except ImportError:  # pragma: no cover - used only in minimal environments
    from calculation.scalar_optimize import minimize_scalar

from calculation.equations import (
    copper_loss,
    current_magnitude,
    dq_voltage,
    electromagnetic_torque,
    mechanical_power,
    torque_per_iq,
    voltage_magnitude,
)
from calculation.region_classifier import classify_operating_point
from calculation.reference_trajectories import (
    reference_distance_a,
    solve_mtpa_point,
    solve_mtpv_point,
)
from models.motor_parameters import MotorParameters
from models.operating_point import (
    OperatingPoint,
    operating_points_to_dataframe,
)
from models.resolved_characteristic_limits import ResolvedCharacteristicLimits


ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]
DiagnosticCallback = Callable[[dict], None]


@dataclass(frozen=True, slots=True)
class SolverSettings:
    coarse_id_points: int = 801
    fine_id_points: int = 401
    constraint_tolerance: float = 1e-8
    max_iterations: int = 200
    timeout_seconds: float = 30.0

    def validated(self) -> "SolverSettings":
        if self.coarse_id_points < 21 or self.fine_id_points < 21:
            raise ValueError("Id搜索网格点数至少为21。")
        if self.max_iterations < 1:
            raise ValueError("求解器最大迭代次数必须大于零。")
        if self.timeout_seconds <= 0.0:
            raise ValueError("求解器超时阈值必须大于零。")
        return self


class EnvelopeSolver:
    def __init__(
        self,
        parameters: MotorParameters,
        settings: SolverSettings | None = None,
        limits: ResolvedCharacteristicLimits | None = None,
    ) -> None:
        self.parameters = parameters.validated()
        self.settings = (settings or SolverSettings()).validated()
        self.limits = (
            limits or ResolvedCharacteristicLimits.from_legacy_motor(parameters)
        ).validated()

    def solve(
        self,
        *,
        speed_grid_rpm: np.ndarray | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        diagnostic_callback: DiagnosticCallback | None = None,
    ) -> pd.DataFrame:
        if speed_grid_rpm is None:
            speeds = np.linspace(
                0.0,
                self.limits.max_speed_rpm,
                self.parameters.speed_points,
                endpoint=True,
            )
        else:
            speeds = np.asarray(speed_grid_rpm, dtype=float).reshape(-1)
            if (
                speeds.size < 2
                or not np.all(np.isfinite(speeds))
                or np.any(np.diff(speeds) <= 0.0)
                or speeds[0] < 0.0
                or speeds[-1] > self.limits.max_speed_rpm * (1.0 + 1e-12)
            ):
                raise ValueError("自定义转速网格必须为范围内严格递增的有限数组。")
        points: list[OperatingPoint] = []
        total = len(speeds)
        feasible_count = 0
        failed_count = 0
        for index, speed_rpm in enumerate(speeds):
            if cancel_check is not None and cancel_check():
                raise InterruptedError("计算已取消。")
            point_started = perf_counter()
            try:
                point = self.solve_speed(float(speed_rpm))
            except Exception as exc:
                failed_count += 1
                if diagnostic_callback is not None:
                    diagnostic_callback(
                        {
                            "stage": "external",
                            "speed_index": index,
                            "torque_index": -1,
                            "speed_rpm": float(speed_rpm),
                            "torque_nm": float("nan"),
                            "elapsed_seconds": perf_counter() - point_started,
                            "status": f"Error:{type(exc).__name__}",
                            "feasible_count": feasible_count,
                            "failed_count": failed_count,
                            "completed": index,
                            "total": total,
                        }
                    )
                raise
            elapsed = perf_counter() - point_started
            if elapsed > self.settings.timeout_seconds:
                raise TimeoutError(
                    f"外特性 speed_index={index}、speed={float(speed_rpm):g} rpm "
                    f"求解耗时 {elapsed:.3f} s，超过 "
                    f"{self.settings.timeout_seconds:.3f} s 限制。"
                )
            points.append(point)
            feasible_count += int(point.valid)
            failed_count += int(not point.valid)
            if diagnostic_callback is not None:
                diagnostic_callback(
                    {
                        "stage": "external",
                        "speed_index": index,
                        "torque_index": -1,
                        "speed_rpm": float(speed_rpm),
                        "torque_nm": float(point.torque_nm),
                        "elapsed_seconds": elapsed,
                        "status": "Converged" if point.valid else "Infeasible",
                        "feasible_count": feasible_count,
                        "failed_count": failed_count,
                        "completed": index + 1,
                        "total": total,
                    }
                )
            if progress_callback is not None:
                progress_callback(index + 1, total)
        return operating_points_to_dataframe(points)

    def solve_speed(self, speed_rpm: float) -> OperatingPoint:
        p = self.parameters
        limits = self.limits
        id_lower = max(
            -limits.max_current_vector_a,
            p.id_min_peak_a
            if p.id_min_peak_a is not None
            else -limits.max_current_vector_a,
        )
        id_upper = limits.max_current_vector_a

        coarse_ids = np.linspace(
            id_lower, id_upper, self.settings.coarse_id_points
        )
        coarse_torque, coarse_iq = self._evaluate_id_candidates(
            coarse_ids, speed_rpm
        )
        if not np.any(np.isfinite(coarse_torque)):
            return OperatingPoint.infeasible(speed_rpm)

        best_index = int(np.nanargmax(coarse_torque))
        coarse_step = (id_upper - id_lower) / (
            self.settings.coarse_id_points - 1
        )
        fine_lower = max(id_lower, coarse_ids[best_index] - 1.5 * coarse_step)
        fine_upper = min(id_upper, coarse_ids[best_index] + 1.5 * coarse_step)
        fine_ids = np.linspace(
            fine_lower, fine_upper, self.settings.fine_id_points
        )
        fine_torque, fine_iq = self._evaluate_id_candidates(fine_ids, speed_rpm)
        fine_best = int(np.nanargmax(fine_torque))

        candidates: list[tuple[float, float, float]] = [
            (
                float(fine_torque[fine_best]),
                float(fine_ids[fine_best]),
                float(fine_iq[fine_best]),
            )
        ]

        if fine_upper > fine_lower:
            result = minimize_scalar(
                lambda id_value: self._negative_torque(float(id_value), speed_rpm),
                bounds=(fine_lower, fine_upper),
                method="bounded",
                options={
                    "xatol": max(
                        1e-10, limits.max_current_vector_a * 1e-10
                    ),
                    "maxiter": self.settings.max_iterations,
                },
            )
            torque_value, iq_value = self._evaluate_id_candidates(
                np.array([float(result.x)]), speed_rpm
            )
            if np.isfinite(torque_value[0]):
                candidates.append(
                    (
                        float(torque_value[0]),
                        float(result.x),
                        float(iq_value[0]),
                    )
                )

        _, id_a, iq_a = max(candidates, key=lambda item: item[0])
        return self._make_operating_point(speed_rpm, id_a, iq_a)

    def _negative_torque(self, id_a: float, speed_rpm: float) -> float:
        torque_values, _ = self._evaluate_id_candidates(
            np.array([id_a], dtype=float), speed_rpm
        )
        if not np.isfinite(torque_values[0]):
            return 1e30
        return -float(torque_values[0])

    def _evaluate_id_candidates(
        self, id_values_a: np.ndarray, speed_rpm: float
    ) -> tuple[np.ndarray, np.ndarray]:
        p = self.parameters
        limits = self.limits
        ids = np.asarray(id_values_a, dtype=float)
        if p.has_saturation_data:
            return self._evaluate_saturated_id_candidates(ids, speed_rpm)
        iq_current_upper = np.sqrt(
            np.maximum(limits.max_current_vector_a**2 - ids**2, 0.0)
        )

        omega_m = speed_rpm * (2.0 * np.pi / 60.0)
        omega_e = p.pole_pairs * omega_m
        a = p.rs_ohm**2 + (omega_e * p.lq_h) ** 2
        b = (
            2.0
            * p.rs_ohm
            * omega_e
            * (p.flux_pm_wb + (p.ld_h - p.lq_h) * ids)
        )
        c = (
            (p.rs_ohm * ids) ** 2
            + (omega_e * (p.ld_h * ids + p.flux_pm_wb)) ** 2
            - limits.max_voltage_dq_v**2
        )

        if a <= np.finfo(float).eps:
            voltage_lower = np.full_like(ids, -np.inf)
            voltage_upper = np.full_like(ids, np.inf)
            voltage_feasible = c <= 0
        else:
            discriminant = b**2 - 4.0 * a * c
            voltage_feasible = discriminant >= 0.0
            sqrt_discriminant = np.sqrt(np.maximum(discriminant, 0.0))
            voltage_lower = (-b - sqrt_discriminant) / (2.0 * a)
            voltage_upper = (-b + sqrt_discriminant) / (2.0 * a)

        iq_lower = np.maximum(0.0, voltage_lower)
        iq_upper = np.minimum(iq_current_upper, voltage_upper)

        torque_coefficient = torque_per_iq(ids, p)
        positive_torque_coefficient = torque_coefficient > 0.0

        if p.pmax_w is not None and omega_m > 0.0:
            with np.errstate(divide="ignore", invalid="ignore"):
                power_upper = p.pmax_w / (omega_m * torque_coefficient)
            power_upper[~positive_torque_coefficient] = -np.inf
            iq_upper = np.minimum(iq_upper, power_upper)

        feasible = (
            voltage_feasible
            & positive_torque_coefficient
            & (iq_upper >= iq_lower)
            & (iq_upper >= 0.0)
        )

        # Move a tiny distance inside the feasible interval so exported values
        # do not exceed a boundary because of floating-point roundoff.
        inward = max(1e-10, limits.max_current_vector_a * 1e-10)
        safe_iq = np.where(
            feasible,
            np.maximum(iq_lower, iq_upper - inward),
            np.nan,
        )
        torque = torque_coefficient * safe_iq
        torque[~feasible] = np.nan
        return torque, safe_iq

    def _evaluate_saturated_id_candidates(
        self, ids: np.ndarray, speed_rpm: float
    ) -> tuple[np.ndarray, np.ndarray]:
        """Numerically maximize torque for each Id with nonlinear Ld/Lq."""

        p = self.parameters
        limits = self.limits
        iq_upper = np.sqrt(
            np.maximum(limits.max_current_vector_a**2 - ids**2, 0.0)
        )
        fractions = np.linspace(0.0, 1.0, 193)
        iqs = iq_upper[:, None] * fractions[None, :]
        id_grid = np.broadcast_to(ids[:, None], iqs.shape)
        torque = electromagnetic_torque(id_grid, iqs, p)
        ud_v, uq_v = dq_voltage(id_grid, iqs, speed_rpm, p)
        feasible = (
            np.isfinite(torque)
            & (torque >= 0.0)
            & (
                ud_v**2 + uq_v**2
                <= limits.max_voltage_dq_v**2 * (1.0 + 1e-9)
            )
        )
        if p.pmax_w is not None and speed_rpm > 0.0:
            omega_m = speed_rpm * 2.0 * np.pi / 60.0
            feasible &= torque * omega_m <= p.pmax_w * (1.0 + 1e-9)
        objective = np.where(feasible, torque, -np.inf)
        best = np.argmax(objective, axis=1)
        row = np.arange(ids.size)
        best_torque = objective[row, best]
        best_iq = iqs[row, best]
        valid = np.isfinite(best_torque)
        return (
            np.where(valid, best_torque, np.nan),
            np.where(valid, best_iq, np.nan),
        )

    def _make_operating_point(
        self, speed_rpm: float, id_a: float, iq_a: float
    ) -> OperatingPoint:
        p = self.parameters
        limits = self.limits
        torque_nm = float(electromagnetic_torque(id_a, iq_a, p))
        ld_h, lq_h = p.inductances_h(id_a, iq_a)
        ud_v_array, uq_v_array = dq_voltage(id_a, iq_a, speed_rpm, p)
        ud_v = float(ud_v_array)
        uq_v = float(uq_v_array)
        is_a = float(current_magnitude(id_a, iq_a))
        us_v = float(voltage_magnitude(ud_v, uq_v))
        power_w = float(mechanical_power(torque_nm, speed_rpm))
        copper_loss_w = float(copper_loss(id_a, iq_a, p))
        current_utilization = is_a / limits.max_current_vector_a
        voltage_utilization = us_v / limits.max_voltage_dq_v
        mtpa_reference = solve_mtpa_point(p, torque_nm, limits)
        mtpv_reference = solve_mtpv_point(
            p, speed_rpm, torque_nm, limits
        )
        mtpa_distance_a = reference_distance_a(id_a, iq_a, mtpa_reference)
        mtpv_distance_a = reference_distance_a(id_a, iq_a, mtpv_reference)
        near_mtpa = mtpa_distance_a <= max(
            0.02 * limits.max_current_vector_a, 0.25
        )
        near_mtpv = mtpv_distance_a <= max(
            0.05 * limits.max_current_vector_a, 0.5
        )
        activity_tolerance = 5e-3
        current_constraint_active = (
            current_utilization >= 1.0 - activity_tolerance
        )
        voltage_constraint_active = (
            voltage_utilization >= 1.0 - activity_tolerance
        )
        power_constraint_active = bool(
            p.pmax_w is not None
            and p.pmax_w > 0.0
            and power_w / p.pmax_w >= 1.0 - activity_tolerance
        )

        if not self._constraints_hold(
            id_a=id_a,
            is_a=is_a,
            us_v=us_v,
            power_w=power_w,
        ):
            raise ArithmeticError(
                f"{speed_rpm:.3f} rpm 的求解结果未通过约束复核。"
            )

        region, active_constraint = classify_operating_point(
            p,
            id_a=id_a,
            current_utilization=current_utilization,
            voltage_utilization=voltage_utilization,
            power_w=power_w,
            current_limit_a=limits.max_current_vector_a,
            near_mtpa=near_mtpa,
            near_mtpv=near_mtpv,
        )
        return OperatingPoint(
            speed_rpm=speed_rpm,
            torque_nm=torque_nm,
            id_a=id_a,
            iq_a=iq_a,
            ld_uh=float(ld_h) * 1e6,
            lq_uh=float(lq_h) * 1e6,
            is_a=is_a,
            ud_v=ud_v,
            uq_v=uq_v,
            us_v=us_v,
            power_kw=power_w / 1000.0,
            copper_loss_kw=copper_loss_w / 1000.0,
            current_utilization=current_utilization,
            voltage_utilization=voltage_utilization,
            near_mtpa=near_mtpa,
            near_mtpv=near_mtpv,
            mtpa_distance_a=mtpa_distance_a,
            mtpv_distance_a=mtpv_distance_a,
            mtpa_reference_id_a=mtpa_reference.id_a,
            mtpa_reference_iq_a=mtpa_reference.iq_a,
            mtpv_reference_id_a=mtpv_reference.id_a,
            mtpv_reference_iq_a=mtpv_reference.iq_a,
            current_constraint_active=current_constraint_active,
            voltage_constraint_active=voltage_constraint_active,
            power_constraint_active=power_constraint_active,
            region=region,
            active_constraint=active_constraint,
        )

    def _constraints_hold(
        self, *, id_a: float, is_a: float, us_v: float, power_w: float
    ) -> bool:
        p = self.parameters
        limits = self.limits
        tolerance = self.settings.constraint_tolerance
        if is_a > limits.max_current_vector_a * (1.0 + tolerance):
            return False
        if us_v > limits.max_voltage_dq_v * (1.0 + tolerance):
            return False
        if (
            p.id_min_peak_a is not None
            and id_a
            < p.id_min_peak_a
            - tolerance * limits.max_current_vector_a
        ):
            return False
        if (
            p.pmax_w is not None
            and power_w > p.pmax_w * (1.0 + tolerance)
        ):
            return False
        return True
