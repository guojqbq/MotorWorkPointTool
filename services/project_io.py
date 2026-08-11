"""Versioned JSON persistence for motor and inverter parameters."""

from __future__ import annotations

import json
from math import sqrt
from pathlib import Path
from typing import Any

from calculation.characteristic_limit_resolver import (
    characteristic_input_from_legacy_motor,
    legacy_iq_limit_to_vector_current_input,
)
from models.characteristic_input import (
    CharacteristicInput,
    CharacteristicInputMode,
)
from models.motor_parameters import MotorParameters, ParameterValidationError
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings


PROJECT_FORMAT = "PMSMPerformanceToolParameters"
PROJECT_VERSION = "1.4"
SCHEMA_VERSION = "1.4"
UNITS = {
    "Rs": "ohm (stator phase resistance)",
    "Ld_mH": "mH",
    "Lq_mH": "mH",
    "flux_pm": "Wb",
    "Udc": "V",
    "Imax": "A (definition given by current_definition)",
    "max_speed_rpm": "rpm",
    "Id_min": "A (definition given by current_definition)",
    "Pmax_kW": "kW",
    "voltage_utilization": "dimensionless",
    "dc_bus_voltage_v": "V",
    "max_current_vector_a": "A (definition given by current_definition)",
    "saturation_map_values": "H",
    "open_winding_udc2_v": "V",
}


def save_project(
    parameters: MotorParameters,
    loss_parameters: LossModelParameters,
    map_settings: MapCalculationSettings,
    path: str | Path,
    *,
    characteristic_input: CharacteristicInput | None = None,
) -> Path:
    parameters.validated()
    loss_parameters.validated()
    map_settings.validated()
    target = Path(path)
    characteristic = (
        characteristic_input
        or characteristic_input_from_legacy_motor(parameters)
    ).validated()
    payload = {
        "format": PROJECT_FORMAT,
        "version": PROJECT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "input_mode": characteristic.input_mode.value,
        "units": UNITS,
        "parameters": parameters.as_input_dict(),
        "characteristic_input": characteristic.as_dict(),
        "loss_model": loss_parameters.as_dict(),
        "map_settings": map_settings.as_dict(),
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def save_parameters(parameters: MotorParameters, path: str | Path) -> Path:
    """Backward-compatible motor-only save entry point."""

    return save_project(
        parameters,
        LossModelParameters(),
        MapCalculationSettings(),
        path,
    )


def _load_payload(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload: Any = json.loads(source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ParameterValidationError(
            [f"JSON文件格式错误：第{exc.lineno}行，第{exc.colno}列。"]
        ) from exc

    if not isinstance(payload, dict):
        raise ParameterValidationError(["参数文件的根节点必须是JSON对象。"])
    if payload.get("format") != PROJECT_FORMAT:
        raise ParameterValidationError(
            [f"不是受支持的参数文件，format 应为 {PROJECT_FORMAT}。"]
        )
    version = str(payload.get("version", ""))
    if not version.startswith("1."):
        raise ParameterValidationError(
            [f"不支持参数文件版本 {version or '（缺失）'}。"]
        )
    values = payload.get("parameters")
    if not isinstance(values, dict):
        raise ParameterValidationError(["参数文件缺少 parameters 对象。"])
    return payload


def load_project(
    path: str | Path,
) -> tuple[MotorParameters, LossModelParameters, MapCalculationSettings]:
    """Load any major-version-1 project, defaulting fields added in V0.2."""

    parameters, losses, settings, _characteristic = (
        load_project_with_characteristic(path)
    )
    return parameters, losses, settings


def load_project_with_characteristic(
    path: str | Path,
) -> tuple[
    MotorParameters,
    LossModelParameters,
    MapCalculationSettings,
    CharacteristicInput,
]:
    """Load major-version-1 projects including the active input mode."""

    payload = _load_payload(path)
    parameters = MotorParameters.from_input_dict(payload["parameters"])
    losses = LossModelParameters.from_dict(payload.get("loss_model"))
    settings = MapCalculationSettings.from_dict(payload.get("map_settings"))
    raw_characteristic = payload.get("characteristic_input")
    if isinstance(raw_characteristic, dict):
        values = dict(raw_characteristic)
        root_mode = payload.get("input_mode")
        if "input_mode" not in values and root_mode is not None:
            values["input_mode"] = root_mode
        raw_mode = str(
            values.get(
                "input_mode",
                CharacteristicInputMode.UDC_IMAX_NMAX.value,
            )
        )
        if raw_mode == "PERFORMANCE_TARGET":
            characteristic = CharacteristicInput(
                input_mode=CharacteristicInputMode.UDC_TMAX_NMAX,
                dc_bus_voltage_v=float(parameters.udc_v),
                max_torque_nm=float(values.get("max_torque_nm", 100.0)),
                max_current_vector_a=float(parameters.imax_a),
                max_speed_rpm=float(
                    values.get(
                        "max_speed_rpm", parameters.max_speed_rpm
                    )
                ),
            ).validated()
        elif raw_mode == "ELECTRICAL_LIMIT":
            old_voltage_limit = float(
                values.get("max_voltage_v", parameters.umax_v)
            )
            denominator = (
                sqrt(3.0) if parameters.modulation == "SVPWM" else 2.0
            )
            equivalent_udc = (
                old_voltage_limit
                * denominator
                / parameters.voltage_utilization
            )
            old_iq_input = float(
                values.get("max_iq_a", parameters.imax_a)
            )
            characteristic = CharacteristicInput(
                input_mode=CharacteristicInputMode.UDC_IMAX_NMAX,
                dc_bus_voltage_v=equivalent_udc,
                max_current_vector_a=(
                    legacy_iq_limit_to_vector_current_input(
                        parameters, old_iq_input
                    )
                ),
                max_torque_nm=float(values.get("max_torque_nm", 100.0)),
                max_speed_rpm=float(
                    values.get(
                        "speed_scan_max_rpm", parameters.max_speed_rpm
                    )
                ),
            ).validated()
        else:
            values.setdefault("dc_bus_voltage_v", parameters.udc_v)
            values.setdefault("max_speed_rpm", parameters.max_speed_rpm)
            characteristic = CharacteristicInput.from_dict(values)
    else:
        characteristic = characteristic_input_from_legacy_motor(parameters)
        # Some early major-version-1 files stored an already converted dq
        # vector limit as ``Umax`` alongside the historical ``Imax`` field.
        # Prefer that explicit peak value over reinterpreting it as Udc.
        legacy_values = payload["parameters"]
        explicit_umax = legacy_values.get(
            "Umax", legacy_values.get("umax_v")
        )
        if explicit_umax not in (None, ""):
            denominator = (
                sqrt(3.0) if parameters.modulation == "SVPWM" else 2.0
            )
            equivalent_udc = (
                float(explicit_umax)
                * denominator
                / parameters.voltage_utilization
            )
            characteristic = CharacteristicInput(
                input_mode=CharacteristicInputMode.UDC_IMAX_NMAX,
                dc_bus_voltage_v=equivalent_udc,
                max_current_vector_a=float(parameters.imax_a),
                max_speed_rpm=float(parameters.max_speed_rpm),
            ).validated()
    return parameters, losses, settings, characteristic


def load_parameters(path: str | Path) -> MotorParameters:
    """Backward-compatible motor-only load entry point."""

    parameters, _losses, _settings = load_project(path)
    return parameters
