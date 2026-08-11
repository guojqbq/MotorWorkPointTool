"""Operating-region and active-constraint classification."""

from __future__ import annotations

from models.motor_parameters import MotorParameters


def classify_operating_point(
    parameters: MotorParameters,
    *,
    id_a: float,
    current_utilization: float,
    voltage_utilization: float,
    power_w: float,
    current_limit_a: float,
    near_mtpa: bool = False,
    near_mtpv: bool = False,
    active_tolerance: float = 5e-3,
) -> tuple[str, str]:
    active: list[str] = []

    if current_utilization >= 1.0 - active_tolerance:
        active.append("电流")
    if voltage_utilization >= 1.0 - active_tolerance:
        active.append("电压")
    if parameters.id_min_peak_a is not None:
        id_tolerance = active_tolerance * max(current_limit_a, 1.0)
        if id_a <= parameters.id_min_peak_a + id_tolerance:
            active.append("Id")
    if parameters.pmax_w is not None and parameters.pmax_w > 0:
        if power_w / parameters.pmax_w >= 1.0 - active_tolerance:
            active.append("功率")

    if "功率" in active:
        region = "功率限制"
    elif "电压" in active and near_mtpv:
        region = "MTPV"
    elif "电压" in active:
        region = "弱磁"
    elif near_mtpa:
        region = "MTPA"
    elif "电流" in active:
        region = "电流限制"
    else:
        region = "MTPA"

    return region, "+".join(active) if active else "无"
