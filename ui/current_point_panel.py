"""Read-only panel showing all values for the selected operating point."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel


class CurrentPointPanel(QGroupBox):
    FIELD_SPECS = [
        ("Speed_rpm", "转速", "rpm", 1),
        ("Torque_Nm", "转矩", "N·m", 3),
        ("Id_A", "Id", "A", 3),
        ("Iq_A", "Iq", "A", 3),
        ("Ld_uH", "当前Ld", "μH", 2),
        ("Lq_uH", "当前Lq", "μH", 2),
        ("Is_A", "电流幅值", "A", 3),
        ("Ud_V", "Ud", "V", 3),
        ("Uq_V", "Uq", "V", 3),
        ("Us_V", "电压幅值", "V", 3),
        ("CurrentUtilization", "电流利用率", "%", 1),
        ("VoltageUtilization", "电压利用率", "%", 1),
        ("Power_kW", "机械功率", "kW", 3),
        ("CopperLoss_kW", "铜耗", "kW", 3),
        ("IronLoss_kW", "铁耗估算", "kW", 3),
        ("TotalMotorLoss_kW", "总电机损耗", "kW", 3),
        ("Efficiency", "电机效率估算", "%", 2),
        ("NearMTPA", "接近MTPA", "", None),
        ("NearMTPV", "接近MTPV", "", None),
        ("Region", "运行区域", "", None),
        ("ActiveConstraint", "生效约束", "", None),
        ("SolverStatus", "求解状态", "", None),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__("当前工作点", parent)
        layout = QGridLayout(self)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(4)
        self._values: dict[str, QLabel] = {}

        rows_per_column = 10
        for index, (key, label, unit, _) in enumerate(self.FIELD_SPECS):
            row = index % rows_per_column
            column = (index // rows_per_column) * 3
            name_label = QLabel(f"{label}：")
            name_label.setProperty("role", "fieldName")
            value_label = QLabel("—")
            value_label.setMinimumWidth(95)
            unit_label = QLabel(unit)
            unit_label.setProperty("role", "unit")
            layout.addWidget(name_label, row, column)
            layout.addWidget(value_label, row, column + 1)
            layout.addWidget(unit_label, row, column + 2)
            self._values[key] = value_label

    def clear_values(self) -> None:
        for label in self._values.values():
            label.setText("—")

    def set_record(self, record: pd.Series | None) -> None:
        self.setTitle("当前工作点")
        if record is None:
            self.clear_values()
            return
        record = record.copy()
        if "Torque_Nm" not in record and "TorqueActual_Nm" in record:
            record["Torque_Nm"] = record.get("TorqueActual_Nm")
        if "Power_kW" not in record and "MechanicalPower_kW" in record:
            record["Power_kW"] = record.get("MechanicalPower_kW")
        if "Region" not in record and "ControlRegion" in record:
            record["Region"] = record.get("ControlRegion")
        for key, _, unit, decimals in self.FIELD_SPECS:
            value = record.get(key)
            if isinstance(value, (bool, np.bool_)):
                text = "是" if bool(value) else "否"
            elif isinstance(value, str):
                text = value
            else:
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    text = "—"
                else:
                    if not math.isfinite(number):
                        text = "—"
                    elif unit == "%":
                        text = f"{number * 100.0:.{decimals}f}"
                    else:
                        text = f"{number:.{decimals}f}"
            self._values[key].setText(text)

    def set_reference_point(self, kind: str, record: dict) -> None:
        """Show a theoretical point without presenting it as an operating row."""

        self.setTitle(f"理论参考点：{kind}")
        reference_record = {
            "Speed_rpm": record.get("Speed_rpm"),
            "Torque_Nm": record.get("Torque_Nm"),
            "Id_A": record.get("Id_A"),
            "Iq_A": record.get("Iq_A"),
            "Is_A": record.get("Is_A"),
            "Ud_V": float("nan"),
            "Uq_V": float("nan"),
            "Us_V": record.get("Us_V"),
            "CurrentUtilization": float("nan"),
            "VoltageUtilization": float("nan"),
            "Power_kW": float("nan"),
            "CopperLoss_kW": float("nan"),
            "NearMTPA": kind == "MTPA",
            "NearMTPV": kind == "MTPV",
            "Region": f"{kind}理论参考",
            "ActiveConstraint": "非实际运行工作点",
        }
        for key, _, unit, decimals in self.FIELD_SPECS:
            value = reference_record.get(key)
            if isinstance(value, bool):
                text = "是" if value else "否"
            elif isinstance(value, str):
                text = value
            else:
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    text = "—"
                else:
                    if not math.isfinite(number):
                        text = "—"
                    elif unit == "%":
                        text = f"{number * 100.0:.{decimals}f}"
                    else:
                        text = f"{number:.{decimals}f}"
            self._values[key].setText(text)
