from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QTabWidget

from models.saturation_map import InductanceSaturationMap
from ui.plot_theme import performance_colormap
from ui.saturation_map_dialog import SaturationMapPreviewDialog


def _map(values) -> InductanceSaturationMap:
    return InductanceSaturationMap.from_arrays(
        [-300.0, -150.0, 0.0],
        [0.0, 150.0, 300.0],
        np.asarray(values, dtype=float) * 1e-6,
    )


def test_preview_uses_independent_levels_colorbar_units_and_hover_label():
    app = QApplication.instance() or QApplication([])
    ld_map = _map([[300, 250, 200], [280, 220, 170], [250, 190, 120]])
    lq_map = _map([[2200, 1800, 1400], [2100, 1600, 1100], [1900, 1400, 900]])
    dialog = SaturationMapPreviewDialog(ld_map, lq_map)
    tabs = dialog.findChild(QTabWidget)
    ld_page = tabs.widget(0)
    lq_page = tabs.widget(1)
    assert ld_page._map_levels == pytest.approx((120.0, 300.0))
    assert lq_page._map_levels == pytest.approx((900.0, 2200.0))
    assert ld_page._map_colorbar_label == "μH"
    assert "Id" in ld_page._map_hover_label.text()
    assert "Iq" in ld_page._map_hover_label.text()

    lookup = performance_colormap().getLookupTable(0.0, 1.0, 16)
    assert lookup[0, 2] > lookup[0, 0]  # low end is blue
    assert lookup[-1, 0] > lookup[-1, 2]  # high end is red
    dialog.close()
    dialog.deleteLater()
    app.processEvents()
