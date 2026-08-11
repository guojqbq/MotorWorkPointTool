"""Result model for a single mechanical speed."""

from __future__ import annotations

from dataclasses import dataclass
from math import nan
from typing import Iterable

import pandas as pd


RESULT_COLUMNS = [
    "Speed_rpm",
    "Torque_Nm",
    "Id_A",
    "Iq_A",
    "Ld_uH",
    "Lq_uH",
    "Is_A",
    "Ud_V",
    "Uq_V",
    "Us_V",
    "Power_kW",
    "CopperLoss_kW",
    "CurrentUtilization",
    "VoltageUtilization",
    "NearMTPA",
    "NearMTPV",
    "MTPADistance_A",
    "MTPVDistance_A",
    "MTPAReferenceId_A",
    "MTPAReferenceIq_A",
    "MTPVReferenceId_A",
    "MTPVReferenceIq_A",
    "CurrentConstraintActive",
    "VoltageConstraintActive",
    "PowerConstraintActive",
    "Region",
    "ActiveConstraint",
]


@dataclass(frozen=True, slots=True)
class OperatingPoint:
    speed_rpm: float
    torque_nm: float
    id_a: float
    iq_a: float
    ld_uh: float
    lq_uh: float
    is_a: float
    ud_v: float
    uq_v: float
    us_v: float
    power_kw: float
    copper_loss_kw: float
    current_utilization: float
    voltage_utilization: float
    near_mtpa: bool
    near_mtpv: bool
    mtpa_distance_a: float
    mtpv_distance_a: float
    mtpa_reference_id_a: float
    mtpa_reference_iq_a: float
    mtpv_reference_id_a: float
    mtpv_reference_iq_a: float
    current_constraint_active: bool
    voltage_constraint_active: bool
    power_constraint_active: bool
    region: str
    active_constraint: str

    @property
    def valid(self) -> bool:
        return self.region != "无可行工作点"

    @classmethod
    def infeasible(cls, speed_rpm: float) -> "OperatingPoint":
        return cls(
            speed_rpm=speed_rpm,
            torque_nm=nan,
            id_a=nan,
            iq_a=nan,
            ld_uh=nan,
            lq_uh=nan,
            is_a=nan,
            ud_v=nan,
            uq_v=nan,
            us_v=nan,
            power_kw=nan,
            copper_loss_kw=nan,
            current_utilization=nan,
            voltage_utilization=nan,
            near_mtpa=False,
            near_mtpv=False,
            mtpa_distance_a=nan,
            mtpv_distance_a=nan,
            mtpa_reference_id_a=nan,
            mtpa_reference_iq_a=nan,
            mtpv_reference_id_a=nan,
            mtpv_reference_iq_a=nan,
            current_constraint_active=False,
            voltage_constraint_active=False,
            power_constraint_active=False,
            region="无可行工作点",
            active_constraint="无",
        )

    def as_record(self) -> dict[str, float | str]:
        return {
            "Speed_rpm": self.speed_rpm,
            "Torque_Nm": self.torque_nm,
            "Id_A": self.id_a,
            "Iq_A": self.iq_a,
            "Ld_uH": self.ld_uh,
            "Lq_uH": self.lq_uh,
            "Is_A": self.is_a,
            "Ud_V": self.ud_v,
            "Uq_V": self.uq_v,
            "Us_V": self.us_v,
            "Power_kW": self.power_kw,
            "CopperLoss_kW": self.copper_loss_kw,
            "CurrentUtilization": self.current_utilization,
            "VoltageUtilization": self.voltage_utilization,
            "NearMTPA": self.near_mtpa,
            "NearMTPV": self.near_mtpv,
            "MTPADistance_A": self.mtpa_distance_a,
            "MTPVDistance_A": self.mtpv_distance_a,
            "MTPAReferenceId_A": self.mtpa_reference_id_a,
            "MTPAReferenceIq_A": self.mtpa_reference_iq_a,
            "MTPVReferenceId_A": self.mtpv_reference_id_a,
            "MTPVReferenceIq_A": self.mtpv_reference_iq_a,
            "CurrentConstraintActive": self.current_constraint_active,
            "VoltageConstraintActive": self.voltage_constraint_active,
            "PowerConstraintActive": self.power_constraint_active,
            "Region": self.region,
            "ActiveConstraint": self.active_constraint,
        }


def operating_points_to_dataframe(
    points: Iterable[OperatingPoint],
) -> pd.DataFrame:
    records = [point.as_record() for point in points]
    return pd.DataFrame.from_records(records, columns=RESULT_COLUMNS)
