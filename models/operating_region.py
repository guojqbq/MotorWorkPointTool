"""Canonical internal operating-point regions."""

from __future__ import annotations

from enum import Enum


class OperatingRegion(str, Enum):
    MTPA = "MTPA"
    FIELD_WEAKENING = "FIELD_WEAKENING"
    MTPV = "MTPV"
    OTHER = "OTHER"
