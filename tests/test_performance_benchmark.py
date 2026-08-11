from __future__ import annotations

import numpy as np

from benchmarks.benchmark_performance import run
from models.saturation_map import InductanceSaturationMap


def test_saturation_map_reuses_prebuilt_interpolation_arrays():
    data = InductanceSaturationMap.from_arrays(
        [-400.0, -200.0, 0.0],
        [0.0, 200.0, 400.0],
        np.full((3, 3), 500e-6),
    )
    id_array = data._id_array
    iq_array = data._iq_array
    value_array = data._values_array
    for _ in range(5):
        assert np.isfinite(data.interpolate_h(-100.0, 100.0))
        assert data._id_array is id_array
        assert data._iq_array is iq_array
        assert data._values_array is value_array


def test_11_by_11_benchmark_has_bounded_point_time_and_no_point_optimizer():
    constant = run("constant", 11, 11)
    saturation = run("saturation", 11, 11)
    assert constant["total_points"] == saturation["total_points"] == 121
    assert constant["average_point_ms"] < 100.0
    assert saturation["average_point_ms"] < 100.0
    assert saturation["maximum_point_ms"] < 100.0
    assert saturation["map_counts"]["optimize_calls"] == 0
    assert saturation["map_counts"]["torque_evaluated_points"] < 10_000_000
    assert saturation["feasible_points"] > 0
    assert saturation["warm_start_points"] > 0
