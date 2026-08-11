"""Interactive color operating map in the mechanical torque-speed plane."""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters
from PySide6.QtCore import QPoint, QPointF, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from models.operating_map import OperatingMapResult
from ui.map_index_utils import clicked_flat_index
from ui.plot_theme import (
    EXTERNAL_COLOR,
    GRID_ALPHA,
    SELECTED_COLOR,
    add_zero_axes,
    performance_colormap,
)


MAP_VARIABLES = {
    "Efficiency": ("效率", "%", 100.0),
    "TotalMotorLoss_kW": ("总电机损耗", "kW", 1.0),
    "CopperLoss_kW": ("铜耗", "kW", 1.0),
    "IronLoss_kW": ("铁耗估算", "kW", 1.0),
    "Id_A": ("Id", "A", 1.0),
    "Iq_A": ("Iq", "A", 1.0),
    "Is_A": ("电流幅值", "A", 1.0),
    "VoltageUtilization": ("电压利用率", "%", 100.0),
    "CurrentUtilization": ("电流利用率", "%", 100.0),
}


class OperatingMapPlot(QWidget):
    pointSelected = Signal(int)
    displayChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.variable_combo = QComboBox()
        for key, (label, unit, _scale) in MAP_VARIABLES.items():
            suffix = f" ({unit})" if unit else ""
            self.variable_combo.addItem(label + suffix, key)
        self.variable_combo.hide()
        self.show_contours = QCheckBox("显示等值线")
        self.show_contours.setChecked(False)
        self.show_contours.hide()
        # Compatibility alias for integrations that previously toggled the
        # discrete point layer.  It now controls contour lines.
        self.show_grid_points = self.show_contours
        self.profile_label = QLabel("尚未计算")
        self.profile_label.setProperty("role", "muted")
        self.display_button = QToolButton()
        self.display_button.setText("显示选项")
        self.display_button.setProperty("role", "displayMenu")
        self.display_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        display_menu = QMenu(self.display_button)
        self.display_button.setMenu(display_menu)
        variable_menu = display_menu.addMenu("色彩图变量")
        self.variable_actions = QActionGroup(self)
        self.variable_actions.setExclusive(True)
        for index in range(self.variable_combo.count()):
            action = variable_menu.addAction(
                self.variable_combo.itemText(index)
            )
            action.setCheckable(True)
            action.setData(index)
            action.setChecked(index == 0)
            self.variable_actions.addAction(action)
            action.triggered.connect(
                lambda _checked=False, selected=index: (
                    self.variable_combo.setCurrentIndex(selected)
                )
            )
        self.contour_action = display_menu.addAction("显示等值线")
        self.contour_action.setCheckable(True)
        self.contour_action.setChecked(False)
        self.contour_action.toggled.connect(self.show_contours.setChecked)
        controls.addWidget(self.display_button)
        controls.addStretch(1)
        controls.addWidget(self.profile_label)
        layout.addLayout(controls)

        self.plot_widget = pg.PlotWidget(background="w")
        self.plot_widget.setLabel("bottom", "机械转速", units="rpm")
        self.plot_widget.setLabel("left", "电磁转矩", units="N·m")
        self.plot_widget.plotItem.getAxis("bottom").enableAutoSIPrefix(False)
        self.plot_widget.plotItem.getAxis("left").enableAutoSIPrefix(False)
        self.plot_widget.setTitle("电机效率估算Map（铜耗+铁耗）")
        self.plot_widget.showGrid(x=True, y=True, alpha=GRID_ALPHA)
        layout.addWidget(self.plot_widget, 1)

        self._cmap = performance_colormap()
        self._mesh = pg.PColorMeshItem(
            colorMap=self._cmap,
            edgecolors=None,
            antialiasing=False,
        )
        self.plot_widget.addItem(self._mesh)
        self._envelope = self.plot_widget.plot(
            [],
            [],
            pen=pg.mkPen(EXTERNAL_COLOR, width=2.6),
            name="最大转矩包络",
        )
        # Transparent hit targets retain one Python flat index per point while
        # the visible field is rendered by the continuous filled mesh.
        self._points = pg.ScatterPlotItem(
            pxMode=True,
            pen=None,
            brush=pg.mkBrush(0, 0, 0, 0),
            symbol="s",
            size=8,
            hoverable=False,
        )
        self.plot_widget.addItem(self._points)
        self._selected = self.plot_widget.plot(
            [],
            [],
            pen=None,
            symbol="o",
            symbolSize=15,
            symbolBrush=SELECTED_COLOR,
            symbolPen=pg.mkPen("#000000", width=2.2),
        )
        self._zero_x, self._zero_y = add_zero_axes(self.plot_widget)
        self._result: OperatingMapResult | None = None
        self._stale = False
        self._visible_flat_indices = np.array([], dtype=int)
        self._contour_items = [
            self.plot_widget.plot(
                [],
                [],
                pen=pg.mkPen(255, 255, 255, 145, width=0.9),
                connect="finite",
            )
            for _ in range(7)
        ]
        self._color_bar = pg.ColorBarItem(
            values=(0.0, 1.0),
            colorMap=self._cmap,
            label="",
            interactive=False,
        )
        self.plot_widget.plotItem.layout.addItem(self._color_bar, 2, 2)

        self.variable_combo.currentIndexChanged.connect(self._update_colors)
        self.variable_combo.currentIndexChanged.connect(self.displayChanged)
        self.show_contours.toggled.connect(self._update_colors)
        self.show_contours.toggled.connect(self.displayChanged)
        self._points.sigClicked.connect(self._on_points_clicked)
        self.plot_widget.scene().sigMouseClicked.connect(self._on_clicked)
        self._hover_proxy = pg.SignalProxy(
            self.plot_widget.scene().sigMouseMoved,
            rateLimit=25,
            slot=self._on_mouse_moved,
        )

    @property
    def selected_variable(self) -> str:
        return str(self.variable_combo.currentData())

    def set_result(self, result: OperatingMapResult) -> None:
        self._result = result
        self._stale = False
        self._update_profile_label()
        self._envelope.setData(
            result.speed_grid_rpm,
            result.maximum_torque_nm,
            connect="finite",
        )
        self._selected.setData([], [])
        self._update_colors()
        self.plot_widget.setXRange(
            -0.015 * max(float(np.nanmax(result.speed_grid_rpm)), 1.0),
            max(float(np.nanmax(result.speed_grid_rpm)), 1.0),
            padding=0.01,
        )
        self.plot_widget.setYRange(
            -0.025 * max(float(np.nanmax(result.maximum_torque_nm)), 1.0),
            max(float(np.nanmax(result.maximum_torque_nm)) * 1.08, 1.0),
            padding=0.01,
        )

    def _update_colors(self, *_args) -> None:
        if self._result is None:
            self._mesh.setData()
            self._points.setData([], [])
            self._visible_flat_indices = np.array([], dtype=int)
            self._clear_contours()
            return
        result = self._result
        column = self.selected_variable
        label, unit, scale = MAP_VARIABLES[column]
        node_values = result.matrix(column).astype(float) * scale
        speed_matrix = result.matrix("Speed_rpm").astype(float)
        torque_matrix = result.matrix("TorqueActual_Nm").astype(float)
        feasible_matrix = result.matrix("IsFeasible").astype(bool)
        speed = speed_matrix.ravel()
        torque = torque_matrix.ravel()
        visible = (
            feasible_matrix.ravel()
            & np.isfinite(speed)
            & np.isfinite(torque)
        )
        self._visible_flat_indices = np.flatnonzero(visible)
        if not np.any(visible):
            self._mesh.setData()
            self._points.setData([], [])
            self._clear_contours()
            return
        self._points.setData(
            x=speed[visible],
            y=torque[visible],
            data=[int(index) for index in self._visible_flat_indices],
            brush=pg.mkBrush(0, 0, 0, 0),
            pen=None,
            size=8,
            symbol="s",
        )

        finite_nodes = (
            feasible_matrix
            & np.isfinite(speed_matrix)
            & np.isfinite(torque_matrix)
            & np.isfinite(node_values)
        )
        visible_values = node_values[finite_nodes]
        if visible_values.size == 0 or min(result.shape) < 2:
            self._mesh.setData()
            self._clear_contours()
            self._color_bar.axis.setLabel(
                f"{label} ({unit})" if unit else label
            )
            return
        low = float(np.nanmin(visible_values))
        high = float(np.nanmax(visible_values))
        if math.isclose(low, high):
            high = low + max(abs(low) * 1e-6, 1e-9)

        # Each colored polygon is bounded by four solved nodes.  Requiring all
        # four to be valid leaves the external-envelope region as true NaN
        # whitespace instead of extrapolating colors beyond the calculation.
        cell_valid = (
            finite_nodes[:-1, :-1]
            & finite_nodes[1:, :-1]
            & finite_nodes[:-1, 1:]
            & finite_nodes[1:, 1:]
        )
        cell_values = 0.25 * (
            node_values[:-1, :-1]
            + node_values[1:, :-1]
            + node_values[:-1, 1:]
            + node_values[1:, 1:]
        )
        cell_values = np.where(cell_valid, cell_values, np.nan)
        x_nodes, y_nodes = np.meshgrid(
            result.speed_grid_rpm,
            result.torque_axis_nm,
            indexing="ij",
        )
        self._mesh.setLevels((low, high))
        self._mesh.setData(
            x_nodes,
            y_nodes,
            cell_values,
            autoLevels=False,
        )
        self._color_bar.setLevels((low, high))
        self._color_bar.axis.setLabel(
            f"{label} ({unit})" if unit else label
        )
        self.plot_widget.setTitle(f"{label} Map")
        self._update_contours(
            result.speed_grid_rpm,
            result.torque_axis_nm,
            node_values,
            finite_nodes,
            low,
            high,
        )

    def _clear_contours(self) -> None:
        for item in self._contour_items:
            item.setData([], [])

    def _update_contours(
        self,
        speeds: np.ndarray,
        torques: np.ndarray,
        values: np.ndarray,
        valid: np.ndarray,
        low: float,
        high: float,
    ) -> None:
        if not self.show_contours.isChecked() or math.isclose(low, high):
            self._clear_contours()
            return
        levels = np.linspace(low, high, len(self._contour_items) + 2)[1:-1]
        for item, level in zip(self._contour_items, levels):
            x_values, y_values = self._contour_segments(
                speeds, torques, values, valid, float(level)
            )
            item.setData(x_values, y_values, connect="finite")

    @staticmethod
    def _contour_segments(
        speeds: np.ndarray,
        torques: np.ndarray,
        values: np.ndarray,
        valid: np.ndarray,
        level: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return finite-separated marching-square line segments."""

        xs: list[float] = []
        ys: list[float] = []
        rows, columns = values.shape
        for speed_index in range(rows - 1):
            for torque_index in range(columns - 1):
                if not (
                    valid[speed_index, torque_index]
                    and valid[speed_index + 1, torque_index]
                    and valid[speed_index + 1, torque_index + 1]
                    and valid[speed_index, torque_index + 1]
                ):
                    continue
                corners = (
                    (
                        float(speeds[speed_index]),
                        float(torques[torque_index]),
                        float(values[speed_index, torque_index]),
                    ),
                    (
                        float(speeds[speed_index + 1]),
                        float(torques[torque_index]),
                        float(values[speed_index + 1, torque_index]),
                    ),
                    (
                        float(speeds[speed_index + 1]),
                        float(torques[torque_index + 1]),
                        float(values[speed_index + 1, torque_index + 1]),
                    ),
                    (
                        float(speeds[speed_index]),
                        float(torques[torque_index + 1]),
                        float(values[speed_index, torque_index + 1]),
                    ),
                )
                intersections: list[tuple[float, float]] = []
                for start, end in zip(
                    corners, (corners[1], corners[2], corners[3], corners[0])
                ):
                    start_value = start[2] - level
                    end_value = end[2] - level
                    if start_value == 0.0 and end_value == 0.0:
                        continue
                    if start_value * end_value > 0.0:
                        continue
                    denominator = end[2] - start[2]
                    fraction = (
                        0.5
                        if math.isclose(denominator, 0.0)
                        else (level - start[2]) / denominator
                    )
                    fraction = float(np.clip(fraction, 0.0, 1.0))
                    intersections.append(
                        (
                            start[0] + fraction * (end[0] - start[0]),
                            start[1] + fraction * (end[1] - start[1]),
                        )
                    )
                for offset in range(0, len(intersections) - 1, 2):
                    first = intersections[offset]
                    second = intersections[offset + 1]
                    xs.extend((first[0], second[0], np.nan))
                    ys.extend((first[1], second[1], np.nan))
        return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)

    def set_selected_point(self, speed_index: int, torque_index: int) -> None:
        if self._result is None:
            self._selected.setData([], [])
            return
        record = self._result.point(speed_index, torque_index)
        if not bool(record["IsFeasible"]):
            self._selected.setData([], [])
            return
        self._selected.setData(
            [float(record["Speed_rpm"])],
            [float(record["TorqueActual_Nm"])],
        )

    def set_selected_map_index(self, map_index: int) -> None:
        if self._result is None:
            self._selected.setData([], [])
            return
        speed_index, torque_index = self._result.unravel_index(map_index)
        self.set_selected_point(speed_index, torque_index)

    def set_stale(self, stale: bool) -> None:
        self._stale = bool(stale)
        self._update_profile_label()

    def _update_profile_label(self) -> None:
        if self._result is None:
            self.profile_label.setText("尚未计算")
            return
        suffix = " · 结果已过期" if self._stale else ""
        self.profile_label.setText(
            f"{'预览' if self._result.is_preview else '全量'} "
            f"{self._result.shape[0]}×{self._result.shape[1]}{suffix}"
        )

    def export_png(self, path: str) -> None:
        exporter = pyqtgraph.exporters.ImageExporter(self.plot_widget.plotItem)
        exporter.parameters()["width"] = 1800
        exporter.export(path)

    def _nearest_flat_index(
        self, scene_position: QPointF, threshold_px: float
    ) -> int | None:
        if self._result is None or self._visible_flat_indices.size == 0:
            return None
        frame = self._result.dataframe
        distances = []
        candidate_indices = []
        for flat_index in self._visible_flat_indices:
            row = frame.iloc[int(flat_index)]
            scene_point = self.plot_widget.plotItem.vb.mapViewToScene(
                QPointF(
                    float(row["Speed_rpm"]),
                    float(row["TorqueActual_Nm"]),
                )
            )
            candidate_indices.append(int(flat_index))
            distances.append(
                (scene_point.x() - scene_position.x()) ** 2
                + (scene_point.y() - scene_position.y()) ** 2
            )
        distance_array = np.asarray(distances, dtype=float)
        if distance_array.size == 0:
            return None
        nearest_index = int(np.argmin(distance_array))
        nearest_distance = float(distance_array[nearest_index])
        if nearest_distance > threshold_px**2:
            return None
        return int(candidate_indices[nearest_index])

    def _on_clicked(self, event) -> None:
        if not self.plot_widget.plotItem.sceneBoundingRect().contains(
            event.scenePos()
        ):
            return
        if event.isAccepted():
            return
        flat_index = self._nearest_flat_index(event.scenePos(), 14.0)
        if flat_index is None or self._result is None:
            return
        self.pointSelected.emit(flat_index)
        event.accept()

    def _on_points_clicked(self, _item, points, event) -> None:
        flat_index = clicked_flat_index(points)
        if flat_index is None:
            return
        self.pointSelected.emit(flat_index)
        event.accept()

    def _on_mouse_moved(self, event) -> None:
        if self._result is None:
            return
        scene_position = event[0]
        if not self.plot_widget.plotItem.sceneBoundingRect().contains(
            scene_position
        ):
            return
        flat_index = self._nearest_flat_index(scene_position, 10.0)
        if flat_index is None:
            return
        row = self._result.dataframe.iloc[flat_index]
        local = self.plot_widget.mapFromScene(scene_position)
        efficiency = row.get("Efficiency", np.nan)
        efficiency_text = (
            f"{float(efficiency) * 100.0:.2f}%"
            if np.isfinite(float(efficiency))
            else "—"
        )
        QToolTip.showText(
            self.plot_widget.mapToGlobal(
                QPoint(int(local.x()), int(local.y()))
            ),
            (
                f"{row['Speed_rpm']:.1f} rpm\n"
                f"{row['TorqueActual_Nm']:.3f} N·m\n"
                f"效率 {efficiency_text}\n"
                f"{row['ControlRegion']} / {row['ActiveConstraint']}"
            ),
            self.plot_widget,
        )
