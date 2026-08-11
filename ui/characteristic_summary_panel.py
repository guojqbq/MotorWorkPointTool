"""Always-visible summary of resolved constraints and characteristic metrics."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QGroupBox

from models.characteristic_input import CharacteristicInputMode
from models.characteristic_summary import CharacteristicSummary
from models.resolved_characteristic_limits import ResolvedCharacteristicLimits


class CharacteristicSummaryPanel(QGroupBox):
    def __init__(self, parent=None) -> None:
        super().__init__("最终采用约束与特性摘要", parent)
        layout = QGridLayout(self)
        self._values: dict[str, QLabel] = {}
        rows = [
            ("mode", "输入方式"),
            ("udc", "母线电压 Udc"),
            ("umax", "Umax（dq峰值）"),
            ("ismax", "Is_max（矢量峰值）"),
            ("tmax", "最大转矩"),
            ("mtpa", "最大转矩点 Id / Iq"),
            ("speed", "最大转速 nmax"),
            ("base", "基速"),
            ("power", "最大功率"),
            ("terminal", "最高转速处转矩"),
        ]
        for row, (key, label) in enumerate(rows):
            layout.addWidget(QLabel(label), row // 4 * 2, row % 4)
            value = QLabel("—")
            value.setProperty("role", "value")
            layout.addWidget(value, row // 4 * 2 + 1, row % 4)
            self._values[key] = value
        self.notice = QLabel("尚未计算")
        self.notice.setWordWrap(True)
        self.notice.setProperty("role", "muted")
        layout.addWidget(self.notice, 6, 0, 1, 4)

    def clear_values(self) -> None:
        for value in self._values.values():
            value.setText("—")
        self.notice.setText("尚未计算")

    def set_result(
        self,
        limits: ResolvedCharacteristicLimits,
        summary: CharacteristicSummary,
    ) -> None:
        mode_text = (
            "Udc + Tmax + nmax"
            if limits.input_mode
            == CharacteristicInputMode.UDC_TMAX_NMAX
            else "Udc + Is_max + nmax"
        )
        values = {
            "mode": mode_text,
            "udc": f"{limits.dc_bus_voltage_v:.3f} V",
            "umax": f"{limits.max_voltage_dq_v:.3f} V",
            "ismax": f"{limits.max_current_vector_a:.3f} A",
            "tmax": f"{summary.maximum_torque_nm:.3f} N·m",
            "mtpa": (
                f"{summary.maximum_torque_id_a:.3f} / "
                f"{summary.maximum_torque_iq_a:.3f} A"
            ),
            "speed": f"{limits.max_speed_rpm:.1f} rpm",
            "base": f"{summary.base_speed_rpm:.1f} rpm",
            "power": f"{summary.maximum_power_kw:.3f} kW",
            "terminal": f"{summary.terminal_speed_torque_nm:.3f} N·m",
        }
        for key, text in values.items():
            self._values[key].setText(text)
        self.notice.setText(
            "该最大电流为依据目标最大转矩反算得到的等效限制。"
            if limits.derived_current
            else "最大定子电流矢量 Is_max 由用户直接输入。"
        )
