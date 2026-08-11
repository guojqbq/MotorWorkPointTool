"""Compact Ld/Lq saturation-map preview dialog."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QDialog, QLabel, QTabWidget, QVBoxLayout, QWidget

from models.saturation_map import InductanceSaturationMap
from ui.plot_theme import performance_colormap


class SaturationMapPreviewDialog(QDialog):
    def __init__(
        self,
        ld_map: InductanceSaturationMap,
        lq_map: InductanceSaturationMap,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ld/Lq 饱和 Map 预览")
        self.resize(980, 620)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._map_widget(ld_map, "Ld"), "Ld")
        tabs.addTab(self._map_widget(lq_map, "Lq"), "Lq")
        layout.addWidget(tabs)

    @staticmethod
    def _map_widget(data: InductanceSaturationMap, name: str) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        plot = pg.PlotWidget(background="#F3F4F6")
        plot.setLabel("bottom", "Iq", units="A")
        plot.setLabel("left", "Id", units="A")
        plot.setTitle(f"{name}(Id, Iq) [μH]")
        plot.showGrid(x=True, y=True, alpha=0.18)
        color_map = performance_colormap()
        mesh = pg.PColorMeshItem(colorMap=color_map)
        iq_axis = np.asarray(data.iq_axis_a, dtype=float)
        id_axis = np.asarray(data.id_axis_a, dtype=float)
        values_uh = np.asarray(data.values_h, dtype=float) * 1e6
        finite_values = values_uh[np.isfinite(values_uh)]
        if finite_values.size == 0:
            minimum, maximum = 0.0, 1.0
        else:
            minimum = float(np.min(finite_values))
            maximum = float(np.max(finite_values))
            if np.isclose(minimum, maximum):
                margin = max(abs(minimum) * 0.01, 1e-9)
                minimum -= margin
                maximum += margin

        def edges(axis: np.ndarray) -> np.ndarray:
            middle = 0.5 * (axis[:-1] + axis[1:])
            return np.concatenate(
                ([axis[0] - (middle[0] - axis[0])], middle, [axis[-1] + (axis[-1] - middle[-1])])
            )

        iq_edges = edges(iq_axis)
        id_edges = edges(id_axis)
        x_nodes, y_nodes = np.meshgrid(iq_edges, id_edges, indexing="xy")
        mesh.setData(
            x_nodes,
            y_nodes,
            values_uh,
        )
        mesh.setLevels((minimum, maximum))
        plot.addItem(mesh)
        color_bar = pg.ColorBarItem(
            values=(minimum, maximum),
            colorMap=color_map,
            label="μH",
            interactive=False,
        )
        color_bar.setImageItem(mesh)
        color_bar.setParentItem(plot.plotItem)
        layout.addWidget(plot)
        hover_label = QLabel("移动鼠标查看 Id、Iq 和电感值")
        hover_label.setProperty("role", "muted")
        layout.addWidget(hover_label)

        def show_hover(scene_position) -> None:
            if not plot.sceneBoundingRect().contains(scene_position):
                return
            view_position = plot.plotItem.vb.mapSceneToView(scene_position)
            iq_value = float(view_position.x())
            id_value = float(view_position.y())
            iq_index = int(np.searchsorted(iq_edges, iq_value, side="right") - 1)
            id_index = int(np.searchsorted(id_edges, id_value, side="right") - 1)
            if not (
                0 <= iq_index < iq_axis.size
                and 0 <= id_index < id_axis.size
            ):
                hover_label.setText("当前鼠标位于 Map 范围外")
                return
            value = float(values_uh[id_index, iq_index])
            value_text = f"{value:.3f} μH" if np.isfinite(value) else "NaN"
            hover_label.setText(
                f"Id = {id_axis[id_index]:.3f} A   |   "
                f"Iq = {iq_axis[iq_index]:.3f} A   |   "
                f"{name} = {value_text}"
            )

        hover_proxy = pg.SignalProxy(
            plot.scene().sigMouseMoved,
            rateLimit=40,
            slot=lambda event: show_hover(event[0]),
        )
        # Keep references for the lifetime of the page and for UI regression
        # tests.  Each Ld/Lq page owns an independent min/max scale.
        container._map_plot = plot
        container._map_mesh = mesh
        container._map_color_bar = color_bar
        container._map_colorbar_label = "μH"
        container._map_levels = (minimum, maximum)
        container._map_hover_label = hover_label
        container._map_hover_proxy = hover_proxy
        return container
