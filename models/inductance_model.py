"""Selectable stator inductance model."""

from __future__ import annotations

from enum import Enum


class InductanceModel(str, Enum):
    CONSTANT = "CONSTANT"
    SATURATION_MAP = "SATURATION_MAP"


def parse_inductance_model(value: object) -> InductanceModel:
    if isinstance(value, InductanceModel):
        return value
    return InductanceModel(str(value or "CONSTANT").strip().upper())
