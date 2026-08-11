"""Combined external characteristic and internal operating-map result."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from models.characteristic_summary import CharacteristicSummary
from models.operating_map import OperatingMapResult
from models.motor_parameters import MotorParameters
from models.resolved_characteristic_limits import ResolvedCharacteristicLimits


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    calculation_parameters: MotorParameters
    external_characteristic: pd.DataFrame
    operating_map: OperatingMapResult
    profile: str
    cache_key: str
    resolved_limits: ResolvedCharacteristicLimits | None = None
    characteristic_summary: CharacteristicSummary | None = None
    mtpa_trajectory: pd.DataFrame | None = None
    mtpv_envelope: pd.DataFrame | None = None
