import numpy as np

from calculation.envelope_solver import EnvelopeSolver


def test_ipmsm_low_speed_mtpa_uses_negative_id(
    ipmsm_parameters, fast_settings
):
    dataframe = EnvelopeSolver(ipmsm_parameters, fast_settings).solve()
    assert dataframe.iloc[0]["Id_A"] < -1.0
    assert dataframe.iloc[0]["Iq_A"] > 0.0
    assert dataframe.iloc[0]["Region"] == "MTPA"


def test_ipmsm_id_moves_negative_in_field_weakening(
    ipmsm_parameters, fast_settings
):
    dataframe = EnvelopeSolver(ipmsm_parameters, fast_settings).solve()
    valid = dataframe.dropna(subset=["Torque_Nm"])
    low_average = np.mean(valid.iloc[:5]["Id_A"])
    high_average = np.mean(valid.iloc[-5:]["Id_A"])
    assert high_average < low_average - 5.0
    assert "弱磁" in set(valid["Region"])
