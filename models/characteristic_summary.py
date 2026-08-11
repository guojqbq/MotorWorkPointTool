"""Post-solve characteristic metrics displayed independently of point selection."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from models.resolved_characteristic_limits import ResolvedCharacteristicLimits


@dataclass(frozen=True, slots=True)
class CharacteristicSummary:
    maximum_torque_nm: float
    maximum_torque_id_a: float
    maximum_torque_iq_a: float
    base_speed_rpm: float
    maximum_power_kw: float
    terminal_speed_torque_nm: float

    @classmethod
    def from_external_characteristic(
        cls,
        dataframe: pd.DataFrame,
        limits: ResolvedCharacteristicLimits,
    ) -> "CharacteristicSummary":
        valid = dataframe.dropna(
            subset=["Speed_rpm", "Torque_Nm", "Id_A", "Iq_A"]
        )
        if valid.empty:
            raise ValueError("外特性没有可用于汇总的工作点。")
        maximum_position = int(
            np.nanargmax(valid["Torque_Nm"].to_numpy(dtype=float))
        )
        maximum_row = valid.iloc[maximum_position]
        voltage = valid["VoltageUtilization"].to_numpy(dtype=float)
        voltage_positions = np.flatnonzero(voltage >= 0.98)
        base_speed = (
            float(valid.iloc[max(int(voltage_positions[0]) - 1, 0)]["Speed_rpm"])
            if voltage_positions.size
            else float(valid.iloc[-1]["Speed_rpm"])
        )
        return cls(
            maximum_torque_nm=float(maximum_row["Torque_Nm"]),
            maximum_torque_id_a=float(maximum_row["Id_A"]),
            maximum_torque_iq_a=float(maximum_row["Iq_A"]),
            base_speed_rpm=base_speed,
            maximum_power_kw=float(np.nanmax(valid["Power_kW"])),
            terminal_speed_torque_nm=float(valid.iloc[-1]["Torque_Nm"]),
        )
