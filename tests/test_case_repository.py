from __future__ import annotations

import numpy as np
import pandas as pd

from calculation.characteristic_limit_resolver import resolve_characteristic_limits
from models.analysis_result import AnalysisResult
from models.characteristic_input import CharacteristicInput
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings
from models.motor_parameters import MotorParameters
from models.operating_map import OperatingMapResult, dataframe_to_matrices
from services.case_repository import CaseRepository, compare_case_points


def _analysis_result() -> tuple:
    parameters = MotorParameters()
    inputs = CharacteristicInput()
    limits = resolve_characteristic_limits(parameters, inputs)
    external = pd.DataFrame(
        {
            "Speed_rpm": [0.0, 1000.0],
            "Torque_Nm": [100.0, 80.0],
            "Id_A": [-20.0, -40.0],
            "Iq_A": [100.0, 90.0],
        }
    )
    frame = pd.DataFrame(
        {
            "SpeedIndex": [0, 0, 1, 1],
            "TorqueIndex": [0, 1, 0, 1],
            "Speed_rpm": [0.0, 0.0, 1000.0, 1000.0],
            "TorqueRequest_Nm": [0.0, 100.0, 0.0, 80.0],
            "TorqueActual_Nm": [0.0, 100.0, 0.0, 80.0],
            "Id_A": [0.0, -20.0, 0.0, -40.0],
            "Iq_A": [0.0, 100.0, 0.0, 90.0],
            "Efficiency": [np.nan, 0.9, np.nan, 0.92],
            "CopperLoss_kW": [0.0, 1.0, 0.0, 0.9],
            "IronLoss_kW": [0.0, 0.2, 0.0, 0.3],
            "TotalMotorLoss_kW": [0.0, 1.2, 0.0, 1.2],
            "IsFeasible": [True, True, True, True],
        }
    )
    operating_map = OperatingMapResult(
        profile="full",
        speed_grid_rpm=np.array([0.0, 1000.0]),
        torque_ratio_grid=np.array([0.0, 1.0]),
        torque_axis_nm=np.array([0.0, 100.0]),
        torque_coordinate_mode="actual",
        maximum_torque_nm=np.array([100.0, 80.0]),
        dataframe=frame,
        matrices=dataframe_to_matrices(frame, (2, 2)),
        external_characteristic=external,
        algorithm_version="test",
    )
    result = AnalysisResult(
        calculation_parameters=parameters,
        external_characteristic=external,
        operating_map=operating_map,
        profile="full",
        cache_key="test",
        resolved_limits=limits,
    )
    return parameters, inputs, LossModelParameters(), MapCalculationSettings(), result


def test_case_save_load_and_non_mutating_comparison(tmp_path):
    repository = CaseRepository(tmp_path / "cases")
    parameters, inputs, losses, settings, result = _analysis_result()
    repository.save("案例A", "基准", parameters, inputs, losses, settings, result)
    loaded_a = repository.load("案例A")
    pd.testing.assert_frame_equal(
        loaded_a.external, result.external_characteristic, check_dtype=False
    )
    pd.testing.assert_frame_equal(
        loaded_a.operating_points, result.operating_map.dataframe, check_dtype=False
    )
    before_a = loaded_a.operating_points.copy(deep=True)
    repository.save("案例B", "对比", parameters, inputs, losses, settings, result)
    loaded_b = repository.load("案例B")
    delta = compare_case_points(loaded_a, loaded_b)
    assert np.nanmax(np.abs(delta["DeltaTorque_Nm"])) == 0.0
    assert np.nanmax(np.abs(delta["DeltaEfficiency"])) == 0.0
    pd.testing.assert_frame_equal(loaded_a.operating_points, before_a)
    assert repository.list_cases() == ["案例A", "案例B"]
