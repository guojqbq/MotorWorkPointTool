from dataclasses import replace

import numpy as np

from calculation.envelope_solver import EnvelopeSolver


def _valid(dataframe):
    return dataframe.dropna(subset=["Torque_Nm"])


def test_all_points_satisfy_current_and_voltage_constraints(
    ipmsm_parameters, fast_settings
):
    p = ipmsm_parameters
    dataframe = EnvelopeSolver(p, fast_settings).solve()
    valid = _valid(dataframe)
    assert len(valid) > 0
    assert np.all(valid["Is_A"].to_numpy() <= p.imax_peak_a * (1 + 1e-8))
    assert np.all(valid["Us_V"].to_numpy() <= p.umax_v * (1 + 1e-8))


def test_power_limit_is_never_exceeded(ipmsm_parameters, fast_settings):
    p = replace(ipmsm_parameters, pmax_kw=20.0)
    dataframe = EnvelopeSolver(p, fast_settings).solve()
    valid = _valid(dataframe)
    assert valid["Power_kW"].max() <= 20.0 * (1 + 1e-8)
    assert "功率限制" in set(valid["Region"])
    assert any(
        "功率" in constraints for constraints in valid["ActiveConstraint"].astype(str)
    )


def test_id_min_is_respected(ipmsm_parameters, fast_settings):
    p = replace(ipmsm_parameters, id_min_a=-80.0)
    dataframe = EnvelopeSolver(p, fast_settings).solve()
    valid = _valid(dataframe)
    assert valid["Id_A"].min() >= -80.0 - p.imax_peak_a * 1e-8


def test_speed_sweep_contains_both_endpoints(ipmsm_parameters, fast_settings):
    dataframe = EnvelopeSolver(ipmsm_parameters, fast_settings).solve()
    assert dataframe.iloc[0]["Speed_rpm"] == 0.0
    assert dataframe.iloc[-1]["Speed_rpm"] == ipmsm_parameters.max_speed_rpm
    assert len(dataframe) == ipmsm_parameters.speed_points


def test_infeasible_speed_is_retained_and_not_faked(
    spmsm_parameters, fast_settings
):
    p = replace(
        spmsm_parameters,
        udc_v=20.0,
        max_speed_rpm=20000.0,
        id_min_a=0.0,
        speed_points=11,
    )
    dataframe = EnvelopeSolver(p, fast_settings).solve()
    last = dataframe.iloc[-1]
    assert last["Region"] == "无可行工作点"
    assert np.isnan(last["Torque_Nm"])
    assert dataframe.iloc[0]["Region"] != "无可行工作点"
