"""Shared plot colors and reference-line helpers."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg


MTPA_COLOR = "#2563EB"
FIELD_WEAKENING_COLOR = "#16A34A"
MTPV_COLOR = "#F59E0B"
EXTERNAL_COLOR = "#DC2626"
SELECTED_COLOR = "#7C3AED"
ZERO_AXIS_COLOR = "#4B5563"
GRID_ALPHA = 0.18


def performance_colormap() -> pg.ColorMap:
    """Blue-to-red map whose extrema are unambiguously cold and warm."""

    return pg.ColorMap(
        np.array([0.0, 0.22, 0.45, 0.68, 0.84, 1.0]),
        np.array(
            [
                [20, 45, 140, 255],
                [0, 150, 230, 255],
                [0, 185, 125, 255],
                [245, 220, 45, 255],
                [245, 130, 30, 255],
                [220, 38, 38, 255],
            ],
            dtype=np.ubyte,
        ),
    )


def add_zero_axes(plot_widget: pg.PlotWidget) -> tuple[pg.InfiniteLine, pg.InfiniteLine]:
    """Add dark reference lines that remain distinct from the light grid."""

    pen = pg.mkPen(ZERO_AXIS_COLOR, width=2.2)
    x_zero = pg.InfiniteLine(pos=0.0, angle=90, pen=pen, movable=False)
    y_zero = pg.InfiniteLine(pos=0.0, angle=0, pen=pen, movable=False)
    x_zero.setZValue(20)
    y_zero.setZValue(20)
    plot_widget.addItem(x_zero, ignoreBounds=True)
    plot_widget.addItem(y_zero, ignoreBounds=True)
    return x_zero, y_zero
