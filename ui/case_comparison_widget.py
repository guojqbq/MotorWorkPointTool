"""Visual comparison of saved external, efficiency, and delta results."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from services.case_repository import SavedCase, compare_case_points
from ui.plot_theme import performance_colormap


class _MapView(QWidget):
    def __init__(self, *, difference: bool = False, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.plot = pg.PlotWidget(background="w")
        self.plot.setLabel("bottom", "机械转速", units="rpm")
        self.plot.setLabel("left", "目标转矩", units="N·m")
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        cmap = (
            pg.ColorMap(
                np.array([0.0, 0.5, 1.0]),
                np.array([[37, 99, 235], [255, 255, 255], [220, 38, 38]], dtype=np.ubyte),
            )
            if difference
            else performance_colormap()
        )
        self.mesh = pg.PColorMeshItem(colorMap=cmap)
        self.plot.addItem(self.mesh)
        self.color_bar = pg.ColorBarItem(colorMap=cmap, interactive=False)
        self.plot.plotItem.layout.addItem(self.color_bar, 2, 2)
        layout.addWidget(self.plot)

    def set_nodes(
        self, speeds: np.ndarray, torques: np.ndarray, values: np.ndarray, label: str
    ) -> None:
        if min(values.shape, default=0) < 2:
            self.mesh.setData()
            return
        corners = np.stack(
            (
                values[:-1, :-1], values[1:, :-1],
                values[:-1, 1:], values[1:, 1:],
            )
        )
        valid = np.all(np.isfinite(corners), axis=0)
        cells = np.where(valid, np.mean(corners, axis=0), np.nan)
        x, y = np.meshgrid(speeds, torques, indexing="ij")
        finite = cells[np.isfinite(cells)]
        if finite.size == 0:
            self.mesh.setData()
            return
        low, high = float(np.min(finite)), float(np.max(finite))
        if np.isclose(low, high):
            high = low + max(abs(low) * 1e-6, 1e-9)
        self.mesh.setLevels((low, high))
        self.mesh.setData(x, y, cells, autoLevels=False)
        self.color_bar.setLevels((low, high))
        self.color_bar.axis.setLabel(label)


class CaseComparisonWidget(QTabWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cases: list[SavedCase] = []
        self.summary = QTableWidget(0, 6)
        self.summary.setHorizontalHeaderLabels(
            ["案例", "接法", "电感模型", "最大转矩", "最高效率", "备注"]
        )
        self.addTab(self.summary, "摘要")

        efficiency_page = QWidget()
        efficiency_layout = QVBoxLayout(efficiency_page)
        efficiency_controls = QHBoxLayout()
        efficiency_controls.addWidget(QLabel("案例"))
        self.efficiency_case = QComboBox()
        efficiency_controls.addWidget(self.efficiency_case)
        efficiency_controls.addStretch(1)
        efficiency_layout.addLayout(efficiency_controls)
        self.efficiency_map = _MapView()
        efficiency_layout.addWidget(self.efficiency_map)
        self.addTab(efficiency_page, "Efficiency Map")

        difference_page = QWidget()
        difference_layout = QVBoxLayout(difference_page)
        difference_controls = QHBoxLayout()
        self.case_a = QComboBox()
        self.case_b = QComboBox()
        self.delta_variable = QComboBox()
        self.delta_variable.addItem("ΔEfficiency", "DeltaEfficiency")
        self.delta_variable.addItem("ΔTorque", "DeltaTorque_Nm")
        for label, editor in (("A", self.case_a), ("B", self.case_b), ("变量", self.delta_variable)):
            difference_controls.addWidget(QLabel(label))
            difference_controls.addWidget(editor)
        difference_controls.addStretch(1)
        difference_layout.addLayout(difference_controls)
        self.difference_map = _MapView(difference=True)
        difference_layout.addWidget(self.difference_map)
        self.addTab(difference_page, "A-B 差值")
        self.efficiency_case.currentIndexChanged.connect(self._update_efficiency)
        self.case_a.currentIndexChanged.connect(self._update_difference)
        self.case_b.currentIndexChanged.connect(self._update_difference)
        self.delta_variable.currentIndexChanged.connect(self._update_difference)

    def set_cases(self, cases: list[SavedCase]) -> None:
        self._cases = list(cases)
        for combo in (self.efficiency_case, self.case_a, self.case_b):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([case.name for case in cases])
            combo.blockSignals(False)
        if len(cases) > 1:
            self.case_b.setCurrentIndex(1)
        self.summary.setRowCount(len(cases))
        for row, case in enumerate(cases):
            motor = case.metadata.get("motor_parameters", {})
            torque = case.external.get("Torque_Nm", np.array([np.nan]))
            efficiency = case.operating_points.get("Efficiency", np.array([np.nan]))
            values = (
                case.name,
                str(motor.get("winding_connection", "STAR")),
                str(motor.get("inductance_model", "CONSTANT")),
                f"{np.nanmax(np.asarray(torque, dtype=float)):.3f}",
                f"{100.0 * np.nanmax(np.asarray(efficiency, dtype=float)):.2f}%",
                case.note,
            )
            for column, value in enumerate(values):
                self.summary.setItem(row, column, QTableWidgetItem(value))
        self._update_efficiency()
        self._update_difference()

    def _update_efficiency(self) -> None:
        index = self.efficiency_case.currentIndex()
        if not 0 <= index < len(self._cases):
            return
        speeds, torques, values = self._cases[index].efficiency_matrix()
        self.efficiency_map.set_nodes(speeds, torques, values * 100.0, "效率 [%]")

    def _update_difference(self) -> None:
        a, b = self.case_a.currentIndex(), self.case_b.currentIndex()
        if not (0 <= a < len(self._cases) and 0 <= b < len(self._cases)):
            return
        frame = compare_case_points(self._cases[a], self._cases[b])
        column = str(self.delta_variable.currentData())
        scale = 100.0 if column == "DeltaEfficiency" else 1.0
        label = "效率差 [百分点]" if column == "DeltaEfficiency" else "转矩差 [N·m]"
        speeds = np.sort(frame["Speed_rpm"].unique().astype(float))
        torques = np.sort(frame["TorqueRequest_Nm"].unique().astype(float))
        matrix = np.full((speeds.size, torques.size), np.nan)
        speed_lookup = {value: index for index, value in enumerate(speeds)}
        torque_lookup = {value: index for index, value in enumerate(torques)}
        for row in frame.itertuples(index=False):
            matrix[speed_lookup[float(row.Speed_rpm)], torque_lookup[float(row.TorqueRequest_Nm)]] = float(getattr(row, column)) * scale
        self.difference_map.set_nodes(speeds, torques, matrix, label)
