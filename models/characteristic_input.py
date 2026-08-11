"""User-facing Udc-based characteristic input modes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping

import numpy as np


class CharacteristicInputMode(str, Enum):
    UDC_TMAX_NMAX = "UDC_TMAX_NMAX"
    UDC_IMAX_NMAX = "UDC_IMAX_NMAX"


_LEGACY_MODE_MAP = {
    "PERFORMANCE_TARGET": CharacteristicInputMode.UDC_TMAX_NMAX,
    "ELECTRICAL_LIMIT": CharacteristicInputMode.UDC_IMAX_NMAX,
}


def parse_characteristic_input_mode(value: object) -> CharacteristicInputMode:
    if isinstance(value, CharacteristicInputMode):
        return value
    text = str(value)
    if text in _LEGACY_MODE_MAP:
        return _LEGACY_MODE_MAP[text]
    return CharacteristicInputMode(text)


@dataclass(frozen=True, slots=True)
class CharacteristicInput:
    """Mode-specific GUI values before conversion to SI/peak constraints."""

    input_mode: CharacteristicInputMode = (
        CharacteristicInputMode.UDC_IMAX_NMAX
    )
    dc_bus_voltage_v: float = 844.0
    max_torque_nm: float = 486.0
    max_current_vector_a: float = 310.0
    max_speed_rpm: float = 30000.0

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        mode = parse_characteristic_input_mode(self.input_mode)
        if (
            not np.isfinite(self.dc_bus_voltage_v)
            or self.dc_bus_voltage_v <= 0
        ):
            errors.append("直流母线电压 Udc 必须是有限正数。")
        if not np.isfinite(self.max_speed_rpm) or self.max_speed_rpm <= 0:
            errors.append("最大转速 nmax 必须是有限正数。")
        if mode == CharacteristicInputMode.UDC_TMAX_NMAX:
            if not np.isfinite(self.max_torque_nm) or self.max_torque_nm <= 0:
                errors.append("最大转矩 Tmax 必须是有限正数。")
        elif (
            not np.isfinite(self.max_current_vector_a)
            or self.max_current_vector_a <= 0
        ):
            errors.append("最大定子电流矢量 Is_max 必须是有限正数。")
        return errors

    def validated(self) -> "CharacteristicInput":
        errors = self.validation_errors()
        if errors:
            raise ValueError("\n".join(errors))
        return self

    def as_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["input_mode"] = parse_characteristic_input_mode(
            self.input_mode
        ).value
        return values

    def calculation_dict(self) -> dict[str, Any]:
        """Return common values plus only the active mode-specific value."""

        mode = parse_characteristic_input_mode(self.input_mode)
        values: dict[str, Any] = {
            "input_mode": mode.value,
            "dc_bus_voltage_v": self.dc_bus_voltage_v,
            "max_speed_rpm": self.max_speed_rpm,
        }
        if mode == CharacteristicInputMode.UDC_TMAX_NMAX:
            values["max_torque_nm"] = self.max_torque_nm
        else:
            values["max_current_vector_a"] = self.max_current_vector_a
        return values

    @classmethod
    def from_dict(
        cls, values: Mapping[str, Any] | None
    ) -> "CharacteristicInput":
        if not values:
            return cls()
        mode = parse_characteristic_input_mode(
            values.get(
                "input_mode",
                CharacteristicInputMode.UDC_IMAX_NMAX.value,
            )
        )
        return cls(
            input_mode=mode,
            dc_bus_voltage_v=float(
                values.get(
                    "dc_bus_voltage_v",
                    values.get("Udc", values.get("udc_v", 844.0)),
                )
            ),
            max_torque_nm=float(values.get("max_torque_nm", 486.0)),
            max_current_vector_a=float(
                values.get(
                    "max_current_vector_a",
                    values.get(
                        "max_iq_a",
                        values.get("Imax", values.get("imax_a", 310.0)),
                    ),
                )
            ),
            max_speed_rpm=float(
                values.get(
                    "max_speed_rpm",
                    values.get("speed_scan_max_rpm", 30000.0),
                )
            ),
        ).validated()
