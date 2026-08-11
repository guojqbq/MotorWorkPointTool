"""Array-backed result model for a two-dimensional PMSM operating map."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray


MAP_RESULT_COLUMNS = [
    "SpeedIndex",
    "TorqueIndex",
    "TorqueRatio",
    "Speed_rpm",
    "TorqueRequest_Nm",
    "TorqueActual_Nm",
    "Id_A",
    "Iq_A",
    "Ld_uH",
    "Lq_uH",
    "Is_A",
    "Ud_V",
    "Uq_V",
    "Us_V",
    "MechanicalPower_kW",
    "CopperLoss_kW",
    "IronLoss_kW",
    "TotalMotorLoss_kW",
    "Efficiency",
    "CurrentUtilization",
    "VoltageUtilization",
    "Psi_d_Wb",
    "Psi_q_Wb",
    "Psi_s_Wb",
    "ElectricalFrequency_Hz",
    "NearMTPA",
    "NearMTPV",
    "MTPADistance_A",
    "MTPVDistance_A",
    "MTPAReferenceId_A",
    "MTPAReferenceIq_A",
    "MTPVReferenceId_A",
    "MTPVReferenceIq_A",
    "CurrentConstraintActive",
    "VoltageConstraintActive",
    "PowerConstraintActive",
    "ControlRegion",
    "ActiveConstraint",
    "IsFeasible",
    "SolverStatus",
]


@dataclass(frozen=True, slots=True)
class OperatingMapResult:
    profile: str
    speed_grid_rpm: NDArray[np.float64]
    torque_ratio_grid: NDArray[np.float64]
    torque_axis_nm: NDArray[np.float64]
    torque_coordinate_mode: str
    maximum_torque_nm: NDArray[np.float64]
    dataframe: pd.DataFrame
    matrices: dict[str, NDArray]
    external_characteristic: pd.DataFrame
    algorithm_version: str
    calculation_elapsed_seconds: float = 0.0

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.speed_grid_rpm), len(self.torque_axis_nm)

    @property
    def is_preview(self) -> bool:
        return self.profile == "preview"

    def matrix(self, column: str) -> NDArray:
        return self.matrices[column]

    def flat_index(self, speed_index: int, torque_index: int) -> int:
        return speed_index * self.shape[1] + torque_index

    def unravel_index(self, map_index: int) -> tuple[int, int]:
        if not 0 <= int(map_index) < len(self.dataframe):
            raise IndexError(f"内部工作点索引越界：{map_index}")
        speed_index, torque_index = np.unravel_index(int(map_index), self.shape)
        return int(speed_index), int(torque_index)

    def point(self, speed_index: int, torque_index: int) -> pd.Series:
        return self.dataframe.iloc[self.flat_index(speed_index, torque_index)]

    def point_by_map_index(self, map_index: int) -> pd.Series:
        if not 0 <= int(map_index) < len(self.dataframe):
            raise IndexError(f"内部工作点索引越界：{map_index}")
        return self.dataframe.iloc[int(map_index)]

    def feasible_map_indices(self) -> NDArray[np.int64]:
        feasible = self.dataframe["IsFeasible"].to_numpy(dtype=bool)
        finite = np.isfinite(
            self.dataframe["Speed_rpm"].to_numpy(dtype=float)
        ) & np.isfinite(
            self.dataframe["TorqueActual_Nm"].to_numpy(dtype=float)
        )
        return np.flatnonzero(feasible & finite).astype(np.int64)

    def diagnostics(self) -> dict[str, int | str]:
        feasible = self.dataframe["IsFeasible"].to_numpy(dtype=bool)
        torque = self.dataframe["TorqueActual_Nm"].to_numpy(dtype=float)
        request = self.dataframe["TorqueRequest_Nm"].to_numpy(dtype=float)
        speed = self.dataframe["Speed_rpm"].to_numpy(dtype=float)
        ids = self.dataframe["Id_A"].to_numpy(dtype=float)
        iqs = self.dataframe["Iq_A"].to_numpy(dtype=float)
        efficiency = self.dataframe["Efficiency"].to_numpy(dtype=float)
        speed_indices = self.dataframe["SpeedIndex"].to_numpy(dtype=int)
        local_maximum = self.maximum_torque_nm[speed_indices]
        status = self.dataframe["SolverStatus"].astype(str).to_numpy()
        regions = self.dataframe["ControlRegion"].astype(str).to_numpy()
        inside_envelope = (
            np.isfinite(request)
            & np.isfinite(local_maximum)
            & (request <= local_maximum + 1e-9)
        )
        finite_ts = feasible & np.isfinite(speed) & np.isfinite(torque)
        finite_dq = feasible & np.isfinite(ids) & np.isfinite(iqs)
        low_torque = (
            feasible
            & np.isfinite(torque)
            & (local_maximum > 0.0)
            & (torque < 0.1 * local_maximum)
        )
        return {
            "profile": self.profile,
            "speed_points": self.shape[0],
            "torque_points": self.shape[1],
            "total_points": len(self.dataframe),
            "inside_envelope_points": int(np.count_nonzero(inside_envelope)),
            "feasible_points": int(np.count_nonzero(feasible)),
            "nonzero_torque_points": int(
                np.count_nonzero(feasible & np.isfinite(torque) & (torque > 1e-9))
            ),
            "zero_torque_points": int(
                np.count_nonzero(
                    feasible & np.isfinite(torque) & np.isclose(torque, 0.0)
                )
            ),
            "below_10_percent_torque_points": int(np.count_nonzero(low_torque)),
            "solver_failed_points": int(
                np.count_nonzero(np.isin(status, ["Infeasible", "SolverFailed"]))
            ),
            "outside_envelope_points": int(
                np.count_nonzero(status == "OutsideEnvelope")
            ),
            "efficiency_invalid_retained_points": int(
                np.count_nonzero(feasible & ~np.isfinite(efficiency))
            ),
            "removed_by_efficiency_points": 0,
            "removed_by_nonfinite_ts_points": int(
                np.count_nonzero(feasible & ~finite_ts)
            ),
            "removed_by_nonfinite_dq_points": int(
                np.count_nonzero(feasible & ~finite_dq)
            ),
            "points_before_deduplication": len(self.dataframe),
            "points_after_deduplication": len(self.dataframe),
            "mtpa_points": int(np.count_nonzero(feasible & (regions == "MTPA"))),
            "field_weakening_points": int(
                np.count_nonzero(feasible & (regions == "FIELD_WEAKENING"))
            ),
            "mtpv_points": int(np.count_nonzero(feasible & (regions == "MTPV"))),
            "other_points": int(np.count_nonzero(feasible & (regions == "OTHER"))),
            "calculation_elapsed_ms": int(
                round(1000.0 * self.calculation_elapsed_seconds)
            ),
        }

    def nearest_index(
        self, speed_rpm: float, torque_nm: float, *, feasible_only: bool = True
    ) -> tuple[int, int]:
        speed = self.matrix("Speed_rpm")
        torque = self.matrix("TorqueActual_Nm")
        scale_speed = max(float(np.nanmax(self.speed_grid_rpm)), 1.0)
        scale_torque = max(float(np.nanmax(self.maximum_torque_nm)), 1.0)
        distance = ((speed - speed_rpm) / scale_speed) ** 2 + (
            (torque - torque_nm) / scale_torque
        ) ** 2
        if feasible_only:
            distance = np.where(self.matrix("IsFeasible"), distance, np.inf)
        flat = int(np.nanargmin(distance))
        return np.unravel_index(flat, self.shape)


def dataframe_to_matrices(
    dataframe: pd.DataFrame, shape: tuple[int, int]
) -> dict[str, NDArray]:
    matrices: dict[str, NDArray] = {}
    for column in dataframe.columns:
        if column in {"SpeedIndex", "TorqueIndex"}:
            continue
        values = dataframe[column].to_numpy(copy=True)
        matrices[column] = values.reshape(shape)
    return matrices
