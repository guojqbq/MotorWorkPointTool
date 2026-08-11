"""Validated motor and inverter input parameters.

The GUI stores inductance in mH, power in kW, and current in the definition
selected by the user.  The calculation layer only consumes the SI/peak-value
properties exposed by :class:`MotorParameters`.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose, sqrt
from typing import Any, Mapping

import numpy as np
from numpy.typing import ArrayLike, NDArray

from models.inductance_model import InductanceModel, parse_inductance_model
from models.saturation_map import InductanceSaturationMap
from models.winding_connection import (
    OpenWindingTopology,
    WindingConnection,
    parse_open_winding_topology,
    parse_winding_connection,
)


class ParameterValidationError(ValueError):
    """Raised when one or more input parameters are invalid."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass(frozen=True, slots=True)
class MotorParameters:
    pole_pairs: int = 3
    rs_ohm: float = 0.0289
    ld_mh: float = 0.442
    lq_mh: float = 1.931
    flux_pm_wb: float = 0.161
    udc_v: float = 844.0
    imax_a: float = 310.0
    max_speed_rpm: float = 30000.0
    speed_points: int = 161
    id_min_a: float | None = None
    pmax_kw: float | None = None
    voltage_utilization: float = 0.95
    modulation: str = "SVPWM"
    current_definition: str = "peak"
    inductance_model: InductanceModel = InductanceModel.CONSTANT
    winding_connection: WindingConnection = WindingConnection.STAR
    open_winding_topology: OpenWindingTopology = (
        OpenWindingTopology.DUAL_COMMON_DC
    )
    open_winding_udc2_v: float | None = None
    ld_saturation_map: InductanceSaturationMap | None = None
    lq_saturation_map: InductanceSaturationMap | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "modulation", str(self.modulation).upper())
        object.__setattr__(
            self, "current_definition", str(self.current_definition).lower()
        )
        object.__setattr__(
            self,
            "inductance_model",
            parse_inductance_model(self.inductance_model),
        )
        object.__setattr__(
            self,
            "winding_connection",
            parse_winding_connection(self.winding_connection),
        )
        object.__setattr__(
            self,
            "open_winding_topology",
            parse_open_winding_topology(self.open_winding_topology),
        )

    @property
    def ld_h(self) -> float:
        return self.ld_mh * 1e-3

    @property
    def lq_h(self) -> float:
        return self.lq_mh * 1e-3

    @property
    def current_scale_to_peak(self) -> float:
        return sqrt(2.0) if self.current_definition == "rms" else 1.0

    @property
    def imax_peak_a(self) -> float:
        return (
            self.imax_a
            * self.current_scale_to_peak
            * self.winding_connection.line_to_winding_current_factor
        )

    @property
    def imax_line_peak_a(self) -> float:
        return self.imax_a * self.current_scale_to_peak

    @property
    def id_min_peak_a(self) -> float | None:
        if self.id_min_a is None:
            return None
        return (
            self.id_min_a
            * self.current_scale_to_peak
            * self.winding_connection.line_to_winding_current_factor
        )

    @property
    def pmax_w(self) -> float | None:
        if self.pmax_kw is None:
            return None
        return self.pmax_kw * 1000.0

    @property
    def umax_v(self) -> float:
        return self.dq_voltage_limit_from_udc(self.udc_v)

    def dq_voltage_limit_from_udc(self, primary_udc_v: float) -> float:
        """Convert inverter-side Udc to physical-winding dq peak voltage."""

        denominator = sqrt(3.0) if self.modulation == "SVPWM" else 2.0
        base_factor = self.voltage_utilization / denominator
        primary = float(primary_udc_v)
        if self.winding_connection is WindingConnection.STAR:
            return base_factor * primary
        if self.winding_connection is WindingConnection.DELTA:
            return sqrt(3.0) * base_factor * primary
        secondary = (
            float(self.open_winding_udc2_v)
            if self.open_winding_topology
            is OpenWindingTopology.CUSTOM_DUAL_UDC
            and self.open_winding_udc2_v is not None
            else primary
        )
        return base_factor * (primary + secondary)

    @property
    def has_saturation_data(self) -> bool:
        return (
            self.inductance_model is InductanceModel.SATURATION_MAP
            and
            self.ld_saturation_map is not None
            and self.lq_saturation_map is not None
        )

    def inductances_h(
        self, id_a: ArrayLike, iq_a: ArrayLike
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        id_values, iq_values = np.broadcast_arrays(
            np.asarray(id_a, dtype=float), np.asarray(iq_a, dtype=float)
        )
        if not self.has_saturation_data:
            return (
                np.full(id_values.shape, self.ld_h, dtype=float),
                np.full(id_values.shape, self.lq_h, dtype=float),
            )
        assert self.ld_saturation_map is not None
        assert self.lq_saturation_map is not None
        return (
            self.ld_saturation_map.interpolate_h(id_values, iq_values),
            self.lq_saturation_map.interpolate_h(id_values, iq_values),
        )

    def saturation_domain_contains(
        self, id_a: ArrayLike, iq_a: ArrayLike
    ) -> NDArray[np.bool_]:
        if self.inductance_model is InductanceModel.CONSTANT:
            return np.ones(np.broadcast_shapes(np.shape(id_a), np.shape(iq_a)), dtype=bool)
        if not self.has_saturation_data:
            return np.zeros(np.broadcast_shapes(np.shape(id_a), np.shape(iq_a)), dtype=bool)
        assert self.ld_saturation_map is not None
        return self.ld_saturation_map.contains(id_a, iq_a)

    @property
    def motor_type(self) -> str:
        if self.has_saturation_data:
            ld_h, lq_h = self.inductances_h(0.0, 0.0)
            ld_value, lq_value = float(ld_h), float(lq_h)
        else:
            ld_value, lq_value = self.ld_h, self.lq_h
        if isclose(ld_value, lq_value, rel_tol=1e-6, abs_tol=1e-12):
            return "SPMSM"
        return "IPMSM"

    @property
    def current_definition_label(self) -> str:
        return "相电流RMS" if self.current_definition == "rms" else "相电流峰值"

    def validation_errors(self) -> list[str]:
        errors: list[str] = []

        if (
            isinstance(self.pole_pairs, bool)
            or not isinstance(self.pole_pairs, int)
            or self.pole_pairs <= 0
        ):
            errors.append("极对数必须是大于0的整数。")
        if self.rs_ohm < 0:
            errors.append("定子相电阻 Rs 不能为负数。")
        if self.ld_mh <= 0:
            errors.append("d轴电感 Ld 必须大于0 mH。")
        if self.lq_mh <= 0:
            errors.append("q轴电感 Lq 必须大于0 mH。")
        if self.flux_pm_wb <= 0:
            errors.append("永磁体磁链必须大于0 Wb。")
        if self.udc_v <= 0:
            errors.append("直流母线电压 Udc 必须大于0 V。")
        if self.imax_a <= 0:
            errors.append("最大电流 Imax 必须大于0 A。")
        if self.max_speed_rpm <= 0:
            errors.append("最大机械转速必须大于0 rpm。")
        if (
            isinstance(self.speed_points, bool)
            or not isinstance(self.speed_points, int)
            or not 2 <= self.speed_points <= 2001
        ):
            errors.append("转速点数必须是2到2001之间的整数。")
        if self.modulation not in {"SVPWM", "SPWM"}:
            errors.append("调制方式只能是 SVPWM 或 SPWM。")
        if self.current_definition not in {"peak", "rms"}:
            errors.append("输入电流定义只能是峰值（peak）或RMS（rms）。")
        try:
            parse_inductance_model(self.inductance_model)
        except ValueError:
            errors.append("电感模型必须是 CONSTANT 或 SATURATION_MAP。")
        try:
            parse_winding_connection(self.winding_connection)
        except ValueError:
            errors.append("绕组接线方式必须是 STAR、DELTA 或 OPEN_WINDING。")
        if (self.ld_saturation_map is None) != (self.lq_saturation_map is None):
            errors.append("启用饱和电感时必须同时提供 Ld 和 Lq 两张表。")
        if (
            self.inductance_model is InductanceModel.SATURATION_MAP
            and not self.has_saturation_data
        ):
            errors.append("SATURATION_MAP 模式必须同时提供 Ld 和 Lq 饱和表。")
        if self.has_saturation_data:
            try:
                assert self.ld_saturation_map is not None
                assert self.lq_saturation_map is not None
                self.ld_saturation_map.validated()
                self.lq_saturation_map.validated()
                if (
                    self.ld_saturation_map.id_axis_a
                    != self.lq_saturation_map.id_axis_a
                    or self.ld_saturation_map.iq_axis_a
                    != self.lq_saturation_map.iq_axis_a
                ):
                    errors.append("Ld 与 Lq 饱和表必须使用相同的 Id/Iq 网格。")
            except ValueError as exc:
                errors.extend(str(exc).splitlines())
        if (
            self.winding_connection is WindingConnection.OPEN_WINDING
            and self.open_winding_topology
            is OpenWindingTopology.CUSTOM_DUAL_UDC
            and (
                self.open_winding_udc2_v is None
                or not np.isfinite(self.open_winding_udc2_v)
                or self.open_winding_udc2_v <= 0.0
            )
        ):
            errors.append("自定义双 Udc 开绕组必须提供有限正数的第二侧 Udc。")
        if not 0 < self.voltage_utilization <= 1:
            errors.append("电压利用系数必须大于0且不超过1。")
        if self.pmax_kw is not None and self.pmax_kw <= 0:
            errors.append("启用最大机械功率限制时，Pmax 必须大于0 kW。")
        if self.id_min_a is not None:
            if self.id_min_a > 0:
                errors.append("最大允许负向d轴电流 Id_min 必须小于或等于0 A。")

        numeric_values = {
            "定子相电阻 Rs": self.rs_ohm,
            "d轴电感 Ld": self.ld_mh,
            "q轴电感 Lq": self.lq_mh,
            "永磁体磁链": self.flux_pm_wb,
            "直流母线电压 Udc": self.udc_v,
            "最大电流 Imax": self.imax_a,
            "最大机械转速": self.max_speed_rpm,
            "电压利用系数": self.voltage_utilization,
        }
        for label, value in numeric_values.items():
            try:
                finite = float("-inf") < float(value) < float("inf")
            except (TypeError, ValueError):
                finite = False
            if not finite:
                errors.append(f"{label}必须是有限数值。")

        return errors

    def validated(self) -> "MotorParameters":
        errors = self.validation_errors()
        if errors:
            raise ParameterValidationError(errors)
        return self

    def as_input_dict(self) -> dict[str, Any]:
        """Return values in the same units and convention used by the GUI."""

        return {
            "pole_pairs": self.pole_pairs,
            "Rs": self.rs_ohm,
            "Ld_mH": self.ld_mh,
            "Lq_mH": self.lq_mh,
            "flux_pm": self.flux_pm_wb,
            "Udc": self.udc_v,
            "Imax": self.imax_a,
            "max_speed_rpm": self.max_speed_rpm,
            "speed_points": self.speed_points,
            "Id_min": self.id_min_a,
            "Pmax_kW": self.pmax_kw,
            "voltage_utilization": self.voltage_utilization,
            "modulation": self.modulation,
            "current_definition": self.current_definition,
            "inductance_model": self.inductance_model.value,
            "winding_connection": self.winding_connection.value,
            "open_winding_topology": self.open_winding_topology.value,
            "open_winding_udc2_v": self.open_winding_udc2_v,
            "ld_saturation_map": (
                self.ld_saturation_map.as_dict()
                if self.ld_saturation_map is not None
                else None
            ),
            "lq_saturation_map": (
                self.lq_saturation_map.as_dict()
                if self.lq_saturation_map is not None
                else None
            ),
        }

    @classmethod
    def from_input_dict(cls, values: Mapping[str, Any]) -> "MotorParameters":
        def optional_float(key: str) -> float | None:
            value = values.get(key)
            if value in (None, ""):
                return None
            return float(value)

        pole_pairs_raw = values.get("pole_pairs", 3)
        speed_points_raw = values.get("speed_points", 121)
        if float(pole_pairs_raw).is_integer():
            pole_pairs = int(pole_pairs_raw)
        else:
            raise ParameterValidationError(["极对数必须是整数。"])
        if float(speed_points_raw).is_integer():
            speed_points = int(speed_points_raw)
        else:
            raise ParameterValidationError(["转速点数必须是整数。"])

        return cls(
            pole_pairs=pole_pairs,
            rs_ohm=float(values.get("Rs", values.get("rs_ohm", 0.0289))),
            ld_mh=float(values.get("Ld_mH", values.get("ld_mh", 0.442))),
            lq_mh=float(values.get("Lq_mH", values.get("lq_mh", 1.931))),
            flux_pm_wb=float(
                values.get("flux_pm", values.get("flux_pm_wb", 0.161))
            ),
            udc_v=float(values.get("Udc", values.get("udc_v", 844.0))),
            imax_a=float(values.get("Imax", values.get("imax_a", 310.0))),
            max_speed_rpm=float(values.get("max_speed_rpm", 30000.0)),
            speed_points=speed_points,
            id_min_a=optional_float("Id_min")
            if "Id_min" in values
            else optional_float("id_min_a"),
            pmax_kw=optional_float("Pmax_kW")
            if "Pmax_kW" in values
            else optional_float("pmax_kw"),
            voltage_utilization=float(values.get("voltage_utilization", 0.95)),
            modulation=str(values.get("modulation", "SVPWM")),
            current_definition=str(values.get("current_definition", "peak")),
            inductance_model=parse_inductance_model(
                values.get(
                    "inductance_model",
                    "SATURATION_MAP"
                    if values.get("ld_saturation_map")
                    and values.get("lq_saturation_map")
                    else "CONSTANT",
                )
            ),
            winding_connection=parse_winding_connection(
                values.get("winding_connection", "STAR")
            ),
            open_winding_topology=parse_open_winding_topology(
                values.get("open_winding_topology", "DUAL_COMMON_DC")
            ),
            open_winding_udc2_v=optional_float("open_winding_udc2_v"),
            ld_saturation_map=InductanceSaturationMap.from_dict(
                values.get("ld_saturation_map")
            ),
            lq_saturation_map=InductanceSaturationMap.from_dict(
                values.get("lq_saturation_map")
            ),
        ).validated()

    @classmethod
    def example_ipmsm(cls) -> "MotorParameters":
        return cls().validated()

    @classmethod
    def example_spmsm(cls) -> "MotorParameters":
        return cls(
            pole_pairs=4,
            rs_ohm=0.03,
            ld_mh=0.45,
            lq_mh=0.45,
            flux_pm_wb=0.08,
            udc_v=320.0,
            imax_a=180.0,
            max_speed_rpm=12000.0,
            speed_points=121,
            id_min_a=None,
            pmax_kw=None,
            voltage_utilization=0.95,
            modulation="SVPWM",
            current_definition="peak",
        ).validated()
