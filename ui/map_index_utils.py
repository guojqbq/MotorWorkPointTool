"""Safe conversion helpers for clickable operating-map scatter points."""

from __future__ import annotations

import math
from numbers import Real
from typing import Any

import numpy as np


def normalize_flat_index(raw_index: Any) -> int:
    """Return one validated Python ``int`` from scatter-point user data."""

    if raw_index is None:
        raise ValueError("内部工作点 data 为空；预期为一个 flat_index。")
    index_array = np.asarray(raw_index)
    if index_array.size != 1:
        raise ValueError(
            "内部工作点 data 必须只包含一个 flat_index，"
            f"实际包含 {index_array.size} 个元素，shape={index_array.shape}。"
        )
    scalar = index_array.reshape(-1)[0]
    if isinstance(scalar, (bool, np.bool_)):
        raise ValueError("内部工作点 flat_index 不能是布尔值。")
    if isinstance(scalar, (Real, np.number)):
        numeric = float(scalar)
        if not math.isfinite(numeric) or not numeric.is_integer():
            raise ValueError(
                f"内部工作点 flat_index 必须是有限整数，实际为 {scalar!r}。"
            )
    try:
        flat_index = int(scalar)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"内部工作点 flat_index 无法转换为整数：{scalar!r}。"
        ) from exc
    return flat_index


def clicked_flat_index(points: Any) -> int | None:
    """Extract the first clicked spot's scalar flat index.

    PyQtGraph returns an ndarray of ``SpotItem`` objects.  Multiple spots can
    legitimately overlap; the first item is the topmost click candidate.
    """

    if points is None:
        return None
    points_array = np.asarray(points, dtype=object)
    if points_array.size == 0:
        return None
    first_point = points_array.reshape(-1)[0]
    raw_index = first_point.data()
    return normalize_flat_index(raw_index)
