"""Interactive dq plot with independent MTPA, MTPV, and operating tracks."""

from __future__ import annotations

import math
import logging
from time import perf_counter

import numpy as np
import pandas as pd
import pyqtgraph as pg
import pyqtgraph.exporters
from PySide6.QtCore import QPointF, Qt, Signal

from calculation.constraint_curves import (
    constant_torque_curve,
    voltage_limit_curve,
)
from calculation.dq_reference_data import build_local_mtpv_trajectory_from_map
from calculation.reference_trajectories import (
    generate_local_mtpv_trajectory,
    generate_mtpa_trajectory,
    generate_mtpv_envelope,
)
from models.motor_parameters import MotorParameters
from models.operating_map import OperatingMapResult
from models.resolved_characteristic_limits import ResolvedCharacteristicLimits
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


LOGGER = logging.getLogger(__name__)


def _custom_dash_pen(color: str, width: float, pattern: list[float]):
    pen = pg.mkPen(color, width=width)
    pen.setStyle(Qt.PenStyle.CustomDashLine)
    pen.setDashPattern(pattern)
    return pen


class DqPlot(pg.PlotWidget):
    DISPLAY_ALL = "all"
    DISPLAY_CURRENT_SPEED = "current_speed"
    DISPLAY_CURRENT_TORQUE = "current_torque"
    DISPLAY_ALL_WITH_SPEED = "all_with_speed"
    pointSelected = Signal(int)
    internalPointSelected = Signal(int)
    referencePointSelected = Signal(str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent, background="w")
        self.setMinimumHeight(280)
        self.plotItem.getViewBox().setAspectLocked(True, ratio=1)
        self.setLabel("bottom", "d轴电流 Id", units="A")
        self.setLabel("left", "q轴电流 Iq", units="A")
        self.plotItem.getAxis("bottom").enableAutoSIPrefix(False)
        self.plotItem.getAxis("left").enableAutoSIPrefix(False)
        self.setTitle("dq 电流平面")
        self.showGrid(x=True, y=True, alpha=GRID_ALPHA)
        self._legend = self.addLegend(offset=(-10, 10))
        self._legend.anchor((1, 0), (1, 0), offset=(-10, 10))
        self._legend.setBrush(pg.mkBrush(255, 255, 255, 220))
        self._legend.setPen(pg.mkPen("#D1D5DB", width=1))
        self.plotItem.getAxis("bottom").setTextPen("#344054")
        self.plotItem.getAxis("left").setTextPen("#344054")
        self._zero_x, self._zero_y = add_zero_axes(self)

        self._current_circle = self.plot(
            [],
            [],
            pen=_custom_dash_pen("#98a2b3", 1.7, [9.0, 4.0]),
            name="Current Limit",
        )
        self._mtpa = self.plot(
            [],
            [],
            pen=pg.mkPen(
                MTPA_COLOR, width=2.2, style=Qt.PenStyle.DashLine
            ),
            name="MTPA",
        )
        self._mtpv = self.plot(
            [],
            [],
            pen=pg.mkPen(
                MTPV_COLOR, width=2.2, style=Qt.PenStyle.DashLine
            ),
            name="MTPV",
        )
        self._local_mtpv = self.plot(
            [],
            [],
            pen=_custom_dash_pen(
                MTPV_COLOR, 1.8, [2.0, 2.0, 8.0, 2.0]
            ),
            connect="finite",
            name="MTPV (Selected Speed)",
        )
        self._trajectory = self.plot(
            [],
            [],
            pen=None,
            symbol="o",
            symbolSize=4,
            symbolBrush=EXTERNAL_COLOR,
            symbolPen=pg.mkPen(EXTERNAL_COLOR, width=0.8),
            connect="finite",
            name="Optimal Operating Trajectory",
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
                size=4.0,
                hoverable=True,
            )
            self._region_points[region] = item
            self.addItem(item)
            self._legend.addItem(item, label)
            item.sigClicked.connect(
                self._on_operating_region_point_clicked
            )
        self._current_speed_trace = self.plot(
            [],
            [],
            pen=pg.mkPen("#101828", width=2.2),
            symbol="o",
            symbolSize=6,
            symbolBrush=pg.mkBrush(255, 255, 255, 170),
            symbolPen=pg.mkPen("#101828", width=1),
            connect="finite",
            name="当前转速轨迹",
        )
        self._current_torque_trace = self.plot(
            [],
            [],
            pen=pg.mkPen("#667085", width=2.0),
            symbol="o",
            symbolSize=6,
            symbolBrush=pg.mkBrush(255, 255, 255, 170),
            symbolPen=pg.mkPen("#667085", width=1),
            connect="finite",
            name="当前转矩轨迹",
        )
        self._voltage_limit = self.plot(
            [],
            [],
            pen=_custom_dash_pen(
                "#f79009", 2.2, [12.0, 3.0, 2.0, 3.0, 2.0, 3.0]
            ),
            name="Voltage Limit",
        )
        self._constant_torque = self.plot(
            [],
            [],
            pen=_custom_dash_pen("#12b76a", 2.0, [4.0, 2.0]),
            connect="finite",
            name="Constant Torque",
        )
        self._selected = self.plot(
            [],
            [],
            pen=None,
            symbol="o",
            symbolSize=15,
            symbolBrush=SELECTED_COLOR,
            symbolPen=pg.mkPen("#000000", width=2.2),
            name="Selected Point",
        )
        self._reference_selected = self.plot(
            [],
            [],
            pen=None,
            symbol="d",
            symbolSize=13,
            symbolBrush=SELECTED_COLOR,
            symbolPen=pg.mkPen("#000000", width=2),
        )

        self._curve_items = {
            "current_limit": [self._current_circle],
            "mtpa": [self._mtpa],
            "mtpv": [self._mtpv],
            "local_mtpv": [self._local_mtpv],
            "optimal": [self._trajectory],
            "voltage_limit": [self._voltage_limit],
            "constant_torque": [self._constant_torque],
        }
        self._parameters: MotorParameters | None = None
        self._limits: ResolvedCharacteristicLimits | None = None
        self._operating_map: OperatingMapResult | None = None
        self._internal_valid_indices = np.array([], dtype=int)
        self._displayed_internal_indices = np.array([], dtype=int)
        self._selected_map_index: int | None = None
        self._internal_display_mode = self.DISPLAY_ALL_WITH_SPEED
        self._internal_points_visible = True
        self._current_speed_highlight_visible = True
        self._dataframe = pd.DataFrame()
        self._mtpa_dataframe = pd.DataFrame()
        self._mtpv_dataframe = pd.DataFrame()
        self._local_mtpv_dataframe = pd.DataFrame()
        self._local_mtpv_cache: dict[float, pd.DataFrame] = {}
        self._valid_indices = np.array([], dtype=int)
        self._max_reference_torque_nm = 0.0
        self._comparison_items: list[pg.GraphicsObject] = []
        self.scene().sigMouseClicked.connect(self._on_scene_clicked)

    @property
    def mtpa_dataframe(self) -> pd.DataFrame:
        return self._mtpa_dataframe.copy()

    @property
    def mtpv_dataframe(self) -> pd.DataFrame:
        return self._mtpv_dataframe.copy()

    @property
    def local_mtpv_dataframe(self) -> pd.DataFrame:
        return self._local_mtpv_dataframe.copy()

    def set_curve_visible(self, curve_key: str, visible: bool) -> None:
        for item in self._curve_items.get(curve_key, []):
            item.setVisible(visible)

    def set_results(
        self,
        parameters: MotorParameters,
        dataframe: pd.DataFrame,
        limits: ResolvedCharacteristicLimits | None = None,
        *,
        mtpa_dataframe: pd.DataFrame | None = None,
        mtpv_dataframe: pd.DataFrame | None = None,
    ) -> None:
        refresh_started = perf_counter()
        self._parameters = parameters
        self._limits = (
            limits
            or ResolvedCharacteristicLimits.from_legacy_motor(parameters)
        )
        self._dataframe = dataframe.reset_index(drop=True).copy()
        self._local_mtpv_cache.clear()

        theta = np.linspace(0.0, 2.0 * np.pi, 721)
        current_limit = self._limits.max_current_vector_a
        self._current_circle.setData(
            current_limit * np.cos(theta),
            current_limit * np.sin(theta),
        )

        mtpa_started = perf_counter()
        self._mtpa_dataframe = (
            generate_mtpa_trajectory(
                parameters, limits=self._limits, samples=181
            )
            if mtpa_dataframe is None
            else mtpa_dataframe.reset_index(drop=True).copy()
        )
        mtpa_elapsed = perf_counter() - mtpa_started
        LOGGER.log(
            logging.WARNING if mtpa_elapsed > 5.0 else logging.INFO,
            "dq 刷新 MTPA 理论轨迹耗时 %.3f s（samples=181）",
            mtpa_elapsed,
        )
        self._max_reference_torque_nm = float(
            self._mtpa_dataframe["Torque_Nm"].max()
        )
        self._mtpa.setData(
            self._mtpa_dataframe["Id_A"].to_numpy(copy=True),
            self._mtpa_dataframe["Iq_A"].to_numpy(copy=True),
            connect="finite",
        )

        mtpv_started = perf_counter()
        self._mtpv_dataframe = (
            generate_mtpv_envelope(
                parameters, self._dataframe, self._limits
            )
            if mtpv_dataframe is None
            else mtpv_dataframe.reset_index(drop=True).copy()
        )
        mtpv_elapsed = perf_counter() - mtpv_started
        LOGGER.log(
            logging.WARNING if mtpv_elapsed > 5.0 else logging.INFO,
            "dq 刷新 MTPV 包络耗时 %.3f s（points=%d）",
            mtpv_elapsed,
            len(self._mtpv_dataframe),
        )
        self._mtpv.setData(
            self._mtpv_dataframe.get("Id_A", pd.Series(dtype=float)).to_numpy(
                copy=True
            ),
            self._mtpv_dataframe.get("Iq_A", pd.Series(dtype=float)).to_numpy(
                copy=True
            ),
            connect="finite",
        )

        if dataframe.empty:
            self._trajectory.setData([], [])
            self._valid_indices = np.array([], dtype=int)
            return
        ids = self._dataframe["Id_A"].to_numpy(dtype=float, copy=True)
        iqs = self._dataframe["Iq_A"].to_numpy(dtype=float, copy=True)
        self._valid_indices = np.flatnonzero(np.isfinite(ids) & np.isfinite(iqs))
        self._trajectory.setData(ids, iqs, connect="finite")
        self._selected.setData([], [])
        self._reference_selected.setData([], [])
        self._voltage_limit.setData([], [])
        self._constant_torque.setData([], [])
        self._local_mtpv.setData([], [])
        span = max(current_limit, 1.0)
        self.setXRange(-1.15 * span, 1.15 * span, padding=0.0)
        self.setYRange(-0.15 * span, 1.15 * span, padding=0.0)
        LOGGER.info("dq set_results 总耗时 %.3f s", perf_counter() - refresh_started)

    def set_selected_index(self, index: int) -> None:
        self._reference_selected.setData([], [])
        if self._parameters is None or not 0 <= index < len(self._dataframe):
            self._selected.setData([], [])
            self._voltage_limit.setData([], [])
            self._constant_torque.setData([], [])
            self._local_mtpv.setData([], [])
            return
        row = self._dataframe.iloc[index]
        self._set_selected_values(
            float(row["Speed_rpm"]),
            float(row["Id_A"]),
            float(row["Iq_A"]),
            float(row["Torque_Nm"]),
        )

    def set_operating_map(
        self, result: OperatingMapResult, *, visible: bool = True
    ) -> None:
        self._operating_map = result
        ids = result.dataframe["Id_A"].to_numpy(dtype=float)
        iqs = result.dataframe["Iq_A"].to_numpy(dtype=float)
        feasible = result.dataframe["IsFeasible"].to_numpy(dtype=bool)
        self._internal_valid_indices = np.flatnonzero(
            feasible & np.isfinite(ids) & np.isfinite(iqs)
        )
        self._internal_points_visible = bool(visible)
        self._selected_map_index = None
        self._refresh_internal_display()

    def set_comparison_cases(self, cases: list[SavedCase]) -> None:
        for item in self._comparison_items:
            self.removeItem(item)
        self._comparison_items.clear()
        colors = ["#0EA5E9", "#A855F7", "#14B8A6", "#E11D48", "#64748B"]
        for index, case in enumerate(cases):
            color = colors[index % len(colors)]
            external = case.external
            curve = self.plot(
                external["Id_A"].to_numpy(dtype=float),
                external["Iq_A"].to_numpy(dtype=float),
                pen=pg.mkPen(color, width=2.0, style=Qt.PenStyle.DashLine),
                connect="finite",
                name=case.legend_label,
            )
            points = case.operating_points
            feasible = points["IsFeasible"].astype(bool).to_numpy()
            stride = max(1, int(np.count_nonzero(feasible) / 1500))
            visible = np.flatnonzero(feasible)[::stride]
            brush_color = pg.mkColor(color)
            brush_color.setAlpha(65)
            scatter = pg.ScatterPlotItem(
                x=points.iloc[visible]["Id_A"].to_numpy(dtype=float),
                y=points.iloc[visible]["Iq_A"].to_numpy(dtype=float),
                size=3,
                pen=None,
                brush=pg.mkBrush(brush_color),
            )
            self.addItem(scatter)
            self._comparison_items.extend((curve, scatter))

    @property
    def internal_point_count(self) -> int:
        return int(len(self._internal_valid_indices))

    @property
    def displayed_internal_point_count(self) -> int:
        return int(len(self._displayed_internal_indices))

    def set_internal_points_visible(self, visible: bool) -> None:
        self._internal_points_visible = bool(visible)
        self._refresh_internal_display()

    def set_current_speed_highlight_visible(self, visible: bool) -> None:
        self._current_speed_highlight_visible = bool(visible)
        self._refresh_internal_display()

    @property
    def operating_region_items(self) -> dict[str, pg.ScatterPlotItem]:
        return dict(self._region_points)

    @property
    def internal_display_mode(self) -> str:
        return self._internal_display_mode

    def set_internal_display_mode(self, mode: str) -> None:
        valid_modes = {
            self.DISPLAY_ALL,
            self.DISPLAY_CURRENT_SPEED,
            self.DISPLAY_CURRENT_TORQUE,
            self.DISPLAY_ALL_WITH_SPEED,
        }
        if mode not in valid_modes:
            raise ValueError(f"未知dq内部工作点显示模式：{mode}")
        self._internal_display_mode = mode
        self._refresh_internal_display()

    def region_point_count(self, region: str) -> int:
        x_values, _ = self._region_points[region].getData()
        return int(len(x_values))

    def _refresh_internal_display(self) -> None:
        if self._operating_map is None:
            self._displayed_internal_indices = np.array([], dtype=int)
            for item in self._region_points.values():
                item.setData([], [])
            self._current_speed_trace.setData([], [])
            self._current_torque_trace.setData([], [])
            return
        frame = self._operating_map.dataframe
        ids = frame["Id_A"].to_numpy(dtype=float)
        iqs = frame["Iq_A"].to_numpy(dtype=float)
        feasible = frame["IsFeasible"].to_numpy(dtype=bool)
        base_mask = feasible & np.isfinite(ids) & np.isfinite(iqs)
        if self._selected_map_index is None and self._internal_valid_indices.size:
            selected_index = int(self._internal_valid_indices[0])
        else:
            selected_index = self._selected_map_index
        selected_speed_index: int | None = None
        selected_torque_index: int | None = None
        if selected_index is not None and 0 <= selected_index < len(frame):
            selected_row = frame.iloc[selected_index]
            selected_speed_index = int(selected_row["SpeedIndex"])
            selected_torque_index = int(selected_row["TorqueIndex"])

        display_mask = base_mask.copy()
        if (
            self._internal_display_mode == self.DISPLAY_CURRENT_SPEED
            and selected_speed_index is not None
        ):
            display_mask &= (
                frame["SpeedIndex"].to_numpy(dtype=int)
                == selected_speed_index
            )
        elif (
            self._internal_display_mode == self.DISPLAY_CURRENT_TORQUE
            and selected_torque_index is not None
        ):
            display_mask &= (
                frame["TorqueIndex"].to_numpy(dtype=int)
                == selected_torque_index
            )
        self._displayed_internal_indices = np.flatnonzero(display_mask)

        regions = frame["ControlRegion"].astype(str).to_numpy()
        display_regions = np.where(
            np.isin(regions, ["MTPA", "MTPV"]),
            regions,
            "FIELD_WEAKENING",
        )
        for region, item in self._region_points.items():
            mask = display_mask & (display_regions == region)
            indices = np.flatnonzero(mask)
            item.setData(
                x=ids[mask],
                y=iqs[mask],
                data=[int(index) for index in indices],
                pxMode=True,
                size=4.0,
                hoverable=True,
            )
            item.setVisible(self._internal_points_visible)

        show_speed_trace = (
            self._internal_points_visible
            and self._current_speed_highlight_visible
            and selected_speed_index is not None
            and self._internal_display_mode
            in {self.DISPLAY_CURRENT_SPEED, self.DISPLAY_ALL_WITH_SPEED}
        )
        if show_speed_trace:
            speed_mask = base_mask & (
                frame["SpeedIndex"].to_numpy(dtype=int)
                == selected_speed_index
            )
            speed_indices = np.flatnonzero(speed_mask)
            order = np.argsort(
                frame.iloc[speed_indices]["TorqueActual_Nm"].to_numpy(
                    dtype=float
                )
            )
            speed_indices = speed_indices[order]
            self._current_speed_trace.setData(
                ids[speed_indices], iqs[speed_indices], connect="finite"
            )
        else:
            self._current_speed_trace.setData([], [])
        self._current_speed_trace.setVisible(show_speed_trace)

        show_torque_trace = (
            self._internal_points_visible
            and selected_torque_index is not None
            and self._internal_display_mode == self.DISPLAY_CURRENT_TORQUE
        )
        if show_torque_trace:
            torque_mask = base_mask & (
                frame["TorqueIndex"].to_numpy(dtype=int)
                == selected_torque_index
            )
            torque_indices = np.flatnonzero(torque_mask)
            order = np.argsort(
                frame.iloc[torque_indices]["Speed_rpm"].to_numpy(dtype=float)
            )
            torque_indices = torque_indices[order]
            self._current_torque_trace.setData(
                ids[torque_indices], iqs[torque_indices], connect="finite"
            )
        else:
            self._current_torque_trace.setData([], [])
        self._current_torque_trace.setVisible(show_torque_trace)

    def set_selected_map_point(
        self, speed_index: int, torque_index: int
    ) -> None:
        self._reference_selected.setData([], [])
        if self._operating_map is None:
            return
        row = self._operating_map.point(speed_index, torque_index)
        if not bool(row["IsFeasible"]):
            self._selected.setData([], [])
            return
        self._set_selected_values(
            float(row["Speed_rpm"]),
            float(row["Id_A"]),
            float(row["Iq_A"]),
            float(row["TorqueActual_Nm"]),
        )

    def set_selected_map_index(self, map_index: int) -> None:
        if self._operating_map is None:
            return
        self._selected_map_index = int(map_index)
        self._refresh_internal_display()
        speed_index, torque_index = self._operating_map.unravel_index(
            map_index
        )
        self.set_selected_map_point(speed_index, torque_index)

    def _set_selected_values(
        self, speed: float, id_a: float, iq_a: float, torque_nm: float
    ) -> None:
        if self._parameters is None or self._limits is None:
            return

        selected_started = perf_counter()
        voltage_started = perf_counter()
        voltage_id, voltage_iq = voltage_limit_curve(
            self._parameters,
            speed,
            samples=721,
            limits=self._limits,
        )
        self._voltage_limit.setData(voltage_id, voltage_iq)
        voltage_elapsed = perf_counter() - voltage_started

        if math.isfinite(torque_nm):
            id_values = np.linspace(
                -self._limits.max_current_vector_a,
                self._limits.max_current_vector_a,
                1001,
            )
            iq_values = constant_torque_curve(
                self._parameters,
                torque_nm,
                id_values,
                iq_plot_limit_a=1.5
                * self._limits.max_current_vector_a,
                limits=self._limits,
            )
            self._constant_torque.setData(id_values, iq_values, connect="finite")
        else:
            self._constant_torque.setData([], [])

        cache_key = round(speed, 9)
        if cache_key not in self._local_mtpv_cache:
            local_mtpv_started = perf_counter()
            if self._operating_map is not None:
                self._local_mtpv_cache[cache_key] = (
                    build_local_mtpv_trajectory_from_map(
                        self._parameters, self._operating_map, speed
                    )
                )
            else:
                self._local_mtpv_cache[cache_key] = generate_local_mtpv_trajectory(
                    self._parameters,
                    speed,
                    limits=self._limits,
                    samples=121,
                    max_torque_nm=self._max_reference_torque_nm,
                )
            local_mtpv_elapsed = perf_counter() - local_mtpv_started
            LOGGER.log(
                logging.WARNING if local_mtpv_elapsed > 5.0 else logging.INFO,
                "dq 当前转速 MTPV 耗时 %.3f s（speed=%.6g rpm, samples=121）",
                local_mtpv_elapsed,
                speed,
            )
        self._local_mtpv_dataframe = self._local_mtpv_cache[cache_key].copy()
        self._local_mtpv.setData(
            self._local_mtpv_dataframe["Id_A"].to_numpy(copy=True),
            self._local_mtpv_dataframe["Iq_A"].to_numpy(copy=True),
            connect="finite",
        )

        if math.isfinite(id_a) and math.isfinite(iq_a):
            self._selected.setData([id_a], [iq_a])
        else:
            self._selected.setData([], [])
        selected_elapsed = perf_counter() - selected_started
        LOGGER.log(
            logging.WARNING if selected_elapsed > 5.0 else logging.INFO,
            "dq 工作点联动耗时 %.3f s（speed=%.6g rpm, voltage_curve=%.3f s）",
            selected_elapsed,
            speed,
            voltage_elapsed,
        )

    def export_png(self, path: str) -> None:
        exporter = pyqtgraph.exporters.ImageExporter(self.plotItem)
        exporter.parameters()["width"] = 1600
        exporter.export(path)

    def _nearest_actual_index(
        self, scene_position: QPointF, threshold_px: float
    ) -> int | None:
        if self._valid_indices.size == 0 or not self._trajectory.isVisible():
            return None
        distances = []
        for index in self._valid_indices:
            row = self._dataframe.iloc[int(index)]
            scene_point = self.plotItem.vb.mapViewToScene(
                QPointF(float(row["Id_A"]), float(row["Iq_A"]))
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

    def _nearest_internal_index(
        self, scene_position: QPointF, threshold_px: float
    ) -> int | None:
        if (
            self._operating_map is None
            or self._displayed_internal_indices.size == 0
            or not self._internal_points_visible
        ):
            return None
        frame = self._operating_map.dataframe
        distances = []
        for flat_index in self._displayed_internal_indices:
            row = frame.iloc[int(flat_index)]
            scene_point = self.plotItem.vb.mapViewToScene(
                QPointF(float(row["Id_A"]), float(row["Iq_A"]))
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
        return int(self._displayed_internal_indices[nearest_position])

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

    def _nearest_reference(
        self, scene_position: QPointF, threshold_px: float
    ) -> tuple[str, dict] | None:
        candidates: list[tuple[float, str, dict]] = []
        references = [
            ("MTPA", self._mtpa_dataframe, self._mtpa.isVisible()),
            ("MTPV", self._mtpv_dataframe, self._mtpv.isVisible()),
            (
                "MTPV",
                self._local_mtpv_dataframe,
                self._local_mtpv.isVisible(),
            ),
        ]
        for kind, dataframe, visible in references:
            if not visible or dataframe.empty:
                continue
            for _, row in dataframe.iterrows():
                id_a = float(row["Id_A"])
                iq_a = float(row["Iq_A"])
                if not math.isfinite(id_a) or not math.isfinite(iq_a):
                    continue
                scene_point = self.plotItem.vb.mapViewToScene(QPointF(id_a, iq_a))
                distance = (
                    (scene_point.x() - scene_position.x()) ** 2
                    + (scene_point.y() - scene_position.y()) ** 2
                )
                candidates.append((distance, kind, row.to_dict()))
        if not candidates:
            return None
        distance, kind, record = min(candidates, key=lambda item: item[0])
        if distance > threshold_px**2:
            return None
        return kind, record

    def _on_scene_clicked(self, event) -> None:
        if not self.plotItem.sceneBoundingRect().contains(event.scenePos()):
            return
        if event.isAccepted():
            return
        internal_index = self._nearest_internal_index(event.scenePos(), 9.0)
        if internal_index is not None:
            self.internalPointSelected.emit(internal_index)
            event.accept()
            return
        index = self._nearest_actual_index(event.scenePos(), 10.0)
        if index is not None:
            self.pointSelected.emit(index)
            event.accept()
            return
        reference = self._nearest_reference(event.scenePos(), 12.0)
        if reference is not None:
            kind, record = reference
            self._reference_selected.setData(
                [float(record["Id_A"])], [float(record["Iq_A"])]
            )
            self.referencePointSelected.emit(kind, record)
            event.accept()
