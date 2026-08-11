"""Interactive torque-speed envelope plot."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pyqtgraph as pg
import pyqtgraph.exporters
from PySide6.QtCore import QPoint, QPointF, Qt, Signal
from PySide6.QtWidgets import QToolTip

from models.operating_map import OperatingMapResult
from services.case_repository import SavedCase
from ui.map_index_utils import clicked_flat_index
from ui.plot_theme import (
    EXTERNAL_COLOR,
    FIELD_WEAKENING_COLOR,
    GRID_ALPHA,
    MTPA_COLOR,
    MTPV_COLOR,
    SELECTED_COLOR,
    add_zero_axes,
)


class TorqueSpeedPlot(pg.PlotWidget):
    pointSelected = Signal(int)
    internalPointSelected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent, background="w")
        self.setMinimumHeight(280)
        self.setLabel("bottom", "机械转速", units="rpm")
        self.setLabel("left", "电磁转矩", units="N·m")
        self.plotItem.getAxis("bottom").enableAutoSIPrefix(False)
        self.plotItem.getAxis("left").enableAutoSIPrefix(False)
        self.setTitle("转矩—转速包络")
        self.showGrid(x=True, y=True, alpha=GRID_ALPHA)
        self._legend = self.addLegend(offset=(10, 10))
        self._legend.anchor((0, 0), (0, 0), offset=(10, 10))
        self._legend.setBrush(pg.mkBrush(255, 255, 255, 220))
        self._legend.setPen(pg.mkPen("#D1D5DB", width=1))
        self.plotItem.getAxis("bottom").setTextPen("#344054")
        self.plotItem.getAxis("left").setTextPen("#344054")
        self._zero_x, self._zero_y = add_zero_axes(self)

        self._envelope = self.plot(
            [],
            [],
            pen=pg.mkPen(EXTERNAL_COLOR, width=2.6),
            symbol="o",
            symbolSize=4,
            symbolBrush=EXTERNAL_COLOR,
            symbolPen=None,
            connect="finite",
            name="最大转矩包络",
        )
        self._region_points: dict[str, pg.ScatterPlotItem] = {}
        region_styles = {
            "MTPA": ("MTPA工作点", MTPA_COLOR, "o"),
            "FIELD_WEAKENING": (
                "普通弱磁工作点",
                FIELD_WEAKENING_COLOR,
                "s",
            ),
            "MTPV": ("MTPV工作点", MTPV_COLOR, "d"),
        }
        for region, (label, color, symbol) in region_styles.items():
            item = pg.ScatterPlotItem(
                pxMode=True,
                pen=None,
                brush=pg.mkBrush(color),
                symbol=symbol,
                size=4.5,
                hoverable=True,
            )
            self._region_points[region] = item
            self.addItem(item)
            self._legend.addItem(item, label)
            item.sigClicked.connect(
                self._on_operating_region_point_clicked
            )
        self._selected = self.plot(
            [],
            [],
            pen=None,
            symbol="o",
            symbolSize=15,
            symbolBrush=SELECTED_COLOR,
            symbolPen=pg.mkPen("#000000", width=2.2),
            name="当前工作点",
        )
        self._dataframe = pd.DataFrame()
        self._operating_map: OperatingMapResult | None = None
        self._internal_flat_indices = np.array([], dtype=int)
        self._valid_indices = np.array([], dtype=int)
        self._comparison_items: list[pg.GraphicsObject] = []
        self.scene().sigMouseClicked.connect(self._on_scene_clicked)
        self._hover_proxy = pg.SignalProxy(
            self.scene().sigMouseMoved,
            rateLimit=30,
            slot=self._on_mouse_moved,
        )

    def set_dataframe(self, dataframe: pd.DataFrame) -> None:
        self._dataframe = dataframe.reset_index(drop=True)
        if dataframe.empty:
            self._envelope.setData([], [])
            self._selected.setData([], [])
            self._valid_indices = np.array([], dtype=int)
            return
        speed = self._dataframe["Speed_rpm"].to_numpy(dtype=float)
        torque = self._dataframe["Torque_Nm"].to_numpy(dtype=float)
        self._valid_indices = np.flatnonzero(np.isfinite(speed) & np.isfinite(torque))
        self._envelope.setData(speed, torque, connect="finite")
        self._selected.setData([], [])
        if self._valid_indices.size:
            max_speed = float(np.nanmax(speed))
            max_torque = float(np.nanmax(torque))
            self.setXRange(
                -0.015 * max(max_speed, 1.0),
                max(max_speed, 1.0),
                padding=0.01,
            )
            self.setYRange(
                -0.025 * max(max_torque, 1.0),
                max(max_torque * 1.32, 1.0),
                padding=0.01,
            )

    def set_operating_map(self, result: OperatingMapResult) -> None:
        self._operating_map = result
        frame = result.dataframe
        speed = frame["Speed_rpm"].to_numpy(dtype=float)
        torque = frame["TorqueActual_Nm"].to_numpy(dtype=float)
        feasible = frame["IsFeasible"].to_numpy(dtype=bool)
        visible = feasible & np.isfinite(speed) & np.isfinite(torque)
        self._internal_flat_indices = np.flatnonzero(visible)
        regions = frame["ControlRegion"].astype(str).to_numpy()
        display_regions = np.where(
            np.isin(regions, ["MTPA", "MTPV"]),
            regions,
            "FIELD_WEAKENING",
        )
        for region, item in self._region_points.items():
            mask = visible & (display_regions == region)
            indices = np.flatnonzero(mask)
            item.setData(
                x=speed[mask],
                y=torque[mask],
                data=[int(index) for index in indices],
                pxMode=True,
                size=4.5,
                hoverable=True,
            )

    @property
    def internal_point_count(self) -> int:
        return int(len(self._internal_flat_indices))

    def set_comparison_cases(self, cases: list[SavedCase]) -> None:
        for item in self._comparison_items:
            self.removeItem(item)
        self._comparison_items.clear()
        colors = ["#0EA5E9", "#A855F7", "#14B8A6", "#E11D48", "#64748B"]
        for index, case in enumerate(cases):
            color = colors[index % len(colors)]
            external = case.external
            curve = self.plot(
                external["Speed_rpm"].to_numpy(dtype=float),
                external["Torque_Nm"].to_numpy(dtype=float),
                pen=pg.mkPen(
                    color, width=2.0, style=Qt.PenStyle.DashLine
                ),
                connect="finite",
                name=case.legend_label,
            )
            points = case.operating_points
            feasible = points["IsFeasible"].astype(bool).to_numpy()
            stride = max(1, int(np.count_nonzero(feasible) / 1500))
            visible = np.flatnonzero(feasible)[::stride]
            brush_color = pg.mkColor(color)
            brush_color.setAlpha(70)
            scatter = pg.ScatterPlotItem(
                x=points.iloc[visible]["Speed_rpm"].to_numpy(dtype=float),
                y=points.iloc[visible]["TorqueActual_Nm"].to_numpy(dtype=float),
                size=3,
                pen=None,
                brush=pg.mkBrush(brush_color),
            )
            self.addItem(scatter)
            self._comparison_items.extend((curve, scatter))

    @property
    def operating_region_items(self) -> dict[str, pg.ScatterPlotItem]:
        return dict(self._region_points)

    def region_point_count(self, region: str) -> int:
        x_values, _ = self._region_points[region].getData()
        return int(len(x_values))

    def set_selected_index(self, index: int) -> None:
        if not 0 <= index < len(self._dataframe):
            self._selected.setData([], [])
            return
        row = self._dataframe.iloc[index]
        speed = float(row["Speed_rpm"])
        torque = float(row["Torque_Nm"])
        if math.isfinite(speed) and math.isfinite(torque):
            self._selected.setData([speed], [torque])
        else:
            self._selected.setData([], [])

    def set_selected_coordinates(self, speed_rpm: float, torque_nm: float) -> None:
        if math.isfinite(speed_rpm) and math.isfinite(torque_nm):
            self._selected.setData([speed_rpm], [torque_nm])
        else:
            self._selected.setData([], [])

    def set_selected_map_index(self, map_index: int) -> None:
        if self._operating_map is None:
            self._selected.setData([], [])
            return
        row = self._operating_map.point_by_map_index(map_index)
        self.set_selected_coordinates(
            float(row["Speed_rpm"]), float(row["TorqueActual_Nm"])
        )

    def export_png(self, path: str) -> None:
        exporter = pyqtgraph.exporters.ImageExporter(self.plotItem)
        exporter.parameters()["width"] = 1600
        exporter.export(path)

    def _nearest_index(self, scene_position: QPointF, threshold_px: float) -> int | None:
        if self._valid_indices.size == 0:
            return None
        distances = []
        for index in self._valid_indices:
            row = self._dataframe.iloc[int(index)]
            scene_point = self.plotItem.vb.mapViewToScene(
                QPointF(float(row["Speed_rpm"]), float(row["Torque_Nm"]))
            )
            distances.append(
                (scene_point.x() - scene_position.x()) ** 2
                + (scene_point.y() - scene_position.y()) ** 2
            )
        distance_array = np.asarray(distances, dtype=float)
        if distance_array.size == 0:
            return None
        nearest_position = int(np.argmin(distance_array))
        nearest_distance = float(distance_array[nearest_position])
        if nearest_distance > threshold_px**2:
            return None
        return int(self._valid_indices[nearest_position])

    def _nearest_internal_map_index(
        self, scene_position: QPointF, threshold_px: float
    ) -> int | None:
        if (
            self._operating_map is None
            or self._internal_flat_indices.size == 0
        ):
            return None
        frame = self._operating_map.dataframe
        distances = []
        candidate_indices = []
        for map_index in self._internal_flat_indices:
            row = frame.iloc[int(map_index)]
            scene_point = self.plotItem.vb.mapViewToScene(
                QPointF(
                    float(row["Speed_rpm"]),
                    float(row["TorqueActual_Nm"]),
                )
            )
            candidate_indices.append(int(map_index))
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

    def _on_operating_region_point_clicked(
        self, _item, points, event
    ) -> None:
        map_index = clicked_flat_index(points)
        if map_index is None:
            return
        self.internalPointSelected.emit(map_index)
        event.accept()

    def _on_internal_points_clicked(
        self, item, points, event
    ) -> None:
        """Backward-compatible callback alias."""

        self._on_operating_region_point_clicked(item, points, event)

    def _on_scene_clicked(self, event) -> None:
        if not self.plotItem.sceneBoundingRect().contains(event.scenePos()):
            return
        if event.isAccepted():
            return
        map_index = self._nearest_internal_map_index(event.scenePos(), 12.0)
        if map_index is not None:
            self.internalPointSelected.emit(map_index)
            event.accept()
            return
        index = self._nearest_index(event.scenePos(), 12.0)
        if index is not None:
            self.pointSelected.emit(index)
            event.accept()

    def _on_mouse_moved(self, event) -> None:
        scene_position = event[0]
        if not self.plotItem.sceneBoundingRect().contains(scene_position):
            return
        index = self._nearest_index(scene_position, 10.0)
        if index is None:
            return
        row = self._dataframe.iloc[index]
        local_point = self.mapFromScene(scene_position)
        QToolTip.showText(
            self.mapToGlobal(QPoint(int(local_point.x()), int(local_point.y()))),
            (
                f"{row['Speed_rpm']:.1f} rpm\n"
                f"{row['Torque_Nm']:.3f} N·m\n"
                f"{row['Region']} / {row['ActiveConstraint']}"
            ),
            self,
        )
