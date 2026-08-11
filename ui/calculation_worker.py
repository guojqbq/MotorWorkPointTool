"""Versioned background calculation worker with diagnostic telemetry."""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from time import perf_counter
import traceback

from PySide6.QtCore import QObject, QThread, Signal, Slot

from calculation.characteristic_limit_resolver import (
    resolve_characteristic_limits,
)
from calculation.envelope_solver import EnvelopeSolver, SolverSettings
from calculation.dq_reference_data import (
    build_mtpa_trajectory_from_map,
    build_mtpv_envelope_from_external,
)
from calculation.operating_map_solver import OperatingMapSolver
from models.analysis_result import AnalysisResult
from models.characteristic_input import CharacteristicInput
from models.characteristic_summary import CharacteristicSummary
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings
from models.motor_parameters import MotorParameters


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CalculationErrorDetails:
    """Structured exception payload safe to send across a Qt signal."""

    exception_type: str
    filename: str
    line_number: int
    message: str
    traceback_text: str
    cancelled: bool = False

    @classmethod
    def from_exception(
        cls, exc: BaseException, *, cancelled: bool = False
    ) -> "CalculationErrorDetails":
        traceback_text = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        frames = traceback.extract_tb(exc.__traceback__)
        origin = frames[-1] if frames else None
        return cls(
            exception_type=type(exc).__name__,
            filename=(origin.filename if origin is not None else "<unknown>"),
            line_number=(origin.lineno if origin is not None else 0),
            message=str(exc),
            traceback_text=traceback_text,
            cancelled=cancelled,
        )

    def dialog_text(self) -> str:
        return (
            f"异常类型：{self.exception_type}\n"
            f"文件名：{self.filename}\n"
            f"行号：{self.line_number}\n"
            f"错误信息：{self.message}\n\n"
            f"完整 Python traceback：\n{self.traceback_text}"
        )


class CalculationWorker(QObject):
    progress = Signal(int, int)
    stage = Signal(int, str, int, int)
    finished = Signal(int, object)
    failed = Signal(int, object)

    def __init__(
        self,
        parameters: MotorParameters,
        loss_parameters: LossModelParameters,
        map_settings: MapCalculationSettings,
        profile: str,
        version: int,
        cache_key: str,
        characteristic_input: CharacteristicInput | None = None,
    ) -> None:
        super().__init__()
        self.parameters = parameters
        self.loss_parameters = loss_parameters
        self.map_settings = map_settings
        self.profile = profile
        self.version = version
        self.cache_key = cache_key
        self.characteristic_input = characteristic_input

    @Slot()
    def run(self) -> None:
        total_started = perf_counter()
        cancel_check = (
            lambda: QThread.currentThread().isInterruptionRequested()
        )
        try:
            self._emit_stage("参数校验", 0, 1, 1)
            effective_parameters = replace(
                self.parameters,
                rs_ohm=self.loss_parameters.resistance_at_temperature(
                    self.parameters.rs_ohm
                ),
            ).validated()
            map_parameters = self.parameters
            map_settings = self.map_settings
            if map_settings.diagnostic_mode:
                effective_parameters = replace(
                    effective_parameters, speed_points=11
                ).validated()
                map_parameters = replace(
                    map_parameters, speed_points=11
                ).validated()
                map_settings = replace(
                    map_settings,
                    grid_definition_mode="point_count",
                    preview_speed_points=11,
                    preview_torque_points=11,
                    full_speed_points=11,
                    full_torque_points=11,
                ).validated()

            characteristic_input = self.characteristic_input
            if characteristic_input is None:
                from calculation.characteristic_limit_resolver import (
                    characteristic_input_from_legacy_motor,
                )

                characteristic_input = characteristic_input_from_legacy_motor(
                    effective_parameters
                )
            limits = resolve_characteristic_limits(
                effective_parameters, characteristic_input
            )
            self._emit_stage("参数校验", 1, 1, 8)

            external_started = perf_counter()
            self._emit_stage(
                "外特性", 0, effective_parameters.speed_points, 10
            )
            envelope_settings = SolverSettings(
                coarse_id_points=(601 if self.profile == "preview" else 1001),
                fine_id_points=(201 if self.profile == "preview" else 301),
            )
            external = EnvelopeSolver(
                effective_parameters, envelope_settings, limits
            ).solve(
                progress_callback=lambda done, total: self._report_named_phase(
                    "外特性", 10, 37, done, total
                ),
                cancel_check=cancel_check,
                diagnostic_callback=self._log_solver_event,
            )
            external_elapsed = perf_counter() - external_started
            LOGGER.info("外特性耗时 %.3f s", external_elapsed)

            self._emit_stage("MTPA/MTPV", 0, 1, 38)
            mtpv_envelope = build_mtpv_envelope_from_external(
                effective_parameters, external
            )
            self._emit_stage("MTPA/MTPV", 1, 1, 39)

            map_shape = map_settings.grid_shape(self.profile)
            self._emit_stage(
                "内部 Map", 0, map_shape[0] * map_shape[1], 40
            )
            map_started = perf_counter()
            operating_map = OperatingMapSolver(
                map_parameters,
                self.loss_parameters,
                map_settings,
                limits,
            ).solve(
                self.profile,
                progress_callback=lambda done, total: self._report_named_phase(
                    "内部 Map", 40, 92, done, total
                ),
                cancel_check=cancel_check,
                diagnostic_callback=self._log_solver_event,
                external_characteristic=external,
            )
            map_elapsed = perf_counter() - map_started
            LOGGER.info("内部 Map 耗时 %.3f s", map_elapsed)
            self._emit_stage("损耗效率", 0, 1, 94)
            mtpa_trajectory = build_mtpa_trajectory_from_map(
                effective_parameters, operating_map
            )
            self._emit_stage("损耗效率", 1, 1, 96)
            if cancel_check():
                raise InterruptedError("计算已取消。")
        except InterruptedError as exc:
            details = CalculationErrorDetails.from_exception(
                exc, cancelled=True
            )
            LOGGER.info("计算已取消\n%s", details.traceback_text)
            self.failed.emit(self.version, details)
        except BaseException as exc:  # GUI/thread boundary: never fail silently
            details = CalculationErrorDetails.from_exception(exc)
            LOGGER.error(
                "后台计算失败：%s:%d %s\n%s",
                details.filename,
                details.line_number,
                details.exception_type,
                details.traceback_text,
            )
            self.failed.emit(self.version, details)
        else:
            total_elapsed = perf_counter() - total_started
            LOGGER.info(
                "计算阶段完成：外特性 %.3f s，内部 Map %.3f s，总耗时 %.3f s",
                external_elapsed,
                map_elapsed,
                total_elapsed,
            )
            self._emit_stage("绘图刷新", 0, 1, 98)
            self.finished.emit(
                self.version,
                AnalysisResult(
                    calculation_parameters=effective_parameters,
                    external_characteristic=external,
                    operating_map=operating_map,
                    profile=self.profile,
                    cache_key=self.cache_key,
                    resolved_limits=limits,
                    characteristic_summary=(
                        CharacteristicSummary.from_external_characteristic(
                            external, limits
                        )
                    ),
                    mtpa_trajectory=mtpa_trajectory,
                    mtpv_envelope=mtpv_envelope,
                ),
            )

    def _report_phase(
        self, start: int, end: int, completed: int, total: int
    ) -> None:
        fraction = completed / max(total, 1)
        self.progress.emit(
            self.version, round(start + (end - start) * fraction)
        )

    def _report_named_phase(
        self,
        name: str,
        start: int,
        end: int,
        completed: int,
        total: int,
    ) -> None:
        self._report_phase(start, end, completed, total)
        self.stage.emit(
            self.version, name, int(completed), int(total)
        )

    def _emit_stage(
        self, name: str, completed: int, total: int, progress: int
    ) -> None:
        self.progress.emit(self.version, int(progress))
        self.stage.emit(self.version, name, int(completed), int(total))

    def _log_solver_event(self, event: dict) -> None:
        stage = str(event.get("stage", "solver"))
        speed_index = int(event.get("speed_index", -1))
        torque_index = int(event.get("torque_index", -1))
        speed_rpm = float(event.get("speed_rpm", float("nan")))
        torque_nm = float(event.get("torque_nm", float("nan")))
        elapsed = float(event.get("elapsed_seconds", 0.0))
        row_elapsed = float(event.get("row_elapsed_seconds", elapsed))
        status = str(event.get("status", "Unknown"))
        initial_id = float(event.get("initial_id_a", float("nan")))
        initial_iq = float(event.get("initial_iq_a", float("nan")))
        iterations = int(event.get("iterations", 0))
        feasible = int(event.get("feasible_count", 0))
        failed = int(event.get("failed_count", 0))
        completed = int(event.get("completed", 0))
        total = int(event.get("total", 0))
        stage_label = {
            "external": "外特性",
            "map_envelope": "内部 Map：转矩边界",
            "map_envelope_reused": "内部 Map：复用转矩边界",
            "internal_map": "内部 Map",
        }.get(stage, stage)
        if total > 0:
            self.stage.emit(self.version, stage_label, completed, total)
        message = (
            "%s speed_index=%d torque_index=%d speed_rpm=%.6g "
            "torque_nm=%.6g solver_elapsed_s=%.6f status=%s "
            "initial_id_a=%.6g initial_iq_a=%.6g iterations=%d "
            "row_elapsed_s=%.6f feasible=%d failed=%d"
        )
        values = (
            stage,
            speed_index,
            torque_index,
            speed_rpm,
            torque_nm,
            elapsed,
            status,
            initial_id,
            initial_iq,
            iterations,
            row_elapsed,
            feasible,
            failed,
        )
        if elapsed > self.map_settings.solver_timeout_seconds:
            LOGGER.warning(message, *values)
        elif row_elapsed > self.map_settings.solver_timeout_seconds:
            LOGGER.warning(message, *values)
        elif self.map_settings.diagnostic_mode or torque_index < 0:
            LOGGER.info(message, *values)
