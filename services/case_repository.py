"""Persistent result cases and non-mutating comparison helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any

import numpy as np
import pandas as pd

from models.analysis_result import AnalysisResult
from models.characteristic_input import CharacteristicInput
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings
from models.motor_parameters import MotorParameters


CASE_FORMAT = "PMSMPerformanceToolCase"
CASE_VERSION = "1.0"


def default_cases_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "cases"
    return Path(__file__).resolve().parents[1] / "cases"


@dataclass(frozen=True, slots=True)
class SavedCase:
    name: str
    created_at: str
    note: str
    metadata: dict[str, Any]
    external: pd.DataFrame
    operating_points: pd.DataFrame

    @property
    def legend_label(self) -> str:
        motor = self.metadata.get("motor_parameters", {})
        return (
            f"{self.name} | {motor.get('winding_connection', 'STAR')} | "
            f"{motor.get('inductance_model', 'CONSTANT')}"
        )

    def efficiency_matrix(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        frame = self.operating_points
        speeds = np.sort(frame["Speed_rpm"].dropna().unique().astype(float))
        torques = np.sort(frame["TorqueRequest_Nm"].dropna().unique().astype(float))
        matrix = np.full((speeds.size, torques.size), np.nan)
        speed_lookup = {value: index for index, value in enumerate(speeds)}
        torque_lookup = {value: index for index, value in enumerate(torques)}
        for row in frame.itertuples(index=False):
            speed = float(getattr(row, "Speed_rpm"))
            torque = float(getattr(row, "TorqueRequest_Nm"))
            value = float(getattr(row, "Efficiency"))
            if np.isfinite(value):
                matrix[speed_lookup[speed], torque_lookup[torque]] = value
        return speeds, torques, matrix


def _map_hash(parameters: MotorParameters) -> str | None:
    if parameters.ld_saturation_map is None or parameters.lq_saturation_map is None:
        return None
    payload = {
        "ld": parameters.ld_saturation_map.as_dict(),
        "lq": parameters.lq_saturation_map.as_dict(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_case_name(name: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", name.strip()).strip(" .")
    if not cleaned:
        raise ValueError("案例名称不能为空。")
    if len(cleaned) > 80:
        cleaned = cleaned[:80].rstrip()
    return cleaned


def _write_npz(frame: pd.DataFrame, path: Path) -> None:
    arrays: dict[str, np.ndarray] = {
        "__columns__": np.asarray(frame.columns, dtype=str)
    }
    for column in frame.columns:
        series = frame[column]
        if pd.api.types.is_bool_dtype(series.dtype):
            arrays[column] = series.to_numpy(dtype=bool)
        elif pd.api.types.is_numeric_dtype(series.dtype):
            arrays[column] = series.to_numpy(dtype=float)
        else:
            arrays[column] = series.fillna("").astype(str).to_numpy(dtype=str)
    np.savez_compressed(path, **arrays)


def _read_npz(path: Path) -> pd.DataFrame:
    with np.load(path, allow_pickle=False) as archive:
        columns = [str(value) for value in archive["__columns__"]]
        return pd.DataFrame({column: archive[column] for column in columns})


class CaseRepository:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def list_cases(self) -> list[str]:
        return sorted(
            path.name
            for path in self.root.iterdir()
            if path.is_dir() and (path / "case.json").is_file()
        )

    def save(
        self,
        name: str,
        note: str,
        parameters: MotorParameters,
        characteristic_input: CharacteristicInput,
        losses: LossModelParameters,
        settings: MapCalculationSettings,
        result: AnalysisResult,
    ) -> Path:
        case_name = _safe_case_name(name)
        target = self.root / case_name
        target.mkdir(parents=True, exist_ok=True)
        created = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        resolved = result.resolved_limits
        metadata = {
            "format": CASE_FORMAT,
            "version": CASE_VERSION,
            "name": case_name,
            "created_at": created,
            "note": str(note),
            "motor_parameters": parameters.as_input_dict(),
            "inductance_map_sha256": _map_hash(parameters),
            "characteristic_input": characteristic_input.as_dict(),
            "loss_model": losses.as_dict(),
            "map_settings": settings.as_dict(),
            "resolved_limits": asdict(resolved) if resolved is not None else None,
            "profile": result.profile,
            "algorithm_version": result.operating_map.algorithm_version,
        }
        (target / "case.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        result.external_characteristic.to_csv(
            target / "external.csv", index=False, encoding="utf-8-sig"
        )
        _write_npz(result.operating_map.dataframe, target / "operating_points.npz")
        return target

    def load(self, name: str) -> SavedCase:
        case_name = _safe_case_name(name)
        source = self.root / case_name
        metadata = json.loads((source / "case.json").read_text(encoding="utf-8-sig"))
        if metadata.get("format") != CASE_FORMAT:
            raise ValueError("不是受支持的 PMSM 案例目录。")
        return SavedCase(
            name=str(metadata.get("name", case_name)),
            created_at=str(metadata.get("created_at", "")),
            note=str(metadata.get("note", "")),
            metadata=metadata,
            external=pd.read_csv(source / "external.csv", encoding="utf-8-sig"),
            operating_points=_read_npz(source / "operating_points.npz"),
        )

    def delete(self, name: str) -> None:
        case_name = _safe_case_name(name)
        target = (self.root / case_name).resolve()
        root = self.root.resolve()
        if target.parent != root:
            raise ValueError("案例删除目标超出 cases 目录。")
        if target.exists():
            shutil.rmtree(target)


def compare_case_points(case_a: SavedCase, case_b: SavedCase) -> pd.DataFrame:
    """Return common-grid deltas without modifying either source frame."""

    keys = ["Speed_rpm", "TorqueRequest_Nm"]
    left = case_a.operating_points.loc[
        :, keys + ["TorqueActual_Nm", "Efficiency"]
    ].copy()
    right = case_b.operating_points.loc[
        :, keys + ["TorqueActual_Nm", "Efficiency"]
    ].copy()
    merged = left.merge(right, on=keys, suffixes=("_A", "_B"), how="inner")
    merged["DeltaTorque_Nm"] = (
        merged["TorqueActual_Nm_A"] - merged["TorqueActual_Nm_B"]
    )
    merged["DeltaEfficiency"] = (
        merged["Efficiency_A"] - merged["Efficiency_B"]
    )
    return merged
