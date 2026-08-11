"""Configuration for the torque-speed operating map and region classifier."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class MapCalculationSettings:
    preview_speed_points: int = 25
    preview_torque_points: int = 25
    full_speed_points: int = 81
    full_torque_points: int = 121
    grid_definition_mode: str = "point_count"
    speed_step_rpm: float = 375.0
    torque_step_nm: float = 4.05
    maximum_speed_rpm: float | None = None
    minimum_torque_nm: float = 0.0
    include_zero_torque: bool = True
    first_quadrant_only: bool = True
    invalid_display: str = "blank"
    strategy: str = "MTPA_FieldWeakening_MTPV"
    # Retained only so V0.2 project files remain loadable.  The GUI no longer
    # starts calculations from parameter-change signals.
    automatic_calculation: bool = False
    debounce_ms: int = 500
    show_internal_points_in_dq: bool = True
    torque_axis_mode: str = "actual"
    torque_axis_distribution: str = "nonuniform"
    mtpa_distance_tolerance: float = 0.015
    mtpv_distance_tolerance: float = 0.020
    voltage_active_threshold: float = 0.98
    # Diagnostic mode deliberately reduces a formal calculation to 11 x 11 so
    # the complete worker/error/progress path can be checked quickly.  It does
    # not select a different numerical algorithm.
    diagnostic_mode: bool = False
    solver_timeout_seconds: float = 5.0

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        for label, value in {
            "预览转速点数": self.preview_speed_points,
            "预览转矩点数": self.preview_torque_points,
            "全量转速点数": self.full_speed_points,
            "全量转矩点数": self.full_torque_points,
        }.items():
            if not 2 <= int(value) <= 401:
                errors.append(f"{label}必须在 2 到 401 之间。")
        if self.maximum_speed_rpm is not None and self.maximum_speed_rpm <= 0:
            errors.append("Map 最大转速必须大于零。")
        if self.grid_definition_mode not in {"point_count", "step"}:
            errors.append("工况网格设置方式必须为按点数或按步长。")
        if self.speed_step_rpm <= 0:
            errors.append("转速步长必须大于零。")
        if self.torque_step_nm <= 0:
            errors.append("转矩步长必须大于零。")
        if self.minimum_torque_nm < 0:
            errors.append("Map 最小转矩不能为负数。")
        if self.strategy not in {
            "MinimumCurrent",
            "MTPA_FieldWeakening_MTPV",
        }:
            errors.append("第一版仅支持 MinimumCurrent 和 MTPA_FieldWeakening_MTPV。")
        if self.invalid_display not in {"blank", "mark"}:
            errors.append("无效点显示方式必须为 blank 或 mark。")
        if self.torque_axis_mode not in {"actual", "normalized"}:
            errors.append("转矩轴模式必须为 actual 或 normalized。")
        if self.torque_axis_distribution not in {"nonuniform", "linear"}:
            errors.append("转矩轴分布必须为 nonuniform 或 linear。")
        if not 0.0 < self.mtpa_distance_tolerance < 1.0:
            errors.append("MTPA归一化距离阈值必须在0到1之间。")
        if not 0.0 < self.mtpv_distance_tolerance < 1.0:
            errors.append("MTPV归一化距离阈值必须在0到1之间。")
        if not 0.0 < self.voltage_active_threshold <= 1.0:
            errors.append("电压激活阈值必须在0到1之间。")
        if (
            not isinstance(self.solver_timeout_seconds, (int, float))
            or self.solver_timeout_seconds <= 0.0
        ):
            errors.append("单个求解单元超时阈值必须大于零。")
        if not 300 <= self.debounce_ms <= 800:
            errors.append("自动计算防抖时间必须在 300 到 800 ms 之间。")
        return errors

    def validated(self) -> "MapCalculationSettings":
        errors = self.validation_errors()
        if errors:
            raise ValueError("\n".join(errors))
        return self

    def grid_shape(self, profile: str) -> tuple[int, int]:
        if self.diagnostic_mode:
            return 11, 11
        if profile == "preview":
            return self.preview_speed_points, self.preview_torque_points
        if profile == "full":
            return self.full_speed_points, self.full_torque_points
        raise ValueError(f"未知 Map 计算档位：{profile}")

    def resolved_grid_shape(
        self,
        profile: str,
        maximum_speed_rpm: float,
        maximum_torque_nm: float,
    ) -> tuple[int, int]:
        """Return the actual grid size after resolving point/step mode."""

        if self.grid_definition_mode == "point_count":
            return self.grid_shape(profile)
        if self.diagnostic_mode:
            return 11, 11
        from calculation.operating_map_grid import point_count_for_step

        return (
            point_count_for_step(maximum_speed_rpm, self.speed_step_rpm),
            point_count_for_step(maximum_torque_nm, self.torque_step_nm),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def calculation_dict(self) -> dict[str, Any]:
        """Return only settings that can change numerical result arrays."""

        values = self.as_dict()
        for key in (
            "automatic_calculation",
            "debounce_ms",
            "show_internal_points_in_dq",
            "invalid_display",
        ):
            values.pop(key, None)
        return values

    @classmethod
    def from_dict(cls, values: Mapping[str, Any] | None) -> "MapCalculationSettings":
        if not values:
            return cls()
        known = {field_name for field_name in cls.__dataclass_fields__}
        return cls(
            **{key: value for key, value in values.items() if key in known}
        ).validated()
