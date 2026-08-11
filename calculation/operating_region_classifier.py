"""Numerically robust classification of independently solved map points."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

from models.operating_region import OperatingRegion


@dataclass(frozen=True, slots=True)
class OperatingRegionClassificationConfig:
    mtpa_distance_tolerance: float = 0.015
    mtpv_distance_tolerance: float = 0.020
    voltage_active_threshold: float = 0.98

    def validated(self) -> "OperatingRegionClassificationConfig":
        if not 0.0 < self.mtpa_distance_tolerance < 1.0:
            raise ValueError("MTPA归一化距离阈值必须在0到1之间。")
        if not 0.0 < self.mtpv_distance_tolerance < 1.0:
            raise ValueError("MTPV归一化距离阈值必须在0到1之间。")
        if not 0.0 < self.voltage_active_threshold <= 1.0:
            raise ValueError("电压激活阈值必须在0到1之间。")
        return self


@dataclass(frozen=True, slots=True)
class OperatingRegionClassification:
    region: OperatingRegion
    mtpa_distance_a: float
    mtpv_distance_a: float
    near_mtpa: bool
    near_mtpv: bool


def min_distance_to_curve(
    id_value: float,
    iq_value: float,
    curve_id_values: ArrayLike,
    curve_iq_values: ArrayLike,
) -> float:
    """Return Euclidean distance to valid discrete curve points.

    Invalid work points, empty curves, shape mismatches, and all-NaN curves
    return infinity rather than participating in an ambiguous array truth test.
    """

    if not np.isfinite(id_value) or not np.isfinite(iq_value):
        return float("inf")
    ids = np.asarray(curve_id_values, dtype=float).reshape(-1)
    iqs = np.asarray(curve_iq_values, dtype=float).reshape(-1)
    if ids.size == 0 or iqs.size == 0 or ids.size != iqs.size:
        return float("inf")
    valid = np.isfinite(ids) & np.isfinite(iqs)
    if not np.any(valid):
        return float("inf")
    distances = np.hypot(id_value - ids[valid], iq_value - iqs[valid])
    if distances.size == 0:
        return float("inf")
    return float(np.min(distances))


def classify_internal_operating_point(
    *,
    id_a: float,
    iq_a: float,
    current_limit_a: float,
    voltage_utilization: float,
    voltage_constraint_active: bool,
    active_constraint: str,
    control_strategy: str,
    mtpa_curve_id_a: ArrayLike,
    mtpa_curve_iq_a: ArrayLike,
    mtpv_curve_id_a: ArrayLike,
    mtpv_curve_iq_a: ArrayLike,
    config: OperatingRegionClassificationConfig,
) -> OperatingRegionClassification:
    config.validated()
    scale = max(float(current_limit_a), np.finfo(float).eps)
    mtpa_distance = min_distance_to_curve(
        id_a, iq_a, mtpa_curve_id_a, mtpa_curve_iq_a
    )
    mtpv_distance = min_distance_to_curve(
        id_a, iq_a, mtpv_curve_id_a, mtpv_curve_iq_a
    )
    near_mtpa = mtpa_distance / scale <= config.mtpa_distance_tolerance
    near_mtpv = mtpv_distance / scale <= config.mtpv_distance_tolerance
    voltage_active = (
        bool(voltage_constraint_active)
        or (
            np.isfinite(voltage_utilization)
            and voltage_utilization >= config.voltage_active_threshold
        )
        or "voltage" in str(active_constraint).lower()
    )
    strategy_indicates_field_weakening = (
        "fieldweakening" in str(control_strategy).replace("_", "").lower()
    )

    if voltage_active and near_mtpv:
        region = OperatingRegion.MTPV
    elif near_mtpa and not voltage_active:
        region = OperatingRegion.MTPA
    elif voltage_active or strategy_indicates_field_weakening:
        region = OperatingRegion.FIELD_WEAKENING
    else:
        region = OperatingRegion.OTHER
    return OperatingRegionClassification(
        region=region,
        mtpa_distance_a=mtpa_distance,
        mtpv_distance_a=mtpv_distance,
        near_mtpa=near_mtpa,
        near_mtpv=near_mtpv,
    )
