"""Mode-independent SI/peak constraints consumed by calculation modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from models.characteristic_input import CharacteristicInputMode

if TYPE_CHECKING:
    from models.motor_parameters import MotorParameters


@dataclass(frozen=True, slots=True)
class ResolvedCharacteristicLimits:
    input_mode: CharacteristicInputMode
    dc_bus_voltage_v: float
    max_voltage_dq_v: float
    max_current_vector_a: float
    max_speed_rpm: float
    target_max_torque_nm: float | None
    derived_current: bool

    def validated(self) -> "ResolvedCharacteristicLimits":
        errors: list[str] = []
        for label, value in (
            ("直流母线电压 Udc", self.dc_bus_voltage_v),
            ("最大dq电压矢量峰值", self.max_voltage_dq_v),
            ("最大定子电流矢量峰值", self.max_current_vector_a),
            ("最大转速", self.max_speed_rpm),
        ):
            if not np.isfinite(value) or value <= 0:
                errors.append(f"{label}必须是有限正数。")
        if self.target_max_torque_nm is not None and (
            not np.isfinite(self.target_max_torque_nm)
            or self.target_max_torque_nm <= 0
        ):
            errors.append("目标最大转矩必须是有限正数。")
        if errors:
            raise ValueError("\n".join(errors))
        return self

    @property
    def max_voltage_v(self) -> float:
        """Compatibility alias for major-version-1 integrations."""

        return self.max_voltage_dq_v

    @property
    def speed_scan_max_rpm(self) -> float:
        """Compatibility alias for major-version-1 integrations."""

        return self.max_speed_rpm

    @classmethod
    def from_legacy_motor(
        cls, parameters: "MotorParameters"
    ) -> "ResolvedCharacteristicLimits":
        """Adapt historical Udc/Imax values as direct vector constraints."""

        return cls(
            input_mode=CharacteristicInputMode.UDC_IMAX_NMAX,
            dc_bus_voltage_v=float(parameters.udc_v),
            max_voltage_dq_v=float(parameters.umax_v),
            max_current_vector_a=float(parameters.imax_peak_a),
            max_speed_rpm=float(parameters.max_speed_rpm),
            target_max_torque_nm=None,
            derived_current=False,
        ).validated()
