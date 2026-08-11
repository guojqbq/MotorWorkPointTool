"""Build plot-ready dq references from values already solved in the map layer."""

from __future__ import annotations

import numpy as np
import pandas as pd

from calculation.equations import dq_voltage, electromagnetic_torque
from calculation.reference_trajectories import REFERENCE_COLUMNS
from models.motor_parameters import MotorParameters
from models.operating_map import OperatingMapResult


def _reference_frame(
    parameters: MotorParameters,
    *,
    kind: str,
    speed_rpm: np.ndarray,
    id_a: np.ndarray,
    iq_a: np.ndarray,
) -> pd.DataFrame:
    speed, ids, iqs = np.broadcast_arrays(
        np.asarray(speed_rpm, dtype=float),
        np.asarray(id_a, dtype=float),
        np.asarray(iq_a, dtype=float),
    )
    finite = np.isfinite(ids) & np.isfinite(iqs)
    speed_for_voltage = np.where(np.isfinite(speed), speed, 0.0)
    torque = electromagnetic_torque(ids, iqs, parameters)
    ud_v, uq_v = dq_voltage(ids, iqs, speed_for_voltage, parameters)
    current = np.hypot(ids, iqs)
    voltage = np.hypot(ud_v, uq_v)
    frame = pd.DataFrame(
        {
            "Kind": kind,
            "Speed_rpm": speed if kind == "MTPV" else np.nan,
            "Torque_Nm": torque,
            "Id_A": ids,
            "Iq_A": iqs,
            "Is_A": current,
            "Us_V": voltage if kind == "MTPV" else np.nan,
        },
        columns=REFERENCE_COLUMNS,
    )
    return frame.loc[finite].reset_index(drop=True)


def build_mtpa_trajectory_from_map(
    parameters: MotorParameters, result: OperatingMapResult
) -> pd.DataFrame:
    """Return one full MTPA row already solved by OperatingMapSolver."""

    frame = result.dataframe
    required = {"MTPAReferenceId_A", "MTPAReferenceIq_A", "SpeedIndex"}
    if not required.issubset(frame.columns):
        return pd.DataFrame(columns=REFERENCE_COLUMNS)
    rows = frame.loc[frame["SpeedIndex"].astype(int) == 0].copy()
    rows = rows.sort_values("TorqueRequest_Nm", kind="stable")
    reference = _reference_frame(
        parameters,
        kind="MTPA",
        speed_rpm=np.full(len(rows), np.nan),
        id_a=rows["MTPAReferenceId_A"].to_numpy(dtype=float),
        iq_a=rows["MTPAReferenceIq_A"].to_numpy(dtype=float),
    )
    return reference.drop_duplicates(
        subset=["Id_A", "Iq_A"], keep="first"
    ).reset_index(drop=True)


def build_mtpv_envelope_from_external(
    parameters: MotorParameters, external: pd.DataFrame
) -> pd.DataFrame:
    """Reuse MTPV points already computed for every external-envelope point."""

    required = {"MTPVReferenceId_A", "MTPVReferenceIq_A", "Speed_rpm"}
    if not required.issubset(external.columns):
        return pd.DataFrame(columns=REFERENCE_COLUMNS)
    valid = external.dropna(
        subset=["Speed_rpm", "MTPVReferenceId_A", "MTPVReferenceIq_A"]
    )
    if valid.empty:
        return pd.DataFrame(columns=REFERENCE_COLUMNS)
    if "VoltageConstraintActive" in valid.columns:
        high_speed = valid[valid["VoltageConstraintActive"].astype(bool)]
    else:
        high_speed = valid
    if len(high_speed) < 4:
        count = max(4, len(valid) // 3)
        high_speed = valid.tail(min(count, len(valid)))
    return _reference_frame(
        parameters,
        kind="MTPV",
        speed_rpm=high_speed["Speed_rpm"].to_numpy(dtype=float),
        id_a=high_speed["MTPVReferenceId_A"].to_numpy(dtype=float),
        iq_a=high_speed["MTPVReferenceIq_A"].to_numpy(dtype=float),
    )


def build_local_mtpv_trajectory_from_map(
    parameters: MotorParameters,
    result: OperatingMapResult,
    speed_rpm: float,
) -> pd.DataFrame:
    """Extract the selected-speed MTPV locus without running another search."""

    frame = result.dataframe
    required = {"MTPVReferenceId_A", "MTPVReferenceIq_A", "SpeedIndex"}
    if not required.issubset(frame.columns) or result.speed_grid_rpm.size == 0:
        return pd.DataFrame(columns=REFERENCE_COLUMNS)
    speed_index = int(
        np.argmin(np.abs(result.speed_grid_rpm - float(speed_rpm)))
    )
    rows = frame.loc[frame["SpeedIndex"].astype(int) == speed_index].copy()
    rows = rows.sort_values("TorqueRequest_Nm", kind="stable")
    reference = _reference_frame(
        parameters,
        kind="MTPV",
        speed_rpm=np.full(len(rows), result.speed_grid_rpm[speed_index]),
        id_a=rows["MTPVReferenceId_A"].to_numpy(dtype=float),
        iq_a=rows["MTPVReferenceIq_A"].to_numpy(dtype=float),
    )
    return reference.drop_duplicates(
        subset=["Id_A", "Iq_A"], keep="first"
    ).reset_index(drop=True)
