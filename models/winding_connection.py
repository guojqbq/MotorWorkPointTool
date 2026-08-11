"""Winding connection and open-winding topology conventions."""

from __future__ import annotations

from enum import Enum
from math import sqrt


class WindingConnection(str, Enum):
    STAR = "STAR"
    DELTA = "DELTA"
    OPEN_WINDING = "OPEN_WINDING"

    @property
    def line_to_winding_current_factor(self) -> float:
        return 1.0 / sqrt(3.0) if self is WindingConnection.DELTA else 1.0


class OpenWindingTopology(str, Enum):
    DUAL_COMMON_DC = "DUAL_COMMON_DC"
    DUAL_ISOLATED_DC = "DUAL_ISOLATED_DC"
    CUSTOM_DUAL_UDC = "CUSTOM_DUAL_UDC"


def parse_winding_connection(value: object) -> WindingConnection:
    if isinstance(value, WindingConnection):
        return value
    aliases = {
        "Y": WindingConnection.STAR,
        "STAR": WindingConnection.STAR,
        "星接": WindingConnection.STAR,
        "星形": WindingConnection.STAR,
        "DELTA": WindingConnection.DELTA,
        "D": WindingConnection.DELTA,
        "角接": WindingConnection.DELTA,
        "三角形": WindingConnection.DELTA,
        "OPEN_END": WindingConnection.OPEN_WINDING,
        "OPEN-END": WindingConnection.OPEN_WINDING,
        "OPEN_WINDING": WindingConnection.OPEN_WINDING,
        "开绕组": WindingConnection.OPEN_WINDING,
    }
    text = str(value or "STAR").strip().upper()
    if text in aliases:
        return aliases[text]
    return WindingConnection(text)


def parse_open_winding_topology(value: object) -> OpenWindingTopology:
    if isinstance(value, OpenWindingTopology):
        return value
    return OpenWindingTopology(
        str(value or OpenWindingTopology.DUAL_COMMON_DC.value).strip().upper()
    )
