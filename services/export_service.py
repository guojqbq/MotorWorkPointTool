"""Export calculated work points to external files."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from models.characteristic_input import CharacteristicInput
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings
from models.motor_parameters import MotorParameters
from models.operating_map import MAP_RESULT_COLUMNS, OperatingMapResult
from models.operating_point import RESULT_COLUMNS
from models.resolved_characteristic_limits import ResolvedCharacteristicLimits


def export_operating_points_csv(
    dataframe: pd.DataFrame, path: str | Path
) -> Path:
    missing = [column for column in RESULT_COLUMNS if column not in dataframe.columns]
    if missing:
        raise ValueError(f"结果数据缺少列：{', '.join(missing)}")
    target = Path(path)
    dataframe.loc[:, RESULT_COLUMNS].to_csv(
        target,
        index=False,
        encoding="utf-8-sig",
        float_format="%.9g",
    )
    return target


def export_operating_map_csv(
    result: OperatingMapResult, path: str | Path
) -> Path:
    target = Path(path)
    export_frame = result.dataframe.loc[:, MAP_RESULT_COLUMNS].copy()
    export_frame.insert(0, "CalculationProfile", result.profile)
    export_frame.insert(1, "AlgorithmVersion", result.algorithm_version)
    export_frame.insert(2, "IronLossIsEstimate", True)
    export_frame.to_csv(
        target,
        index=False,
        encoding="utf-8-sig",
        float_format="%.9g",
    )
    return target


def export_operating_map_npz(
    result: OperatingMapResult, path: str | Path
) -> Path:
    target = Path(path)
    np.savez_compressed(
        target,
        SpeedGrid=result.matrix("Speed_rpm"),
        TorqueGrid=result.matrix("TorqueActual_Nm"),
        TorqueRequestGrid=result.matrix("TorqueRequest_Nm"),
        TorqueRatioGrid=result.matrix("TorqueRatio"),
        TorqueAxis_Nm=result.torque_axis_nm,
        TorqueCoordinateMode=np.array(result.torque_coordinate_mode),
        IdMap=result.matrix("Id_A"),
        IqMap=result.matrix("Iq_A"),
        EfficiencyMap=result.matrix("Efficiency"),
        CopperLossMap=result.matrix("CopperLoss_kW"),
        IronLossMap=result.matrix("IronLoss_kW"),
        TotalMotorLossMap=result.matrix("TotalMotorLoss_kW"),
        CurrentMagnitudeMap=result.matrix("Is_A"),
        VoltageUtilizationMap=result.matrix("VoltageUtilization"),
        CurrentUtilizationMap=result.matrix("CurrentUtilization"),
        FeasibleMask=result.matrix("IsFeasible").astype(bool),
        OperatingRegionMap=result.matrix("ControlRegion").astype(str),
        CalculationProfile=np.array(result.profile),
        AlgorithmVersion=np.array(result.algorithm_version),
    )
    return target


def export_analysis_excel(
    parameters: MotorParameters,
    loss_parameters: LossModelParameters,
    map_settings: MapCalculationSettings,
    result: OperatingMapResult,
    path: str | Path,
    *,
    characteristic_input: CharacteristicInput | None = None,
    resolved_limits: ResolvedCharacteristicLimits | None = None,
) -> Path:
    target = Path(path)
    parameter_rows = []
    for section, values in (
        ("Motor/Inverter", parameters.as_input_dict()),
        ("LossEstimate", loss_parameters.as_dict()),
        ("Map", map_settings.as_dict()),
    ):
        for name, value in values.items():
            parameter_rows.append(
                {"Section": section, "Parameter": name, "Value": value}
            )
    parameter_rows.extend(
        [
            {"Section": "Result", "Parameter": "profile", "Value": result.profile},
            {
                "Section": "Result",
                "Parameter": "algorithm_version",
                "Value": result.algorithm_version,
            },
            {
                "Section": "Disclaimer",
                "Parameter": "efficiency_scope",
                "Value": "电机效率估算（铜耗+铁耗）；不含逆变器、机械及杂散损耗。",
            },
            {
                "Section": "Disclaimer",
                "Parameter": "iron_loss",
                "Value": "铁耗为全电机经验模型估算，系数需实测标定。",
            },
        ]
    )
    if characteristic_input is not None:
        for name, value in characteristic_input.as_dict().items():
            parameter_rows.append(
                {
                    "Section": "CharacteristicInput",
                    "Parameter": name,
                    "Value": value,
                }
            )
    if resolved_limits is not None:
        for name in resolved_limits.__dataclass_fields__:
            value = getattr(resolved_limits, name)
            if hasattr(value, "value"):
                value = value.value
            parameter_rows.append(
                {
                    "Section": "ResolvedLimits",
                    "Parameter": name,
                    "Value": value,
                }
            )

    def matrix_frame(column: str) -> pd.DataFrame:
        if result.torque_coordinate_mode == "actual":
            headings = [
                f"Torque_{torque:.6g}_Nm"
                for torque in result.torque_axis_nm
            ]
        else:
            headings = [
                f"TorqueRatio_{ratio:.6g}"
                for ratio in result.torque_ratio_grid
            ]
        frame = pd.DataFrame(result.matrix(column), columns=headings)
        frame.insert(0, "Speed_rpm", result.speed_grid_rpm)
        return frame

    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        pd.DataFrame(parameter_rows).to_excel(
            writer, sheet_name="Parameters", index=False
        )
        result.external_characteristic.to_excel(
            writer, sheet_name="ExternalCharacteristic", index=False
        )
        result.dataframe.to_excel(
            writer, sheet_name="InternalOperatingPoints", index=False
        )
        matrix_frame("Efficiency").to_excel(
            writer, sheet_name="EfficiencyMap", index=False
        )
        matrix_frame("CopperLoss_kW").to_excel(
            writer, sheet_name="CopperLossMap", index=False
        )
        matrix_frame("IronLoss_kW").to_excel(
            writer, sheet_name="IronLossMap", index=False
        )
    return target
