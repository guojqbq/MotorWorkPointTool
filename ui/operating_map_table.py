"""Filterable table for all internal torque-speed operating points."""

from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from models.operating_map import OperatingMapResult
from ui.operating_point_table import OperatingPointTable


class OperatingMapTable(QWidget):
    pointSelected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.speed_filter = QComboBox()
        self.torque_min = QDoubleSpinBox()
        self.torque_max = QDoubleSpinBox()
        for spinbox in (self.torque_min, self.torque_max):
            spinbox.setRange(0.0, 1e9)
            spinbox.setDecimals(2)
            spinbox.setSuffix(" N·m")
            spinbox.setKeyboardTracking(False)
        self.feasible_only = QCheckBox("仅可行点")
        self.feasible_only.setChecked(True)
        self.region_filter = QComboBox()
        self.region_filter.addItem("全部区域", "all")
        self.region_filter.addItem("电流约束激活", "current")
        self.region_filter.addItem("电压约束激活", "voltage")
        self.region_filter.addItem("弱磁/MTPV", "field_weakening")
        self.efficiency_filter_enabled = QCheckBox("效率范围")
        self.efficiency_min = QDoubleSpinBox()
        self.efficiency_max = QDoubleSpinBox()
        for spinbox in (self.efficiency_min, self.efficiency_max):
            spinbox.setRange(0.0, 100.0)
            spinbox.setDecimals(1)
            spinbox.setSuffix("%")
            spinbox.setKeyboardTracking(False)
        self.efficiency_min.setValue(0.0)
        self.efficiency_max.setValue(100.0)
        self.profile_label = QLabel()
        self.profile_label.setProperty("role", "muted")

        controls.addWidget(QLabel("转速："))
        controls.addWidget(self.speed_filter)
        controls.addWidget(QLabel("转矩："))
        controls.addWidget(self.torque_min)
        controls.addWidget(QLabel("至"))
        controls.addWidget(self.torque_max)
        controls.addWidget(self.feasible_only)
        controls.addWidget(self.region_filter)
        controls.addWidget(self.efficiency_filter_enabled)
        controls.addWidget(self.efficiency_min)
        controls.addWidget(self.efficiency_max)
        controls.addStretch(1)
        controls.addWidget(self.profile_label)
        layout.addLayout(controls)

        self.table = OperatingPointTable()
        layout.addWidget(self.table, 1)
        self._result: OperatingMapResult | None = None
        self._source_indices = np.array([], dtype=int)

        self.speed_filter.currentIndexChanged.connect(self._apply_filters)
        self.torque_min.valueChanged.connect(self._apply_filters)
        self.torque_max.valueChanged.connect(self._apply_filters)
        self.feasible_only.toggled.connect(self._apply_filters)
        self.region_filter.currentIndexChanged.connect(self._apply_filters)
        self.efficiency_filter_enabled.toggled.connect(self._apply_filters)
        self.efficiency_min.valueChanged.connect(self._apply_filters)
        self.efficiency_max.valueChanged.connect(self._apply_filters)
        self.table.pointSelected.connect(self._table_row_selected)

    def set_result(self, result: OperatingMapResult) -> None:
        self._result = result
        self.profile_label.setText(
            f"{'预览' if result.is_preview else '全量'} "
            f"{result.shape[0]}×{result.shape[1]}"
        )
        self.speed_filter.blockSignals(True)
        self.speed_filter.clear()
        self.speed_filter.addItem("全部", None)
        for speed in result.speed_grid_rpm:
            self.speed_filter.addItem(f"{speed:.1f} rpm", float(speed))
        self.speed_filter.blockSignals(False)
        max_torque = max(float(np.nanmax(result.maximum_torque_nm)), 1.0)
        self.torque_min.blockSignals(True)
        self.torque_max.blockSignals(True)
        self.torque_min.setMaximum(max_torque * 1.1)
        self.torque_max.setMaximum(max_torque * 1.1)
        self.torque_min.setValue(0.0)
        self.torque_max.setValue(max_torque * 1.01)
        self.torque_min.blockSignals(False)
        self.torque_max.blockSignals(False)
        self._apply_filters()

    def _apply_filters(self, *_args) -> None:
        if self._result is None:
            self._source_indices = np.array([], dtype=int)
            self.table.set_dataframe(pd.DataFrame())
            return
        frame = self._result.dataframe
        mask = np.ones(len(frame), dtype=bool)
        speed = self.speed_filter.currentData()
        if speed is not None:
            mask &= np.isclose(frame["Speed_rpm"].to_numpy(float), float(speed))
        request = frame["TorqueRequest_Nm"].to_numpy(float)
        mask &= request >= self.torque_min.value()
        mask &= request <= self.torque_max.value()
        if self.feasible_only.isChecked():
            mask &= frame["IsFeasible"].to_numpy(bool)
        region_filter = str(self.region_filter.currentData())
        if region_filter == "current":
            mask &= frame["CurrentConstraintActive"].to_numpy(bool)
        elif region_filter == "voltage":
            mask &= frame["VoltageConstraintActive"].to_numpy(bool)
        elif region_filter == "field_weakening":
            mask &= frame["ControlRegion"].astype(str).isin(
                ["FIELD_WEAKENING", "MTPV", "OTHER"]
            ).to_numpy()
        if self.efficiency_filter_enabled.isChecked():
            efficiency = frame["Efficiency"].to_numpy(float) * 100.0
            mask &= np.isfinite(efficiency)
            mask &= efficiency >= self.efficiency_min.value()
            mask &= efficiency <= self.efficiency_max.value()
        self._source_indices = np.flatnonzero(mask)
        self.table.set_dataframe(frame.iloc[self._source_indices].reset_index(drop=True))

    def _table_row_selected(self, displayed_row: int) -> None:
        if (
            self._result is None
            or not 0 <= displayed_row < len(self._source_indices)
        ):
            return
        source_row = int(self._source_indices[displayed_row])
        record = self._result.dataframe.iloc[source_row]
        self.pointSelected.emit(source_row)

    def select_point(self, speed_index: int, torque_index: int) -> None:
        if self._result is None:
            return
        source_row = self._result.flat_index(speed_index, torque_index)
        positions = np.flatnonzero(self._source_indices == source_row)
        if positions.size:
            self.table.select_index(int(positions[0]))

    def select_map_index(self, map_index: int) -> None:
        if self._result is None:
            return
        speed_index, torque_index = self._result.unravel_index(map_index)
        self.select_point(speed_index, torque_index)
