"""Validated two-dimensional Ld/Lq saturation table and interpolation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray


@dataclass(frozen=True, slots=True)
class InductanceSaturationMap:
    """Inductance in henry on an Id-by-Iq grid.

    Axes are stored in strictly increasing order. Queries outside the table
    return NaN; numerical extrapolation and boundary clamping are forbidden.
    """

    id_axis_a: tuple[float, ...]
    iq_axis_a: tuple[float, ...]
    values_h: tuple[tuple[float, ...], ...]
    source_name: str = ""

    def validated(self) -> "InductanceSaturationMap":
        ids = np.asarray(self.id_axis_a, dtype=float)
        iqs = np.asarray(self.iq_axis_a, dtype=float)
        values = np.asarray(self.values_h, dtype=float)
        errors: list[str] = []
        if ids.ndim != 1 or ids.size < 2 or not np.all(np.isfinite(ids)):
            errors.append("Id 轴至少需要两个有限数值点。")
        elif not np.all(np.diff(ids) > 0.0):
            errors.append("Id 轴必须严格递增且不能重复。")
        if iqs.ndim != 1 or iqs.size < 2 or not np.all(np.isfinite(iqs)):
            errors.append("Iq 轴至少需要两个有限数值点。")
        elif not np.all(np.diff(iqs) > 0.0):
            errors.append("Iq 轴必须严格递增且不能重复。")
        if values.shape != (ids.size, iqs.size):
            errors.append(
                f"电感矩阵形状应为 {ids.size}×{iqs.size}，实际为 {values.shape}。"
            )
        elif not np.all(np.isfinite(values)) or np.any(values <= 0.0):
            errors.append("电感矩阵必须全部为有限正数。")
        if errors:
            raise ValueError("\n".join(errors))
        return self

    @classmethod
    def from_arrays(
        cls,
        id_axis_a: Sequence[float],
        iq_axis_a: Sequence[float],
        values_h: ArrayLike,
        *,
        source_name: str = "",
    ) -> "InductanceSaturationMap":
        ids = np.asarray(id_axis_a, dtype=float).reshape(-1)
        iqs = np.asarray(iq_axis_a, dtype=float).reshape(-1)
        values = np.asarray(values_h, dtype=float)
        if values.shape != (ids.size, iqs.size):
            raise ValueError("电感矩阵尺寸必须与 Id/Iq 轴一致。")
        id_order = np.argsort(ids)
        iq_order = np.argsort(iqs)
        ids = ids[id_order]
        iqs = iqs[iq_order]
        values = values[np.ix_(id_order, iq_order)]
        return cls(
            id_axis_a=tuple(float(value) for value in ids),
            iq_axis_a=tuple(float(value) for value in iqs),
            values_h=tuple(
                tuple(float(value) for value in row) for row in values
            ),
            source_name=str(source_name),
        ).validated()

    def interpolate_h(
        self, id_a: ArrayLike, iq_a: ArrayLike
    ) -> NDArray[np.float64]:
        self.validated()
        ids = np.asarray(self.id_axis_a, dtype=float)
        iqs = np.asarray(self.iq_axis_a, dtype=float)
        values = np.asarray(self.values_h, dtype=float)
        id_values, iq_values = np.broadcast_arrays(
            np.asarray(id_a, dtype=float), np.asarray(iq_a, dtype=float)
        )
        outside = (
            (id_values < ids[0])
            | (id_values > ids[-1])
            | (iq_values < iqs[0])
            | (iq_values > iqs[-1])
        )
        clipped_id = np.clip(id_values, ids[0], ids[-1])
        clipped_iq = np.clip(iq_values, iqs[0], iqs[-1])
        id_index = np.clip(np.searchsorted(ids, clipped_id, side="right") - 1, 0, ids.size - 2)
        iq_index = np.clip(np.searchsorted(iqs, clipped_iq, side="right") - 1, 0, iqs.size - 2)
        id_weight = (clipped_id - ids[id_index]) / (ids[id_index + 1] - ids[id_index])
        iq_weight = (clipped_iq - iqs[iq_index]) / (iqs[iq_index + 1] - iqs[iq_index])
        v00 = values[id_index, iq_index]
        v10 = values[id_index + 1, iq_index]
        v01 = values[id_index, iq_index + 1]
        v11 = values[id_index + 1, iq_index + 1]
        interpolated = (
            (1.0 - id_weight) * (1.0 - iq_weight) * v00
            + id_weight * (1.0 - iq_weight) * v10
            + (1.0 - id_weight) * iq_weight * v01
            + id_weight * iq_weight * v11
        ).astype(float, copy=False)
        return np.where(outside, np.nan, interpolated)

    def contains(self, id_a: ArrayLike, iq_a: ArrayLike) -> NDArray[np.bool_]:
        ids = np.asarray(id_a, dtype=float)
        iqs = np.asarray(iq_a, dtype=float)
        ids, iqs = np.broadcast_arrays(ids, iqs)
        return (
            (ids >= self.id_axis_a[0])
            & (ids <= self.id_axis_a[-1])
            & (iqs >= self.iq_axis_a[0])
            & (iqs <= self.iq_axis_a[-1])
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id_axis_a": list(self.id_axis_a),
            "iq_axis_a": list(self.iq_axis_a),
            "values_h": [list(row) for row in self.values_h],
            "source_name": self.source_name,
        }

    @classmethod
    def from_dict(
        cls, values: Mapping[str, Any] | None
    ) -> "InductanceSaturationMap | None":
        if not values:
            return None
        return cls.from_arrays(
            values["id_axis_a"],
            values["iq_axis_a"],
            values["values_h"],
            source_name=str(values.get("source_name", "")),
        )

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.id_axis_a), len(self.iq_axis_a)
