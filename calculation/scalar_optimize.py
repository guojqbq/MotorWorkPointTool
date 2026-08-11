"""Small dependency-free bounded scalar minimizer for packaged builds."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Callable


@dataclass(frozen=True, slots=True)
class ScalarMinimizeResult:
    x: float
    fun: float
    success: bool
    nit: int


def minimize_scalar(
    objective: Callable[[float], float],
    *,
    bounds: tuple[float, float],
    method: str = "bounded",
    options: dict[str, float | int] | None = None,
) -> ScalarMinimizeResult:
    """Golden-section minimization compatible with the used SciPy subset."""

    if method != "bounded":
        raise ValueError("内置一维优化器仅支持 bounded 方法。")
    lower, upper = (float(bounds[0]), float(bounds[1]))
    if not lower < upper:
        raise ValueError("一维优化区间必须严格递增。")
    settings = options or {}
    tolerance = max(float(settings.get("xatol", 1e-10)), 1e-15)
    maximum_iterations = max(int(settings.get("maxiter", 200)), 1)
    ratio = (sqrt(5.0) - 1.0) / 2.0
    left = upper - ratio * (upper - lower)
    right = lower + ratio * (upper - lower)
    left_value = float(objective(left))
    right_value = float(objective(right))
    iterations = 0
    while (
        upper - lower > tolerance
        and iterations < maximum_iterations
    ):
        if left_value <= right_value:
            upper = right
            right = left
            right_value = left_value
            left = upper - ratio * (upper - lower)
            left_value = float(objective(left))
        else:
            lower = left
            left = right
            left_value = right_value
            right = lower + ratio * (upper - lower)
            right_value = float(objective(right))
        iterations += 1
    candidates = (
        (left, left_value),
        (right, right_value),
        (lower, float(objective(lower))),
        (upper, float(objective(upper))),
    )
    best_x, best_value = min(candidates, key=lambda candidate: candidate[1])
    return ScalarMinimizeResult(
        x=float(best_x),
        fun=float(best_value),
        success=True,
        nit=iterations,
    )
