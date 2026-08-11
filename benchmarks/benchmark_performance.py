"""Reproducible PMSM solver benchmark with physics-call counters."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import calculation.envelope_solver as envelope_module
import calculation.operating_map_solver as map_module
import calculation.reference_trajectories as reference_module
from calculation.envelope_solver import EnvelopeSolver, SolverSettings
from calculation.operating_map_solver import OperatingMapSolver
from models.inductance_model import InductanceModel
from models.map_calculation_settings import MapCalculationSettings
from models.motor_parameters import MotorParameters
from models.saturation_map import InductanceSaturationMap


def _saturation_map(values_uh: list[list[float]]) -> InductanceSaturationMap:
    return InductanceSaturationMap.from_arrays(
        [-400.0, -200.0, 0.0],
        [0.0, 200.0, 400.0],
        np.asarray(values_uh, dtype=float) * 1e-6,
        source_name="benchmark",
    )


def benchmark_parameters(model: str, speed_points: int) -> MotorParameters:
    parameters = replace(
        MotorParameters.example_ipmsm(), speed_points=int(speed_points)
    )
    if model == "constant":
        return parameters
    return replace(
        parameters,
        inductance_model=InductanceModel.SATURATION_MAP,
        ld_saturation_map=_saturation_map(
            [[600, 560, 500], [520, 480, 430], [460, 420, 380]]
        ),
        lq_saturation_map=_saturation_map(
            [[2100, 1800, 1450], [2000, 1650, 1250], [1900, 1500, 1050]]
        ),
    ).validated()


def _size(*values) -> int:
    arrays = [np.asarray(value) for value in values]
    shape = np.broadcast_shapes(*(value.shape for value in arrays))
    return int(np.prod(shape, dtype=int)) if shape else 1


@contextmanager
def counted_calls():
    counts = {
        "inductance_calls": 0,
        "inductance_points": 0,
        "torque_calls": 0,
        "torque_evaluated_points": 0,
        "voltage_calls": 0,
        "voltage_evaluated_points": 0,
        "optimize_calls": 0,
    }
    originals: list[tuple[object, str, object]] = []

    original_inductances = MotorParameters.inductances_h

    def inductances(parameters, id_a, iq_a):
        counts["inductance_calls"] += 1
        counts["inductance_points"] += _size(id_a, iq_a)
        return original_inductances(parameters, id_a, iq_a)

    originals.append((MotorParameters, "inductances_h", original_inductances))
    MotorParameters.inductances_h = inductances

    def patch(module, name, call_key, point_key, value_count):
        original = getattr(module, name)

        def wrapper(*args, **kwargs):
            counts[call_key] += 1
            counts[point_key] += _size(*args[:value_count])
            return original(*args, **kwargs)

        originals.append((module, name, original))
        setattr(module, name, wrapper)

    for module in (envelope_module, map_module, reference_module):
        patch(
            module,
            "electromagnetic_torque",
            "torque_calls",
            "torque_evaluated_points",
            2,
        )
        patch(
            module,
            "dq_voltage",
            "voltage_calls",
            "voltage_evaluated_points",
            2,
        )
    original_minimize = reference_module.minimize_scalar

    def minimize_wrapper(*args, **kwargs):
        counts["optimize_calls"] += 1
        return original_minimize(*args, **kwargs)

    originals.append((reference_module, "minimize_scalar", original_minimize))
    reference_module.minimize_scalar = minimize_wrapper
    try:
        yield counts
    finally:
        for owner, name, original in reversed(originals):
            setattr(owner, name, original)


def run(model: str, speed_points: int, torque_points: int) -> dict:
    parameters = benchmark_parameters(model, speed_points)
    settings = MapCalculationSettings(
        full_speed_points=speed_points,
        full_torque_points=torque_points,
    )
    slowest = {"seconds": 0.0, "speed_rpm": 0.0, "torque_nm": 0.0}
    warm_start_points = 0

    def diagnostic(event: dict) -> None:
        nonlocal warm_start_points
        if event.get("stage") != "internal_map":
            return
        warm_start_points += int(bool(event.get("warm_start_used", False)))
        elapsed = float(event.get("elapsed_seconds", 0.0))
        if elapsed > slowest["seconds"]:
            slowest.update(
                seconds=elapsed,
                speed_rpm=float(event.get("speed_rpm", 0.0)),
                torque_nm=float(event.get("torque_nm", 0.0)),
            )

    with counted_calls() as counts:
        total_started = perf_counter()
        external_started = perf_counter()
        external = EnvelopeSolver(
            parameters,
            SolverSettings(coarse_id_points=1001, fine_id_points=301),
        ).solve()
        external_seconds = perf_counter() - external_started
        external_counts = dict(counts)
        map_started = perf_counter()
        operating_map = OperatingMapSolver(
            parameters, settings=settings
        ).solve(
            "full",
            external_characteristic=external,
            diagnostic_callback=diagnostic,
        )
        map_seconds = perf_counter() - map_started
        total_seconds = perf_counter() - total_started
    diagnostics = operating_map.diagnostics()
    result = {
        "model": model,
        "speed_points": speed_points,
        "torque_points": torque_points,
        "total_points": speed_points * torque_points,
        "external_seconds": external_seconds,
        "map_seconds": map_seconds,
        "total_seconds": total_seconds,
        "average_point_ms": 1000.0 * map_seconds / (speed_points * torque_points),
        "maximum_point_ms": 1000.0 * slowest["seconds"],
        "slowest_speed_rpm": slowest["speed_rpm"],
        "slowest_torque_nm": slowest["torque_nm"],
        "solver_failed_points": int(diagnostics["solver_failed_points"]),
        "feasible_points": int(diagnostics["feasible_points"]),
        "warm_start_points": warm_start_points,
        "external_counts": external_counts,
        "map_counts": {
            key: int(counts[key] - external_counts[key]) for key in counts
        },
        **counts,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("constant", "saturation"), required=True)
    parser.add_argument("--speed-points", type=int, required=True)
    parser.add_argument("--torque-points", type=int, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.model, args.speed_points, args.torque_points)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
