"""Normalized torque-speed operating-map solver.

For every speed the maximum torque is obtained from the independent external
envelope solver.  Internal points are then solved independently at fixed
torque; the external trajectory is never produced by stitching MTPA and MTPV
reference arrays.
"""

from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from typing import Callable

import numpy as np
import pandas as pd

from calculation.envelope_solver import EnvelopeSolver, SolverSettings
from calculation.equations import dq_voltage, electromagnetic_torque
from calculation.losses import (
    dq_flux_linkage,
    electrical_frequency_hz,
    iron_loss_w,
    motor_efficiency,
)
from calculation.operating_map_grid import (
    generate_nonuniform_ratios,
    generate_step_axis,
    generate_torque_axis,
)
from calculation.operating_region_classifier import (
    OperatingRegionClassificationConfig,
    classify_internal_operating_point,
)
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings
from models.motor_parameters import MotorParameters
from models.operating_map import (
    MAP_RESULT_COLUMNS,
    OperatingMapResult,
    dataframe_to_matrices,
)
from models.resolved_characteristic_limits import ResolvedCharacteristicLimits


ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]
DiagnosticCallback = Callable[[dict], None]

OPERATING_MAP_ALGORITHM_VERSION = "operating-map-3.2"


class OperatingMapSolver:
    """Solve fixed-torque points inside the external torque-speed envelope."""

    def __init__(
        self,
        parameters: MotorParameters,
        loss_parameters: LossModelParameters | None = None,
        settings: MapCalculationSettings | None = None,
        limits: ResolvedCharacteristicLimits | None = None,
    ) -> None:
        self.parameters = parameters.validated()
        self.loss_parameters = (loss_parameters or LossModelParameters()).validated()
        self.settings = (settings or MapCalculationSettings()).validated()
        self.limits = (
            limits or ResolvedCharacteristicLimits.from_legacy_motor(parameters)
        ).validated()
        self._reference_cache: dict[
            tuple[float, str, bytes],
            tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
        ] = {}

    def solve(
        self,
        profile: str = "preview",
        *,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        diagnostic_callback: DiagnosticCallback | None = None,
        external_characteristic: pd.DataFrame | None = None,
    ) -> OperatingMapResult:
        started_at = perf_counter()
        maximum_speed = (
            self.limits.max_speed_rpm
            if self.settings.maximum_speed_rpm is None
            else min(
                self.limits.max_speed_rpm,
                self.settings.maximum_speed_rpm,
            )
        )
        point_speed_count, point_torque_count = self.settings.grid_shape(
            profile
        )
        if (
            self.settings.grid_definition_mode == "step"
            and not self.settings.diagnostic_mode
        ):
            requested_speed_grid = generate_step_axis(
                maximum_speed, self.settings.speed_step_rpm
            )
            speed_count = int(requested_speed_grid.size)
        else:
            requested_speed_grid = None
            speed_count = point_speed_count
        effective_rs = self.loss_parameters.resistance_at_temperature(
            self.parameters.rs_ohm
        )
        calculation_parameters = replace(
            self.parameters,
            rs_ohm=effective_rs,
            max_speed_rpm=maximum_speed,
            speed_points=speed_count,
        ).validated()
        calculation_limits = replace(
            self.limits, max_speed_rpm=maximum_speed
        ).validated()

        envelope_settings = SolverSettings(
            coarse_id_points=601 if profile == "preview" else 1001,
            fine_id_points=201 if profile == "preview" else 301,
        )
        target_speed_grid = (
            requested_speed_grid
            if requested_speed_grid is not None
            else np.linspace(0.0, maximum_speed, speed_count, endpoint=True)
        )
        external = self._matching_external_rows(
            external_characteristic, target_speed_grid
        )
        external_reused = external is not None
        if external is None:
            external = EnvelopeSolver(
                calculation_parameters, envelope_settings, calculation_limits
            ).solve(
                speed_grid_rpm=requested_speed_grid,
                progress_callback=(
                    lambda done, _total: self._report(
                        progress_callback,
                        done,
                        speed_count + speed_count * point_torque_count,
                    )
                ),
                cancel_check=cancel_check,
                diagnostic_callback=(
                    None
                    if diagnostic_callback is None
                    else lambda event: diagnostic_callback(
                        {**event, "stage": "map_envelope"}
                    )
                ),
            )
        elif diagnostic_callback is not None:
            diagnostic_callback(
                {
                    "stage": "map_envelope_reused",
                    "speed_index": speed_count - 1,
                    "torque_index": -1,
                    "speed_rpm": float(target_speed_grid[-1]),
                    "torque_nm": float(external.iloc[-1]["Torque_Nm"]),
                    "elapsed_seconds": 0.0,
                    "status": "Reused",
                    "feasible_count": int(external["Torque_Nm"].notna().sum()),
                    "failed_count": int(external["Torque_Nm"].isna().sum()),
                    "completed": speed_count,
                    "total": speed_count,
                }
            )
        speeds = external["Speed_rpm"].to_numpy(dtype=float, copy=True)
        maximum_torque = external["Torque_Nm"].to_numpy(dtype=float, copy=True)
        maximum_torque = np.where(
            np.isfinite(maximum_torque) & (maximum_torque >= 0.0),
            maximum_torque,
            0.0,
        )
        global_maximum_torque = max(
            float(np.nanmax(maximum_torque)), 0.0
        )
        if global_maximum_torque <= 0.0:
            raise ArithmeticError(
                "外特性在扫描范围内没有正转矩，无法生成实际转矩轴。"
            )
        if (
            self.settings.grid_definition_mode == "step"
            and not self.settings.diagnostic_mode
        ):
            torque_axis_nm = generate_step_axis(
                global_maximum_torque, self.settings.torque_step_nm
            )
            torque_count = int(torque_axis_nm.size)
            torque_ratios = torque_axis_nm / global_maximum_torque
            if not self.settings.include_zero_torque:
                torque_axis_nm = torque_axis_nm[1:]
                torque_ratios = torque_ratios[1:]
                torque_count -= 1
        else:
            torque_count = point_torque_count
            start_ratio = (
                0.0
                if self.settings.include_zero_torque
                else 1.0 / torque_count
            )
            if self.settings.torque_axis_distribution == "nonuniform":
                torque_ratios = generate_nonuniform_ratios(torque_count)
            else:
                torque_ratios = np.linspace(0.0, 1.0, torque_count)
            if not self.settings.include_zero_torque:
                torque_ratios = (
                    start_ratio + (1.0 - start_ratio) * torque_ratios
                )
            torque_axis_nm = generate_torque_axis(
                global_maximum_torque, torque_count
            )
        if (
            self.settings.grid_definition_mode == "point_count"
            and self.settings.torque_axis_distribution == "linear"
        ):
            torque_axis_nm = np.linspace(
                start_ratio * global_maximum_torque,
                global_maximum_torque,
                torque_count,
            )
        elif (
            self.settings.grid_definition_mode == "point_count"
            and not self.settings.include_zero_torque
        ):
            torque_axis_nm = (
                start_ratio
                + (1.0 - start_ratio)
                * generate_nonuniform_ratios(torque_count)
            ) * global_maximum_torque

        records: list[dict] = []
        completed_points = 0
        feasible_count = 0
        failed_count = 0
        total_points = speed_count * torque_count
        previous_speed_ids: np.ndarray | None = None
        for speed_index, speed_rpm in enumerate(speeds):
            if cancel_check is not None and cancel_check():
                raise InterruptedError("计算已取消。")
            if self.settings.torque_axis_mode == "actual":
                requests = torque_axis_nm.copy()
                local_ratios = np.divide(
                    requests,
                    maximum_torque[speed_index],
                    out=np.full_like(requests, np.nan),
                    where=maximum_torque[speed_index] > 0.0,
                )
            else:
                requests = torque_ratios * maximum_torque[speed_index]
                local_ratios = torque_ratios
            row_initial_ids = (
                None
                if previous_speed_ids is None
                else previous_speed_ids.copy()
            )
            row_started = perf_counter()
            try:
                speed_records = self._solve_speed_row(
                    calculation_parameters,
                    calculation_limits,
                    float(speed_rpm),
                    requests,
                    local_ratios,
                    speed_index,
                    external.iloc[speed_index],
                    profile,
                    float(maximum_torque[speed_index]),
                    previous_speed_ids,
                )
            except Exception as exc:
                if diagnostic_callback is not None:
                    diagnostic_callback(
                        {
                            "stage": "internal_map",
                            "speed_index": speed_index,
                            "torque_index": -1,
                            "speed_rpm": float(speed_rpm),
                            "torque_nm": float("nan"),
                            "elapsed_seconds": perf_counter() - row_started,
                            "status": f"Error:{type(exc).__name__}",
                            "feasible_count": feasible_count,
                            "failed_count": failed_count + 1,
                            "completed": completed_points,
                            "total": total_points,
                        }
                    )
                raise
            row_elapsed = perf_counter() - row_started
            amortized_elapsed = row_elapsed / max(len(speed_records), 1)
            if amortized_elapsed > self.settings.solver_timeout_seconds:
                raise TimeoutError(
                    f"内部 Map speed_index={speed_index}、speed={float(speed_rpm):g} rpm "
                    f"该行求解耗时 {row_elapsed:.3f} s，折算单点 "
                    f"{amortized_elapsed:.3f} s，超过 "
                    f"{self.settings.solver_timeout_seconds:.3f} s 限制。"
                )
            records.extend(speed_records)
            previous_speed_ids = np.asarray(
                [
                    float(record["Id_A"])
                    if bool(record["IsFeasible"])
                    else np.nan
                    for record in speed_records
                ],
                dtype=float,
            )
            for record in speed_records:
                if cancel_check is not None and cancel_check():
                    raise InterruptedError("计算已取消。")
                completed_points += 1
                is_feasible = bool(record["IsFeasible"])
                feasible_count += int(is_feasible)
                status = str(record["SolverStatus"])
                failed_count += int(
                    status in {"Infeasible", "SolverFailed"}
                )
                if diagnostic_callback is not None:
                    diagnostic_callback(
                        {
                            "stage": "internal_map",
                            "speed_index": int(record["SpeedIndex"]),
                            "torque_index": int(record["TorqueIndex"]),
                            "speed_rpm": float(record["Speed_rpm"]),
                            "torque_nm": float(record["TorqueRequest_Nm"]),
                            "elapsed_seconds": amortized_elapsed,
                            "row_elapsed_seconds": row_elapsed,
                            "status": status,
                            "initial_id_a": float(
                                row_initial_ids[int(record["TorqueIndex"])]
                                if row_initial_ids is not None
                                and np.isfinite(
                                    row_initial_ids[int(record["TorqueIndex"])]
                                )
                                else external.iloc[speed_index].get(
                                    "Id_A", np.nan
                                )
                            ),
                            "initial_iq_a": float(
                                external.iloc[speed_index].get("Iq_A", np.nan)
                            ),
                            "iterations": (
                                32 if calculation_parameters.has_saturation_data else 0
                            ),
                            "warm_start_used": bool(
                                calculation_parameters.has_saturation_data
                                and row_initial_ids is not None
                                and np.isfinite(
                                    row_initial_ids[int(record["TorqueIndex"])]
                                )
                            ),
                            "feasible_count": feasible_count,
                            "failed_count": failed_count,
                            "completed": completed_points,
                            "total": total_points,
                        }
                    )
                self._report(
                    progress_callback,
                    completed_points if external_reused else speed_count + completed_points,
                    total_points if external_reused else speed_count + total_points,
                )

        dataframe = pd.DataFrame.from_records(records, columns=MAP_RESULT_COLUMNS)
        shape = (speed_count, torque_count)
        return OperatingMapResult(
            profile=profile,
            speed_grid_rpm=speeds,
            torque_ratio_grid=torque_ratios,
            torque_axis_nm=torque_axis_nm,
            torque_coordinate_mode=self.settings.torque_axis_mode,
            maximum_torque_nm=maximum_torque,
            dataframe=dataframe,
            matrices=dataframe_to_matrices(dataframe, shape),
            external_characteristic=external.reset_index(drop=True).copy(),
            algorithm_version=OPERATING_MAP_ALGORITHM_VERSION,
            calculation_elapsed_seconds=perf_counter() - started_at,
        )

    def solve_fixed_torque_point(
        self, speed_rpm: float, target_torque_nm: float
    ) -> dict:
        """Solve one high-priority fixed-torque point without a map sweep."""

        if not np.isfinite(speed_rpm) or speed_rpm < 0:
            raise ValueError("转速必须为有限非负数。")
        if not np.isfinite(target_torque_nm) or target_torque_nm < 0:
            raise ValueError("目标转矩必须为有限非负数。")
        effective_parameters = replace(
            self.parameters,
            rs_ohm=self.loss_parameters.resistance_at_temperature(
                self.parameters.rs_ohm
            ),
        ).validated()
        records = self._solve_speed_row(
            effective_parameters,
            self.limits,
            float(speed_rpm),
            np.array([float(target_torque_nm)]),
            np.array([np.nan]),
            0,
            pd.Series({"Id_A": np.nan, "Iq_A": np.nan}),
            "preview",
            float("inf"),
        )
        return records[0]

    @staticmethod
    def _report(
        callback: ProgressCallback | None, done: int, total: int
    ) -> None:
        if callback is not None:
            callback(done, total)

    @staticmethod
    def _matching_external_rows(
        external: pd.DataFrame | None, target_speeds: np.ndarray
    ) -> pd.DataFrame | None:
        """Reuse an identical envelope grid; never interpolate numerical results."""

        if external is None or not {"Speed_rpm", "Torque_Nm"}.issubset(
            external.columns
        ):
            return None
        source_speeds = external["Speed_rpm"].to_numpy(dtype=float)
        if source_speeds.size == 0 or not np.all(np.isfinite(source_speeds)):
            return None
        scale = max(float(np.max(np.abs(target_speeds))), 1.0)
        selected: list[int] = []
        for speed in np.asarray(target_speeds, dtype=float):
            nearest = int(np.argmin(np.abs(source_speeds - speed)))
            if not np.isclose(
                source_speeds[nearest], speed, rtol=0.0, atol=scale * 1e-10
            ):
                return None
            selected.append(nearest)
        return external.iloc[selected].reset_index(drop=True).copy()

    def _solve_speed_row(
        self,
        parameters: MotorParameters,
        limits: ResolvedCharacteristicLimits,
        speed_rpm: float,
        requests: np.ndarray,
        torque_ratios: np.ndarray,
        speed_index: int,
        external_row: pd.Series,
        profile: str,
        maximum_torque_nm: float,
        previous_speed_ids: np.ndarray | None = None,
    ) -> list[dict]:
        count = len(requests)
        current_limit = limits.max_current_vector_a
        id_lower = max(
            -current_limit,
            parameters.id_min_peak_a
            if parameters.id_min_peak_a is not None
            else -current_limit,
        )
        if parameters.has_saturation_data:
            return self._solve_speed_row_saturated(
                parameters,
                limits,
                speed_rpm,
                requests,
                torque_ratios,
                speed_index,
                external_row,
                profile,
                maximum_torque_nm,
                id_lower,
                previous_speed_ids,
            )
        grid_points = 801 if profile == "preview" else 1601
        ids = np.linspace(id_lower, current_limit, grid_points)
        torque_coefficient = (
            1.5
            * parameters.pole_pairs
            * (
                parameters.flux_pm_wb
                + (parameters.ld_h - parameters.lq_h) * ids
            )
        )
        coefficient_valid = torque_coefficient > self._coefficient_threshold(parameters)
        iqs = np.divide(
            requests[:, None],
            torque_coefficient[None, :],
            out=np.full((count, len(ids)), np.nan),
            where=coefficient_valid[None, :],
        )
        candidate = np.isfinite(iqs) & (iqs >= 0.0)
        current_squared = ids[None, :] ** 2 + iqs**2
        candidate &= current_squared <= current_limit**2 * (1.0 + 1e-9)

        omega_e = (
            parameters.pole_pairs * speed_rpm * 2.0 * np.pi / 60.0
        )
        ud = parameters.rs_ohm * ids[None, :] - omega_e * parameters.lq_h * iqs
        uq = (
            parameters.rs_ohm * iqs
            + omega_e * (parameters.ld_h * ids[None, :] + parameters.flux_pm_wb)
        )
        voltage_squared = ud**2 + uq**2
        candidate &= (
            voltage_squared
            <= limits.max_voltage_dq_v**2 * (1.0 + 1e-9)
        )
        inside_envelope = requests <= maximum_torque_nm + max(
            1e-8, abs(maximum_torque_nm) * 1e-9
        )
        candidate &= inside_envelope[:, None]
        output_power = requests * speed_rpm * 2.0 * np.pi / 60.0
        if parameters.pmax_w is not None:
            candidate &= (
                output_power[:, None] <= parameters.pmax_w * (1.0 + 1e-9)
            )

        objective = np.where(candidate, current_squared, np.inf)
        best_indices = np.argmin(objective, axis=1)
        feasible = np.isfinite(objective[np.arange(count), best_indices])
        selected_id = ids[best_indices]
        selected_iq = iqs[np.arange(count), best_indices]

        # Refine all torque points together in a narrow interval around their
        # coarse optimum.  This gives stable constraint-boundary points without
        # thousands of scalar optimizer calls.
        grid_step = (current_limit - id_lower) / max(grid_points - 1, 1)
        offsets = np.linspace(-1.2, 1.2, 81) * grid_step
        refined_ids = np.clip(selected_id[:, None] + offsets[None, :], id_lower, current_limit)
        refined_coefficient = (
            1.5
            * parameters.pole_pairs
            * (
                parameters.flux_pm_wb
                + (parameters.ld_h - parameters.lq_h) * refined_ids
            )
        )
        refined_iq = np.divide(
            requests[:, None],
            refined_coefficient,
            out=np.full_like(refined_ids, np.nan),
            where=refined_coefficient > self._coefficient_threshold(parameters),
        )
        refined_current_squared = refined_ids**2 + refined_iq**2
        refined_ud = (
            parameters.rs_ohm * refined_ids
            - omega_e * parameters.lq_h * refined_iq
        )
        refined_uq = (
            parameters.rs_ohm * refined_iq
            + omega_e
            * (parameters.ld_h * refined_ids + parameters.flux_pm_wb)
        )
        refined_voltage_squared = refined_ud**2 + refined_uq**2
        refined_valid = (
            np.isfinite(refined_iq)
            & (refined_iq >= 0.0)
            & (refined_current_squared <= current_limit**2 * (1.0 + 1e-9))
            & (
                refined_voltage_squared
                <= limits.max_voltage_dq_v**2 * (1.0 + 1e-9)
            )
            & inside_envelope[:, None]
        )
        if parameters.pmax_w is not None:
            refined_valid &= (
                output_power[:, None] <= parameters.pmax_w * (1.0 + 1e-9)
            )
        refined_objective = np.where(
            refined_valid, refined_current_squared, np.inf
        )
        refined_best = np.argmin(refined_objective, axis=1)
        refined_feasible = np.isfinite(
            refined_objective[np.arange(count), refined_best]
        )
        use_refined = feasible & refined_feasible
        selected_id = np.where(
            use_refined, refined_ids[np.arange(count), refined_best], selected_id
        )
        selected_iq = np.where(
            use_refined, refined_iq[np.arange(count), refined_best], selected_iq
        )

        # Close to a current/voltage intersection the feasible Id interval can
        # be thinner than the global coarse grid.  Re-solve only those missed
        # inside-envelope targets on a dense local grid seeded by the
        # independently optimized external point.
        missed_positions = np.flatnonzero(inside_envelope & ~feasible)
        external_id = float(external_row.get("Id_A", np.nan))
        if missed_positions.size and np.isfinite(external_id):
            local_ids = np.linspace(
                max(id_lower, external_id - 12.0 * grid_step),
                min(current_limit, external_id + 12.0 * grid_step),
                801,
            )
            local_coefficient = (
                1.5
                * parameters.pole_pairs
                * (
                    parameters.flux_pm_wb
                    + (parameters.ld_h - parameters.lq_h) * local_ids
                )
            )
            local_iq = np.divide(
                requests[missed_positions, None],
                local_coefficient[None, :],
                out=np.full(
                    (missed_positions.size, local_ids.size), np.nan
                ),
                where=(
                    local_coefficient[None, :]
                    > self._coefficient_threshold(parameters)
                ),
            )
            local_current_squared = local_ids[None, :] ** 2 + local_iq**2
            local_ud = (
                parameters.rs_ohm * local_ids[None, :]
                - omega_e * parameters.lq_h * local_iq
            )
            local_uq = (
                parameters.rs_ohm * local_iq
                + omega_e
                * (
                    parameters.ld_h * local_ids[None, :]
                    + parameters.flux_pm_wb
                )
            )
            local_valid = (
                np.isfinite(local_iq)
                & (local_iq >= 0.0)
                & (
                    local_current_squared
                    <= current_limit**2 * (1.0 + 1e-9)
                )
                & (
                    local_ud**2 + local_uq**2
                    <= limits.max_voltage_dq_v**2 * (1.0 + 1e-9)
                )
            )
            if parameters.pmax_w is not None:
                local_valid &= (
                    output_power[missed_positions, None]
                    <= parameters.pmax_w * (1.0 + 1e-9)
                )
            local_objective = np.where(
                local_valid, local_current_squared, np.inf
            )
            local_best = np.argmin(local_objective, axis=1)
            local_feasible = np.isfinite(
                local_objective[
                    np.arange(missed_positions.size), local_best
                ]
            )
            recovered = missed_positions[local_feasible]
            if recovered.size:
                recovered_best = local_best[local_feasible]
                selected_id[recovered] = local_ids[recovered_best]
                selected_iq[recovered] = local_iq[
                    np.flatnonzero(local_feasible), recovered_best
                ]
                feasible[recovered] = True

        # The exact maximum-torque sample comes from the independently solved
        # external envelope.  This also prevents a thin feasible boundary from
        # being missed by the fixed-torque search grid.
        boundary_positions = (
            np.flatnonzero(
                np.isclose(
                    requests,
                    maximum_torque_nm,
                    rtol=1e-7,
                    atol=max(1e-8, abs(maximum_torque_nm) * 1e-7),
                )
            )
            if np.isfinite(maximum_torque_nm)
            else np.array([], dtype=int)
        )
        if boundary_positions.size:
            external_iq = float(external_row.get("Iq_A", np.nan))
            if np.isfinite(external_id) and np.isfinite(external_iq):
                boundary_index = int(boundary_positions[-1])
                selected_id[boundary_index] = external_id
                selected_iq[boundary_index] = external_iq
                feasible[boundary_index] = True

        mtpa_id, mtpa_iq, mtpv_id, mtpv_iq = self._reference_points(
            parameters, limits, speed_rpm, requests, profile
        )

        records: list[dict] = []
        for torque_index, request in enumerate(requests):
            if not inside_envelope[torque_index]:
                records.append(
                    self._infeasible_record(
                        speed_index,
                        torque_index,
                        float(torque_ratios[torque_index]),
                        speed_rpm,
                        float(request),
                        "OutsideEnvelope",
                    )
                )
                continue
            below_minimum = (
                request < self.settings.minimum_torque_nm
                and not (
                    self.settings.include_zero_torque
                    and np.isclose(request, 0.0, atol=1e-12)
                )
            )
            point_feasible = bool(feasible[torque_index]) and not below_minimum
            if not point_feasible:
                records.append(
                    self._infeasible_record(
                        speed_index,
                        torque_index,
                        float(torque_ratios[torque_index]),
                        speed_rpm,
                        float(request),
                        "BelowMinimumTorque" if below_minimum else "Infeasible",
                    )
                )
                continue
            records.append(
                self._build_record(
                    parameters,
                    limits,
                    speed_index,
                    torque_index,
                    float(torque_ratios[torque_index]),
                    speed_rpm,
                    float(request),
                    float(selected_id[torque_index]),
                    float(selected_iq[torque_index]),
                    mtpa_id,
                    mtpa_iq,
                    mtpv_id,
                    mtpv_iq,
                )
            )
        self._attach_reference_columns(
            records, mtpa_id, mtpa_iq, mtpv_id, mtpv_iq
        )
        return records

    @staticmethod
    def _saturated_iq_for_torque(
        parameters: MotorParameters,
        target_nm: np.ndarray,
        id_a: np.ndarray,
        iq_upper_a: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Solve Te(Id, Iq)=target by vectorized bisection within Map range."""

        target, ids, upper = np.broadcast_arrays(
            np.asarray(target_nm, dtype=float),
            np.asarray(id_a, dtype=float),
            np.asarray(iq_upper_a, dtype=float),
        )
        upper = np.maximum(upper, 0.0)
        upper_torque = electromagnetic_torque(ids, upper, parameters)
        valid = (
            np.isfinite(upper_torque)
            & np.isfinite(target)
            & (target >= 0.0)
            & (upper_torque >= target - np.maximum(1e-9, np.abs(target) * 1e-9))
        )
        lower = np.zeros_like(upper)
        high = upper.copy()
        # 32 bisections resolve a 400 A interval below 1e-7 A, comfortably
        # tighter than the torque equality tolerance while avoiding 16
        # redundant full-Map interpolation passes from the former loop.
        for _ in range(32):
            middle = 0.5 * (lower + high)
            torque = electromagnetic_torque(ids, middle, parameters)
            above = np.isfinite(torque) & (torque >= target)
            high = np.where(above, middle, high)
            lower = np.where(above, lower, middle)
        result = 0.5 * (lower + high)
        actual = electromagnetic_torque(ids, result, parameters)
        valid &= np.isfinite(actual) & (
            np.abs(actual - target) <= np.maximum(2e-6, np.abs(target) * 2e-6)
        )
        return np.where(valid, result, np.nan), valid

    def _solve_speed_row_saturated(
        self,
        parameters: MotorParameters,
        limits: ResolvedCharacteristicLimits,
        speed_rpm: float,
        requests: np.ndarray,
        torque_ratios: np.ndarray,
        speed_index: int,
        external_row: pd.Series,
        profile: str,
        maximum_torque_nm: float,
        id_lower: float,
        previous_speed_ids: np.ndarray | None,
    ) -> list[dict]:
        """Independent fixed-torque solve using Ld(Id,Iq)/Lq(Id,Iq)."""

        count = len(requests)
        current_limit = limits.max_current_vector_a
        inside_envelope = requests <= maximum_torque_nm + max(
            1e-8, abs(maximum_torque_nm) * 1e-9
        )
        output_power = requests * speed_rpm * 2.0 * np.pi / 60.0
        row = np.arange(count)

        def evaluate(
            candidate_ids: np.ndarray,
            indices: np.ndarray | None = None,
        ):
            local_requests = requests if indices is None else requests[indices]
            local_inside = (
                inside_envelope if indices is None else inside_envelope[indices]
            )
            local_power = output_power if indices is None else output_power[indices]
            upper = np.sqrt(
                np.maximum(current_limit**2 - candidate_ids**2, 0.0)
            )
            target = np.broadcast_to(
                local_requests[:, None], candidate_ids.shape
            )
            candidate_iq, root_valid = self._saturated_iq_for_torque(
                parameters, target, candidate_ids, upper
            )
            current_squared = candidate_ids**2 + candidate_iq**2
            ud_v, uq_v = dq_voltage(
                candidate_ids, candidate_iq, speed_rpm, parameters
            )
            valid = (
                root_valid
                & (current_squared <= current_limit**2 * (1.0 + 1e-9))
                & (
                    ud_v**2 + uq_v**2
                    <= limits.max_voltage_dq_v**2 * (1.0 + 1e-9)
                )
                & local_inside[:, None]
            )
            if parameters.pmax_w is not None:
                valid &= (
                    local_power[:, None]
                    <= parameters.pmax_w * (1.0 + 1e-9)
                )
            return candidate_iq, np.where(valid, current_squared, np.inf)

        global_points = 201 if profile == "preview" else 301
        global_ids = np.linspace(id_lower, 0.0, global_points)
        candidate_parts = [
            np.broadcast_to(global_ids[None, :], (count, global_points))
        ]
        warm_span = max(12.0, 0.04 * current_limit)
        if previous_speed_ids is not None and len(previous_speed_ids) == count:
            seeds = np.asarray(previous_speed_ids, dtype=float)
            fallback = np.full(count, 0.5 * (id_lower + 0.0))
            seeds = np.where(np.isfinite(seeds), seeds, fallback)
            warm_ids = np.clip(
                seeds[:, None]
                + np.linspace(-warm_span, warm_span, 81)[None, :],
                id_lower,
                0.0,
            )
            candidate_parts.append(warm_ids)
        candidate_ids = np.concatenate(candidate_parts, axis=1)
        candidate_iq, objective = evaluate(candidate_ids)
        best = np.argmin(objective, axis=1)
        feasible = np.isfinite(objective[row, best])
        selected_id = candidate_ids[row, best]
        selected_iq = candidate_iq[row, best]

        global_step = (0.0 - id_lower) / max(global_points - 1, 1)
        adjacent_center = np.concatenate(
            (selected_id[:1], selected_id[:-1])
        )
        centers = [selected_id, adjacent_center]
        if previous_speed_ids is not None and len(previous_speed_ids) == count:
            previous = np.asarray(previous_speed_ids, dtype=float)
            centers.append(np.where(np.isfinite(previous), previous, selected_id))
        refine_offsets = np.linspace(-2.0, 2.0, 41) * global_step
        refined_ids = np.concatenate(
            [
                np.clip(
                    center[:, None] + refine_offsets[None, :],
                    id_lower,
                    0.0,
                )
                for center in centers
            ],
            axis=1,
        )
        refined_iq, refined_objective = evaluate(refined_ids)
        refined_best = np.argmin(refined_objective, axis=1)
        use_refined = np.isfinite(refined_objective[row, refined_best])
        selected_id = np.where(
            use_refined, refined_ids[row, refined_best], selected_id
        )
        selected_iq = np.where(
            use_refined, refined_iq[row, refined_best], selected_iq
        )
        feasible |= use_refined

        refine_step = 4.0 * global_step / 40.0
        fine_ids = np.clip(
            selected_id[:, None]
            + np.linspace(-2.0, 2.0, 41)[None, :] * refine_step,
            id_lower,
            0.0,
        )
        fine_iq, fine_objective = evaluate(fine_ids)
        fine_best = np.argmin(fine_objective, axis=1)
        use_fine = np.isfinite(fine_objective[row, fine_best])
        selected_id = np.where(
            use_fine, fine_ids[row, fine_best], selected_id
        )
        selected_iq = np.where(
            use_fine, fine_iq[row, fine_best], selected_iq
        )
        feasible |= use_fine

        # A voltage/current intersection can become narrower than the global
        # continuation grid at isolated boundary points. Re-run only those
        # missed in-envelope targets on the former full grid; normal points
        # retain the fast continuation path and numerical robustness is not
        # traded for speed.
        missed = np.flatnonzero(inside_envelope & ~feasible)
        if missed.size:
            fallback_points = 601 if profile == "preview" else 1001
            fallback_axis = np.linspace(id_lower, 0.0, fallback_points)
            fallback_ids = np.broadcast_to(
                fallback_axis[None, :], (missed.size, fallback_points)
            )
            fallback_iq, fallback_objective = evaluate(
                fallback_ids, missed
            )
            fallback_row = np.arange(missed.size)
            fallback_best = np.argmin(fallback_objective, axis=1)
            recovered = np.isfinite(
                fallback_objective[fallback_row, fallback_best]
            )
            recovered_indices = missed[recovered]
            if recovered_indices.size:
                recovered_best = fallback_best[recovered]
                recovered_row = fallback_row[recovered]
                selected_id[recovered_indices] = fallback_ids[
                    recovered_row, recovered_best
                ]
                selected_iq[recovered_indices] = fallback_iq[
                    recovered_row, recovered_best
                ]
                feasible[recovered_indices] = True
                fallback_step = (0.0 - id_lower) / max(
                    fallback_points - 1, 1
                )
                fallback_refined_ids = np.clip(
                    selected_id[recovered_indices, None]
                    + np.linspace(-1.5, 1.5, 101)[None, :]
                    * fallback_step,
                    id_lower,
                    0.0,
                )
                fallback_refined_iq, fallback_refined_objective = evaluate(
                    fallback_refined_ids, recovered_indices
                )
                recovered_row = np.arange(recovered_indices.size)
                fallback_refined_best = np.argmin(
                    fallback_refined_objective, axis=1
                )
                refined_ok = np.isfinite(
                    fallback_refined_objective[
                        recovered_row, fallback_refined_best
                    ]
                )
                refined_indices = recovered_indices[refined_ok]
                if refined_indices.size:
                    refined_rows = recovered_row[refined_ok]
                    refined_best = fallback_refined_best[refined_ok]
                    selected_id[refined_indices] = fallback_refined_ids[
                        refined_rows, refined_best
                    ]
                    selected_iq[refined_indices] = fallback_refined_iq[
                        refined_rows, refined_best
                    ]

        external_id = float(external_row.get("Id_A", np.nan))
        external_iq = float(external_row.get("Iq_A", np.nan))
        boundary = np.flatnonzero(
            np.isclose(
                requests,
                maximum_torque_nm,
                rtol=1e-7,
                atol=max(1e-8, abs(maximum_torque_nm) * 1e-7),
            )
        )
        if boundary.size and np.isfinite(external_id) and np.isfinite(external_iq):
            index = int(boundary[-1])
            selected_id[index] = external_id
            selected_iq[index] = external_iq
            feasible[index] = True

        mtpa_id, mtpa_iq, mtpv_id, mtpv_iq = self._reference_points(
            parameters, limits, speed_rpm, requests, profile
        )
        records: list[dict] = []
        for torque_index, request in enumerate(requests):
            if not inside_envelope[torque_index]:
                records.append(
                    self._infeasible_record(
                        speed_index, torque_index, float(torque_ratios[torque_index]),
                        speed_rpm, float(request), "OutsideEnvelope"
                    )
                )
                continue
            below_minimum = request < self.settings.minimum_torque_nm and not (
                self.settings.include_zero_torque
                and np.isclose(request, 0.0, atol=1e-12)
            )
            if not bool(feasible[torque_index]) or below_minimum:
                records.append(
                    self._infeasible_record(
                        speed_index, torque_index, float(torque_ratios[torque_index]),
                        speed_rpm, float(request),
                        "BelowMinimumTorque" if below_minimum else "Infeasible",
                    )
                )
                continue
            records.append(
                self._build_record(
                    parameters, limits, speed_index, torque_index,
                    float(torque_ratios[torque_index]), speed_rpm, float(request),
                    float(selected_id[torque_index]), float(selected_iq[torque_index]),
                    mtpa_id, mtpa_iq, mtpv_id, mtpv_iq,
                )
            )
        self._attach_reference_columns(
            records, mtpa_id, mtpa_iq, mtpv_id, mtpv_iq
        )
        return records

    def _reference_points(
        self,
        parameters: MotorParameters,
        limits: ResolvedCharacteristicLimits,
        speed_rpm: float,
        requests: np.ndarray,
        profile: str,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        cache_key = (
            round(float(speed_rpm), 9),
            str(profile),
            np.asarray(requests, dtype=np.float64).tobytes(),
        )
        cached = self._reference_cache.get(cache_key)
        if cached is not None:
            return cached
        current = max(limits.max_current_vector_a, 1e-9)
        characteristic = parameters.flux_pm_wb / max(
            min(parameters.ld_h, parameters.lq_h), 1e-12
        )
        bound = min(max(3.0 * current, 2.0 * characteristic), 20.0 * current)
        points = 1001 if profile == "preview" else 1601
        if parameters.has_saturation_data:
            assert parameters.ld_saturation_map is not None
            assert parameters.lq_saturation_map is not None
            id_lower = max(
                -bound,
                parameters.ld_saturation_map.id_axis_a[0],
                parameters.lq_saturation_map.id_axis_a[0],
            )
            id_upper = min(
                bound,
                parameters.ld_saturation_map.id_axis_a[-1],
                parameters.lq_saturation_map.id_axis_a[-1],
            )
            if id_upper <= id_lower:
                raise ArithmeticError("饱和电感Map没有可用的Id参考范围。")
            original_step = 2.0 * bound / max(points - 1, 1)
            local_points = max(
                101,
                int(np.ceil((id_upper - id_lower) / original_step)) + 1,
            )
            ids = np.linspace(id_lower, id_upper, local_points)
            iq_upper = min(
                2.0 * bound,
                float(parameters.lq_saturation_map.iq_axis_a[-1]),
            )
            id_grid = np.broadcast_to(ids[None, :], (len(requests), len(ids)))
            target_grid = np.broadcast_to(requests[:, None], id_grid.shape)
            upper_grid = np.full(id_grid.shape, iq_upper, dtype=float)
            iqs, valid = self._saturated_iq_for_torque(
                parameters, target_grid, id_grid, upper_grid
            )
            current_squared = id_grid**2 + iqs**2
            mtpa_objective = np.where(valid, current_squared, np.inf)
            mtpa_index = np.argmin(mtpa_objective, axis=1)
            ud, uq = dq_voltage(id_grid, iqs, speed_rpm, parameters)
            tie_scale = (
                np.finfo(float).eps
                * max(limits.max_voltage_dq_v**2, 1.0)
                / max(current**2, 1.0)
            )
            mtpv_objective = np.where(
                valid, ud**2 + uq**2 + tie_scale * current_squared, np.inf
            )
            mtpv_index = np.argmin(mtpv_objective, axis=1)
            row = np.arange(len(requests))
            result = (
                ids[mtpa_index],
                iqs[row, mtpa_index],
                ids[mtpv_index],
                iqs[row, mtpv_index],
            )
            self._reference_cache[cache_key] = result
            return result
        ids = np.linspace(-bound, bound, points)
        coefficient = (
            1.5
            * parameters.pole_pairs
            * (
                parameters.flux_pm_wb
                + (parameters.ld_h - parameters.lq_h) * ids
            )
        )
        iqs = np.divide(
            requests[:, None],
            coefficient[None, :],
            out=np.full((len(requests), len(ids)), np.nan),
            where=coefficient[None, :] > self._coefficient_threshold(parameters),
        )
        valid = np.isfinite(iqs) & (iqs >= 0.0)
        current_squared = ids[None, :] ** 2 + iqs**2
        mtpa_objective = np.where(valid, current_squared, np.inf)
        mtpa_index = np.argmin(mtpa_objective, axis=1)

        omega_e = (
            parameters.pole_pairs * speed_rpm * 2.0 * np.pi / 60.0
        )
        ud = parameters.rs_ohm * ids[None, :] - omega_e * parameters.lq_h * iqs
        uq = (
            parameters.rs_ohm * iqs
            + omega_e * (parameters.ld_h * ids[None, :] + parameters.flux_pm_wb)
        )
        tie_scale = (
            np.finfo(float).eps
            * max(limits.max_voltage_dq_v**2, 1.0)
            / max(current**2, 1.0)
        )
        mtpv_objective = np.where(
            valid, ud**2 + uq**2 + tie_scale * current_squared, np.inf
        )
        mtpv_index = np.argmin(mtpv_objective, axis=1)
        row = np.arange(len(requests))
        result = (
            ids[mtpa_index],
            iqs[row, mtpa_index],
            ids[mtpv_index],
            iqs[row, mtpv_index],
        )
        self._reference_cache[cache_key] = result
        return result

    @staticmethod
    def _coefficient_threshold(parameters: MotorParameters) -> float:
        return max(
            1e-14,
            abs(parameters.flux_pm_wb)
            * parameters.pole_pairs
            * np.finfo(float).eps
            * 100.0,
        )

    @staticmethod
    def _attach_reference_columns(
        records: list[dict],
        mtpa_id: np.ndarray,
        mtpa_iq: np.ndarray,
        mtpv_id: np.ndarray,
        mtpv_iq: np.ndarray,
    ) -> None:
        """Persist already-solved references so the GUI never re-solves them."""

        for torque_index, record in enumerate(records):
            record["MTPAReferenceId_A"] = float(mtpa_id[torque_index])
            record["MTPAReferenceIq_A"] = float(mtpa_iq[torque_index])
            record["MTPVReferenceId_A"] = float(mtpv_id[torque_index])
            record["MTPVReferenceIq_A"] = float(mtpv_iq[torque_index])

    def _build_record(
        self,
        parameters: MotorParameters,
        limits: ResolvedCharacteristicLimits,
        speed_index: int,
        torque_index: int,
        torque_ratio: float,
        speed_rpm: float,
        request_nm: float,
        id_a: float,
        iq_a: float,
        mtpa_curve_id: np.ndarray,
        mtpa_curve_iq: np.ndarray,
        mtpv_curve_id: np.ndarray,
        mtpv_curve_iq: np.ndarray,
    ) -> dict:
        actual_torque = float(electromagnetic_torque(id_a, iq_a, parameters))
        ld_h, lq_h = parameters.inductances_h(id_a, iq_a)
        current = float(np.hypot(id_a, iq_a))
        ud_values, uq_values = dq_voltage(id_a, iq_a, speed_rpm, parameters)
        ud_v = float(ud_values)
        uq_v = float(uq_values)
        voltage = float(np.hypot(ud_v, uq_v))
        mechanical_power_w = actual_torque * speed_rpm * 2.0 * np.pi / 60.0
        copper_w = 1.5 * parameters.rs_ohm * current**2
        psi_d, psi_q, psi_s = dq_flux_linkage(id_a, iq_a, parameters)
        iron_w = float(
            iron_loss_w(
                speed_rpm,
                psi_s,
                parameters.pole_pairs,
                self.loss_parameters,
            )
        )
        efficiency = float(
            motor_efficiency(
                mechanical_power_w,
                copper_w,
                iron_w,
                minimum_output_w=self.loss_parameters.minimum_efficiency_output_w,
            )
        )
        current_utilization = current / limits.max_current_vector_a
        voltage_utilization = voltage / limits.max_voltage_dq_v
        power_utilization = (
            mechanical_power_w / parameters.pmax_w
            if parameters.pmax_w is not None
            else 0.0
        )
        current_active = current_utilization >= 0.995
        voltage_active = (
            voltage_utilization >= self.settings.voltage_active_threshold
        )
        power_active = (
            parameters.pmax_w is not None and power_utilization >= 0.995
        )
        active_names = []
        if current_active:
            active_names.append("Current")
        if voltage_active:
            active_names.append("Voltage")
        if power_active:
            active_names.append("Power")
        active_constraint = "+".join(active_names) if active_names else "None"
        classification = classify_internal_operating_point(
            id_a=id_a,
            iq_a=iq_a,
            current_limit_a=limits.max_current_vector_a,
            voltage_utilization=voltage_utilization,
            voltage_constraint_active=voltage_active,
            active_constraint=active_constraint,
            control_strategy=self.settings.strategy,
            mtpa_curve_id_a=mtpa_curve_id,
            mtpa_curve_iq_a=mtpa_curve_iq,
            mtpv_curve_id_a=mtpv_curve_id,
            mtpv_curve_iq_a=mtpv_curve_iq,
            config=OperatingRegionClassificationConfig(
                mtpa_distance_tolerance=(
                    self.settings.mtpa_distance_tolerance
                ),
                mtpv_distance_tolerance=(
                    self.settings.mtpv_distance_tolerance
                ),
                voltage_active_threshold=(
                    self.settings.voltage_active_threshold
                ),
            ),
        )

        return {
            "SpeedIndex": speed_index,
            "TorqueIndex": torque_index,
            "TorqueRatio": torque_ratio,
            "Speed_rpm": speed_rpm,
            "TorqueRequest_Nm": request_nm,
            "TorqueActual_Nm": actual_torque,
            "Id_A": id_a,
            "Iq_A": iq_a,
            "Ld_uH": float(ld_h) * 1e6,
            "Lq_uH": float(lq_h) * 1e6,
            "Is_A": current,
            "Ud_V": ud_v,
            "Uq_V": uq_v,
            "Us_V": voltage,
            "MechanicalPower_kW": mechanical_power_w / 1000.0,
            "CopperLoss_kW": copper_w / 1000.0,
            "IronLoss_kW": iron_w / 1000.0,
            "TotalMotorLoss_kW": (copper_w + iron_w) / 1000.0,
            "Efficiency": efficiency,
            "CurrentUtilization": current_utilization,
            "VoltageUtilization": voltage_utilization,
            "Psi_d_Wb": float(psi_d),
            "Psi_q_Wb": float(psi_q),
            "Psi_s_Wb": float(psi_s),
            "ElectricalFrequency_Hz": float(
                electrical_frequency_hz(speed_rpm, parameters.pole_pairs)
            ),
            "NearMTPA": classification.near_mtpa,
            "NearMTPV": classification.near_mtpv,
            "MTPADistance_A": classification.mtpa_distance_a,
            "MTPVDistance_A": classification.mtpv_distance_a,
            "CurrentConstraintActive": current_active,
            "VoltageConstraintActive": voltage_active,
            "PowerConstraintActive": power_active,
            "ControlRegion": classification.region.value,
            "ActiveConstraint": active_constraint,
            "IsFeasible": True,
            "SolverStatus": "Converged",
        }

    @staticmethod
    def _infeasible_record(
        speed_index: int,
        torque_index: int,
        torque_ratio: float,
        speed_rpm: float,
        request_nm: float,
        status: str,
    ) -> dict:
        record = {
            column: np.nan
            for column in MAP_RESULT_COLUMNS
            if column
            not in {
                "SpeedIndex",
                "TorqueIndex",
                "TorqueRatio",
                "Speed_rpm",
                "TorqueRequest_Nm",
                "NearMTPA",
                "NearMTPV",
                "CurrentConstraintActive",
                "VoltageConstraintActive",
                "PowerConstraintActive",
                "ControlRegion",
                "ActiveConstraint",
                "IsFeasible",
                "SolverStatus",
            }
        }
        record.update(
            {
                "SpeedIndex": speed_index,
                "TorqueIndex": torque_index,
                "TorqueRatio": torque_ratio,
                "Speed_rpm": speed_rpm,
                "TorqueRequest_Nm": request_nm,
                "NearMTPA": False,
                "NearMTPV": False,
                "CurrentConstraintActive": False,
                "VoltageConstraintActive": False,
                "PowerConstraintActive": False,
                "ControlRegion": "Infeasible",
                "ActiveConstraint": "None",
                "IsFeasible": False,
                "SolverStatus": status,
            }
        )
        return record
