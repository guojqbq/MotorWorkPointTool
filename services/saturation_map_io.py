"""Import Ld/Lq Id-by-Iq saturation tables from CSV or Excel."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from models.saturation_map import InductanceSaturationMap


UNIT_TO_HENRY = {
    "H": 1.0,
    "mH": 1e-3,
    "uH": 1e-6,
    "μH": 1e-6,
    "µH": 1e-6,
}


def _read_frame(path: Path, sheet_name: str | int = 0) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, header=None, encoding="utf-8-sig")
    if suffix in {".xlsx", ".xlsm"}:
        return pd.read_excel(path, header=None, sheet_name=sheet_name)
    raise ValueError("饱和电感表仅支持 CSV、XLSX 或 XLSM。")


def _frame_to_map(
    frame: pd.DataFrame,
    *,
    unit: str,
    source_name: str,
) -> InductanceSaturationMap:
    cleaned = frame.dropna(axis=0, how="all").dropna(axis=1, how="all")
    if cleaned.shape[0] < 3 or cleaned.shape[1] < 3:
        raise ValueError("表格至少需要 2 个 Id 点和 2 个 Iq 点。")
    ids = pd.to_numeric(cleaned.iloc[1:, 0], errors="coerce").to_numpy(float)
    iqs = pd.to_numeric(cleaned.iloc[0, 1:], errors="coerce").to_numpy(float)
    values = cleaned.iloc[1:, 1:].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    if not np.all(np.isfinite(ids)):
        raise ValueError("首列（第 2 行起）必须全部是有限的 Id[A] 数值。")
    if not np.all(np.isfinite(iqs)):
        raise ValueError("首行（第 2 列起）必须全部是有限的 Iq[A] 数值。")
    if not np.all(np.isfinite(values)):
        raise ValueError("电感数据区域存在空值或非数值单元格。")
    try:
        factor = UNIT_TO_HENRY[unit]
    except KeyError as exc:
        raise ValueError(f"未知电感单位：{unit}") from exc
    return InductanceSaturationMap.from_arrays(
        ids,
        iqs,
        values * factor,
        source_name=source_name,
    )


def load_inductance_map(
    path: str | Path,
    *,
    unit: str = "μH",
    sheet_name: str | int = 0,
) -> InductanceSaturationMap:
    source = Path(path)
    return _frame_to_map(
        _read_frame(source, sheet_name),
        unit=unit,
        source_name=(
            f"{source.name}:{sheet_name}"
            if source.suffix.lower() != ".csv"
            else source.name
        ),
    )


def load_ld_lq_workbook(
    path: str | Path, *, unit: str = "μH"
) -> tuple[InductanceSaturationMap, InductanceSaturationMap]:
    source = Path(path)
    if source.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError("同时导入 Ld/Lq 需要包含 Ld、Lq 工作表的 Excel 文件。")
    workbook = pd.ExcelFile(source)
    normalized = {name.strip().lower(): name for name in workbook.sheet_names}
    ld_sheet = normalized.get("ld")
    lq_sheet = normalized.get("lq")
    if ld_sheet is None or lq_sheet is None:
        raise ValueError("Excel 必须包含名为 Ld 和 Lq 的两个工作表。")
    ld_map = load_inductance_map(source, unit=unit, sheet_name=ld_sheet)
    lq_map = load_inductance_map(source, unit=unit, sheet_name=lq_sheet)
    if (
        ld_map.id_axis_a != lq_map.id_axis_a
        or ld_map.iq_axis_a != lq_map.iq_axis_a
    ):
        raise ValueError("Ld 与 Lq 工作表的 Id/Iq 网格必须完全一致。")
    return ld_map, lq_map
