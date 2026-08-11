"""Convert either Udc-based input mode to standard calculation constraints."""

from __future__ import annotations

from math import hypot

import numpy as np

from calculation.equations import dq_voltage, electromagnetic_torque
from calculation.reference_trajectories import solve_mtpa_point
from models.characteristic_input import (
    CharacteristicInput,
    CharacteristicInputMode,
    parse_characteristic_input_mode,
)
from models.motor_parameters import MotorParameters
from models.resolved_characteristic_limits import ResolvedCharacteristicLimits


class CharacteristicResolutionError(ValueError):
    """Raised when valid GUI inputs cannot form feasible standard limits."""


def _peak_current(parameters: MotorParameters, input_current_a: float) -> float:
    return (
        float(input_current_a)
        * parameters.current_scale_to_peak
        * parameters.winding_connection.line_to_winding_current_factor
    )


def _input_current(parameters: MotorParameters, peak_current_a: float) -> float:
    return float(peak_current_a) / (
        parameters.current_scale_to_peak
        * parameters.winding_connection.line_to_winding_current_factor
    )


def dc_bus_to_dq_voltage_limit(
    parameters: MotorParameters, dc_bus_voltage_v: float
) -> float:
    """Convert Udc to maximum dq voltage-vector peak magnitude."""

    return parameters.dq_voltage_limit_from_udc(dc_bus_voltage_v)


def _mtpa_point_for_iq(
    parameters: MotorParameters, iq_peak_a: float
) -> tuple[float, float, float]:
    """Recover the old iq_max semantics for major-version-1 JSON migration."""

    iq_target = float(iq_peak_a)
    if iq_target <= 0.0 or not np.isfinite(iq_target):
        raise CharacteristicResolutionError(
            "旧版最大q轴电流 iq_max 必须是有限正数。"
        )
    if parameters.motor_type == "SPMSM":
        torque = float(electromagnetic_torque(0.0, iq_target, parameters))
        return 0.0, iq_target, torque

    current_hint = max(2.0 * iq_target, 1.0)
    low_torque = 0.0
    low_point = solve_mtpa_point(
        parameters, low_torque, current_hint_a=current_hint
    )
    high_torque = max(
        float(electromagnetic_torque(0.0, iq_target, parameters)), 1.0
    )
    high_point = solve_mtpa_point(
        parameters, high_torque, current_hint_a=current_hint
    )
    for _ in range(60):
        if high_point.iq_a >= iq_target:
            break
        high_torque *= 2.0
        high_point = solve_mtpa_point(
            parameters, high_torque, current_hint_a=current_hint
        )
    else:
        raise CharacteristicResolutionError(
            "无法恢复旧版 iq_max 对应的MTPA电流矢量。"
        )

    for _ in range(70):
        middle_torque = 0.5 * (low_torque + high_torque)
        middle_point = solve_mtpa_point(
            parameters, middle_torque, current_hint_a=current_hint
        )
        if abs(middle_point.iq_a - iq_target) <= max(
            1e-9, 1e-9 * iq_target
        ):
            return middle_point.id_a, iq_target, middle_torque
        if middle_point.iq_a < iq_target:
            low_torque = middle_torque
            low_point = middle_point
        else:
            high_torque = middle_torque
            high_point = middle_point
    best = min(
        (low_point, high_point),
        key=lambda point: abs(point.iq_a - iq_target),
    )
    return best.id_a, iq_target, float(
        electromagnetic_torque(best.id_a, iq_target, parameters)
    )


def legacy_iq_limit_to_vector_current_input(
    parameters: MotorParameters, iq_input_a: float
) -> float:
    """Convert old iq_max input to the new Is_max input convention."""

    iq_peak = _peak_current(parameters, iq_input_a)
    id_a, iq_a, _torque = _mtpa_point_for_iq(parameters, iq_peak)
    return _input_current(parameters, hypot(id_a, iq_a))


def characteristic_input_from_legacy_motor(
    parameters: MotorParameters,
) -> CharacteristicInput:
    """Represent historical Udc/Imax as the new direct-vector mode."""

    return CharacteristicInput(
        input_mode=CharacteristicInputMode.UDC_IMAX_NMAX,
        dc_bus_voltage_v=float(parameters.udc_v),
        max_torque_nm=486.0,
        max_current_vector_a=float(parameters.imax_a),
        max_speed_rpm=float(parameters.max_speed_rpm),
    ).validated()


def resolve_characteristic_limits(
    parameters: MotorParameters, inputs: CharacteristicInput
) -> ResolvedCharacteristicLimits:
    parameters.validated()
    inputs.validated()
    mode = parse_characteristic_input_mode(inputs.input_mode)
    dc_bus_voltage = float(inputs.dc_bus_voltage_v)
    voltage_limit = dc_bus_to_dq_voltage_limit(
        parameters, dc_bus_voltage
    )

    target_torque: float | None = None
    if mode == CharacteristicInputMode.UDC_TMAX_NMAX:
        target_torque = float(inputs.max_torque_nm)
        current_guess = target_torque / max(
            1.5 * parameters.pole_pairs * parameters.flux_pm_wb, 1e-12
        )
        mtpa = solve_mtpa_point(
            parameters,
            target_torque,
            current_hint_a=max(2.0 * current_guess, 1.0),
        )
        current_limit = float(mtpa.is_a)
        if (
            parameters.id_min_peak_a is not None
            and mtpa.id_a
            < parameters.id_min_peak_a - 1e-9 * current_limit
        ):
            raise CharacteristicResolutionError(
                "目标最大转矩的MTPA点违反当前负向Id限制。"
            )
        ud_v, uq_v = dq_voltage(mtpa.id_a, mtpa.iq_a, 0.0, parameters)
        required_voltage = float(np.hypot(ud_v, uq_v))
        if required_voltage > voltage_limit * (1.0 + 1e-9):
            raise CharacteristicResolutionError(
                "当前Udc无法支持目标最大转矩对应的MTPA电流点："
                f"需要 {required_voltage:.6g} V，"
                f"可用dq电压为 {voltage_limit:.6g} V。"
            )
        derived_current = True
    else:
        current_limit = _peak_current(
            parameters, inputs.max_current_vector_a
        )
        derived_current = False

    if parameters.has_saturation_data:
        assert parameters.ld_saturation_map is not None
        saturation_map = parameters.ld_saturation_map
        if (
            saturation_map.id_axis_a[0] > -current_limit
            or saturation_map.id_axis_a[-1] < 0.0
            or saturation_map.iq_axis_a[0] > 0.0
            or saturation_map.iq_axis_a[-1] < current_limit
        ):
            raise CharacteristicResolutionError(
                "超出饱和电感Map范围：当前电流限制需要覆盖 "
                f"Id=[{-current_limit:.3f}, 0] A、Iq=[0, {current_limit:.3f}] A；"
                f"导入表范围为 Id=[{saturation_map.id_axis_a[0]:.3f}, "
                f"{saturation_map.id_axis_a[-1]:.3f}] A、"
                f"Iq=[{saturation_map.iq_axis_a[0]:.3f}, "
                f"{saturation_map.iq_axis_a[-1]:.3f}] A。"
            )

    return ResolvedCharacteristicLimits(
        input_mode=mode,
        dc_bus_voltage_v=dc_bus_voltage,
        max_voltage_dq_v=float(voltage_limit),
        max_current_vector_a=float(current_limit),
        max_speed_rpm=float(inputs.max_speed_rpm),
        target_max_torque_nm=target_torque,
        derived_current=derived_current,
    ).validated()
