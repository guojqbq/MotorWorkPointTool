import numpy as np

from calculation.constraint_curves import constant_torque_curve
from calculation.envelope_solver import EnvelopeSolver


def test_spmsm_constant_torque_curve_is_horizontal(spmsm_parameters):
    ids = np.linspace(-spmsm_parameters.imax_peak_a, 0.0, 101)
    iqs = constant_torque_curve(spmsm_parameters, 50.0, ids)
    assert np.all(np.isfinite(iqs))
    assert np.ptp(iqs) < 1e-12


def test_spmsm_low_speed_optimum_id_is_near_zero(
    spmsm_parameters, fast_settings
):
    dataframe = EnvelopeSolver(spmsm_parameters, fast_settings).solve()
    low_speed = dataframe.iloc[:3]
    assert np.max(np.abs(low_speed["Id_A"].to_numpy())) < 1e-3


def test_spmsm_enters_field_weakening(spmsm_parameters, fast_settings):
    dataframe = EnvelopeSolver(spmsm_parameters, fast_settings).solve()
    valid = dataframe.dropna(subset=["Torque_Nm"])
    assert valid.iloc[-1]["Id_A"] < valid.iloc[0]["Id_A"] - 1.0
    assert "弱磁" in set(valid["Region"])
