"""Import and export Ld/Lq Id-by-Iq saturation tables."""

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
    try:
        if suffix == ".csv":
            return pd.read_csv(path, header=None, encoding="utf-8-sig")
        if suffix in {".xlsx", ".xlsm"}:
            return pd.read_excel(path, header=None, sheet_name=sheet_name)
    except PermissionError as exc:
        raise ValueError(f"无法读取文件，文件可能正被占用：{path.name}") from exc
    except Exception as exc:
        raise ValueError(
            f"无法读取 {path.name} 的工作表 {sheet_name!s}：{exc}"
        ) from exc
    raise ValueError("饱和电感表仅支持 CSV、XLSX 或 XLSM。")


def _frame_to_map(
    frame: pd.DataFrame,
    *,
    unit: str,
    source_name: str,
) -> InductanceSaturationMap:
    cleaned = frame.dropna(axis=0, how="all").dropna(axis=1, how="all")
    if cleaned.shape[0] < 3 or cleaned.shape[1] < 3:
        raise ValueError(
            f"工作表 {source_name} 至少需要2个Id点和2个Iq点。"
        )
    raw_ids = cleaned.iloc[1:, 0]
    raw_iqs = cleaned.iloc[0, 1:]
    raw_values = cleaned.iloc[1:, 1:]
    if raw_ids.isna().any() or raw_iqs.isna().any() or raw_values.isna().any().any():
        raise ValueError(f"工作表 {source_name} 发现空白单元格。")
    ids = pd.to_numeric(raw_ids, errors="coerce").to_numpy(float)
    iqs = pd.to_numeric(raw_iqs, errors="coerce").to_numpy(float)
    values = raw_values.apply(pd.to_numeric, errors="coerce").to_numpy(float)
    if not np.all(np.isfinite(ids)):
        raise ValueError(
            f"工作表 {source_name} 第一列必须全部为有限的Id(A)数值。"
        )
    if not np.all(np.isfinite(iqs)):
        raise ValueError(
            f"工作表 {source_name} 第一行必须全部为有限的Iq(A)数值。"
        )
    if not np.all(np.isfinite(values)):
        raise ValueError(
            f"工作表 {source_name} 的电感矩阵存在非数值单元格。"
        )
    try:
        factor = UNIT_TO_HENRY[unit]
    except KeyError as exc:
        raise ValueError(f"未知电感导入单位：{unit}") from exc
    try:
        return InductanceSaturationMap.from_arrays(
            ids,
            iqs,
            values * factor,
            source_name=source_name,
        )
    except ValueError as exc:
        raise ValueError(f"工作表 {source_name} 的网格无效：{exc}") from exc


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
        raise ValueError(
            "同时导入Ld/Lq需要包含Ld、Lq工作表的Excel文件。"
        )
    try:
        workbook = pd.ExcelFile(source)
    except PermissionError as exc:
        raise ValueError(f"无法读取文件，文件可能正被占用：{source.name}") from exc
    except Exception as exc:
        raise ValueError(f"无法打开Excel文件 {source.name}：{exc}") from exc
    normalized = {name.strip().lower(): name for name in workbook.sheet_names}
    missing = [name for name in ("Ld", "Lq") if name.lower() not in normalized]
    if missing:
        raise ValueError("未找到Sheet: " + "、".join(missing))
    ld_sheet = normalized["ld"]
    lq_sheet = normalized["lq"]
    ld_map = load_inductance_map(source, unit=unit, sheet_name=ld_sheet)
    lq_map = load_inductance_map(source, unit=unit, sheet_name=lq_sheet)
    if (
        ld_map.id_axis_a != lq_map.id_axis_a
        or ld_map.iq_axis_a != lq_map.iq_axis_a
    ):
        raise ValueError("Ld与Lq的Id/Iq轴不一致。")
    return ld_map, lq_map


def write_ld_lq_template(path: str | Path) -> Path:
    """Create an editable two-sheet μH template with blank value cells."""

    target = Path(path)
    if target.suffix.lower() != ".xlsx":
        target = target.with_suffix(".xlsx")
    ids = [0.0, -55.1, -110.2, -165.3]
    iqs = [0.0, 55.1, 110.2, 165.3]
    matrix = [["Id/Iq [A]", *iqs]]
    matrix.extend([[id_a, *([None] * len(iqs))] for id_a in ids])
    frame = pd.DataFrame(matrix)
    try:
        with pd.ExcelWriter(target, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name="Ld", header=False, index=False)
            frame.to_excel(writer, sheet_name="Lq", header=False, index=False)
            for sheet in ("Ld", "Lq"):
                worksheet = writer.book[sheet]
                worksheet.freeze_panes = "B2"
                worksheet["A1"] = "Id/Iq [A]（电感单位：μH）"
                worksheet.column_dimensions["A"].width = 28
                for column in "BCDE":
                    worksheet.column_dimensions[column].width = 14
    except PermissionError as exc:
        raise ValueError(f"无法写入模板，文件可能正被占用：{target.name}") from exc
    except Exception as exc:
        raise ValueError(f"Excel模板生成失败：{exc}") from exc
    return target
