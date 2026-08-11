import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from calculation.operating_map_grid import generate_nonuniform_ratios
from calculation.operating_map_solver import OperatingMapSolver
from calculation.operating_region_classifier import (
    OperatingRegionClassificationConfig,
    classify_internal_operating_point,
    min_distance_to_curve,
)
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings
from models.motor_parameters import MotorParameters
from models.operating_region import OperatingRegion


@pytest.fixture(scope="module")
def small_map_case():
    parameters = MotorParameters(
        pole_pairs=4,
        rs_ohm=0.03,
        ld_mh=0.60,
        lq_mh=1.00,
        flux_pm_wb=0.06,
        udc_v=320.0,
        imax_a=180.0,
        max_speed_rpm=12000.0,
        speed_points=7,
        voltage_utilization=0.95,
        modulation="SVPWM",
        current_definition="peak",
    ).validated()
    settings = MapCalculationSettings(
        preview_speed_points=5,
        preview_torque_points=7,
        full_speed_points=7,
        full_torque_points=9,
    )
    solver = OperatingMapSolver(
        parameters, LossModelParameters(), settings
    )
    return parameters, solver.limits, solver.solve("full")


@pytest.fixture(scope="module")
def dense_map_case():
    parameters = MotorParameters.example_ipmsm()
    solver = OperatingMapSolver(parameters)
    return parameters, solver.limits, solver.solve("full")


def _classification(
    *,
    point=(1.0, 2.0),
    mtpa=((1.0,), (2.0,)),
    mtpv=((-8.0,), (4.0,)),
    voltage_utilization=0.5,
    voltage_active=False,
    strategy="MTPA_FieldWeakening_MTPV",
):
    return classify_internal_operating_point(
        id_a=point[0],
        iq_a=point[1],
        current_limit_a=100.0,
        voltage_utilization=voltage_utilization,
        voltage_constraint_active=voltage_active,
        active_constraint="Voltage" if voltage_active else "None",
        control_strategy=strategy,
        mtpa_curve_id_a=mtpa[0],
        mtpa_curve_iq_a=mtpa[1],
        mtpv_curve_id_a=mtpv[0],
        mtpv_curve_iq_a=mtpv[1],
        config=OperatingRegionClassificationConfig(),
    )


def test_region_classifier_uses_reference_distance_and_voltage_state():
    mtpa = _classification(point=(-12.0, 30.0), mtpa=((-12.0,), (30.0,)))
    field_weakening = _classification(
        point=(-25.0, 40.0),
        mtpa=((0.0,), (40.0,)),
        mtpv=((-50.0,), (20.0,)),
        voltage_utilization=0.99,
        voltage_active=True,
    )
    mtpv = _classification(
        point=(-50.0, 20.0),
        mtpa=((0.0,), (40.0,)),
        mtpv=((-50.0,), (20.0,)),
        voltage_utilization=0.99,
        voltage_active=True,
    )
    assert mtpa.region == OperatingRegion.MTPA
    assert mtpa.near_mtpa
    assert mtpa.region != OperatingRegion.FIELD_WEAKENING
    assert field_weakening.region == OperatingRegion.FIELD_WEAKENING
    assert mtpv.region == OperatingRegion.MTPV


def test_curve_distance_handles_empty_nan_and_invalid_inputs():
    assert np.isinf(min_distance_to_curve(0.0, 0.0, [], []))
    assert np.isinf(
        min_distance_to_curve(0.0, 0.0, [np.nan], [np.nan])
    )
    assert np.isinf(min_distance_to_curve(np.nan, 0.0, [0.0], [0.0]))
    assert min_distance_to_curve(3.0, 4.0, [0.0], [0.0]) == 5.0


def test_nonuniform_actual_torque_axis_is_exact_and_end_dense():
    ratios = generate_nonuniform_ratios(121)
    assert len(ratios) == 121
    assert ratios[0] == 0.0
    assert ratios[-1] == 1.0
    assert np.all(np.diff(ratios) > 0.0)
    middle_spacing = np.median(np.diff(ratios)[45:75])
    assert np.mean(np.diff(ratios)[:10]) < middle_spacing
    assert np.mean(np.diff(ratios)[-10:]) < middle_spacing


def test_default_full_map_density_and_diagnostics(dense_map_case):
    _parameters, _limits, result = dense_map_case
    diagnostics = result.diagnostics()
    assert result.shape == (81, 121)
    assert diagnostics["total_points"] == 9801
    assert diagnostics["total_points"] > 81 * 81
    assert diagnostics["inside_envelope_points"] == diagnostics[
        "feasible_points"
    ]
    assert diagnostics["feasible_points"] > 81
    assert diagnostics["below_10_percent_torque_points"] > 0
    assert diagnostics["solver_failed_points"] == 0
    assert diagnostics["removed_by_efficiency_points"] == 0
    assert diagnostics["points_before_deduplication"] == 9801
    assert diagnostics["points_after_deduplication"] == 9801
    assert diagnostics["mtpa_points"] > 0
    assert diagnostics["field_weakening_points"] > 0
    assert (
        diagnostics["mtpa_points"]
        + diagnostics["field_weakening_points"]
        + diagnostics["mtpv_points"]
        + diagnostics["other_points"]
        == diagnostics["feasible_points"]
    )


def test_dense_map_points_obey_final_constraints(dense_map_case):
    parameters, limits, result = dense_map_case
    valid = result.dataframe[result.dataframe["IsFeasible"]]
    assert (valid["Is_A"] <= limits.max_current_vector_a * (1 + 2e-8)).all()
    assert (valid["Us_V"] <= limits.max_voltage_dq_v * (1 + 2e-8)).all()
    if parameters.id_min_peak_a is not None:
        assert (
            valid["Id_A"]
            >= parameters.id_min_peak_a
            - limits.max_current_vector_a * 2e-8
        ).all()
    if parameters.pmax_kw is not None:
        assert (
            valid["MechanicalPower_kW"]
            <= parameters.pmax_kw + 1e-7
        ).all()


def test_low_efficiency_points_keep_dq_and_flat_index(small_map_case):
    _parameters, _limits, result = small_map_case
    frame = result.dataframe
    retained = frame[
        frame["IsFeasible"] & frame["Efficiency"].isna()
    ]
    assert not retained.empty
    assert np.isfinite(retained[["Id_A", "Iq_A", "Ud_V", "Uq_V"]]).all().all()
    assert set(retained.index).issubset(
        set(result.feasible_map_indices().tolist())
    )
    assert result.diagnostics()["removed_by_efficiency_points"] == 0


def test_same_dq_at_different_operating_conditions_is_not_deduplicated(
    small_map_case,
):
    _parameters, _limits, result = small_map_case
    valid = result.dataframe[result.dataframe["IsFeasible"]].copy()
    valid["RoundedId"] = valid["Id_A"].round(6)
    valid["RoundedIq"] = valid["Iq_A"].round(6)
    repeated = valid.groupby(["RoundedId", "RoundedIq"]).filter(
        lambda group: len(group) > 1
    )
    assert not repeated.empty
    assert repeated[["Speed_rpm", "TorqueActual_Nm"]].drop_duplicates().shape[
        0
    ] > 1
    assert len(result.dataframe) == result.shape[0] * result.shape[1]


def test_outside_envelope_points_are_infeasible_and_not_display_candidates(
    small_map_case,
):
    _parameters, _limits, result = small_map_case
    outside = result.dataframe["SolverStatus"] == "OutsideEnvelope"
    assert outside.any()
    assert not result.dataframe.loc[outside, "IsFeasible"].any()
    assert not np.isfinite(
        result.dataframe.loc[outside, ["Id_A", "Iq_A"]]
    ).any().any()
    assert len(result.feasible_map_indices()) == int(
        result.dataframe["IsFeasible"].sum()
    )


def test_three_independent_scatter_items_counts_indexes_and_clicks(
    small_map_case,
):
    pytest.importorskip("PySide6")
    pytest.importorskip("pyqtgraph")
    from PySide6.QtWidgets import QApplication

    from ui.dq_plot import DqPlot
    from ui.torque_speed_plot import TorqueSpeedPlot

    class AcceptedEvent:
        def __init__(self):
            self.accepted = False

        def accept(self):
            self.accepted = True

    app = QApplication.instance() or QApplication([])
    parameters, limits, result = small_map_case
    left = TorqueSpeedPlot()
    left.set_dataframe(result.external_characteristic)
    left.set_operating_map(result)
    dq = DqPlot()
    dq.set_results(parameters, result.external_characteristic, limits)
    dq.set_operating_map(result)

    try:
        for plot in (left, dq):
            items = plot.operating_region_items
            assert set(items) == {"MTPA", "FIELD_WEAKENING", "MTPV"}
            assert len({id(item) for item in items.values()}) == 3
            assert sum(len(item.points()) for item in items.values()) == int(
                result.dataframe["IsFeasible"].sum()
            )
            assert all(
                type(point.data()) is int
                for item in items.values()
                for point in item.points()
            )
            clicked = []
            plot.internalPointSelected.connect(clicked.append)
            for item in items.values():
                points = item.points()
                assert points.size > 0
                point = points[0]
                event = AcceptedEvent()
                item.sigClicked.emit(
                    item, np.asarray([point], dtype=object), event
                )
                assert event.accepted
                assert clicked[-1] == int(point.data())
    finally:
        left.close()
        dq.close()
        left.deleteLater()
        dq.deleteLater()
        app.processEvents()


def test_dq_display_modes_preserve_original_map_indices(small_map_case):
    pytest.importorskip("PySide6")
    pytest.importorskip("pyqtgraph")
    from PySide6.QtWidgets import QApplication

    from ui.dq_plot import DqPlot

    app = QApplication.instance() or QApplication([])
    parameters, limits, result = small_map_case
    plot = DqPlot()
    plot.set_results(parameters, result.external_characteristic, limits)
    plot.set_operating_map(result)
    frame = result.dataframe
    candidate_rows = (
        frame[frame["IsFeasible"]]
        .groupby("SpeedIndex")
        .size()
        .sort_values(ascending=False)
    )
    speed_index = int(candidate_rows.index[0])
    row_indices = frame.index[
        frame["IsFeasible"] & (frame["SpeedIndex"] == speed_index)
    ].to_numpy(dtype=int)
    selected = int(row_indices[len(row_indices) // 2])
    plot.set_selected_map_index(selected)

    plot.set_internal_display_mode(DqPlot.DISPLAY_CURRENT_SPEED)
    assert plot.displayed_internal_point_count == len(row_indices)
    trace_id, trace_iq = plot._current_speed_trace.getData()
    assert len(trace_id) == len(trace_iq) == len(row_indices)

    plot.set_internal_display_mode(DqPlot.DISPLAY_ALL_WITH_SPEED)
    assert plot.displayed_internal_point_count == int(
        frame["IsFeasible"].sum()
    )
    displayed_indexes = {
        int(point.data())
        for item in plot.operating_region_items.values()
        for point in item.points()
    }
    assert displayed_indexes == set(result.feasible_map_indices().tolist())
    plot.close()
    plot.deleteLater()
    app.processEvents()
