"""Qt table model and view for all speed-sweep work points."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QTableView

from models.operating_point import RESULT_COLUMNS


class OperatingPointTableModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.dataframe = pd.DataFrame(columns=RESULT_COLUMNS)

    def set_dataframe(self, dataframe: pd.DataFrame) -> None:
        self.beginResetModel()
        self.dataframe = dataframe.reset_index(drop=True).copy()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.dataframe)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.dataframe.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.dataframe.iat[index.row(), index.column()]
        column = self.dataframe.columns[index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            if isinstance(value, (bool, np.bool_)):
                return "是" if bool(value) else "否"
            if isinstance(value, str):
                return value
            try:
                number = float(value)
            except (TypeError, ValueError):
                return str(value)
            if not math.isfinite(number):
                return "—"
            if column == "Speed_rpm":
                return f"{number:.1f}"
            if column in {"CurrentUtilization", "VoltageUtilization"}:
                return f"{number * 100.0:.1f}%"
            return f"{number:.3f}"

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in {"Region", "ActiveConstraint"}:
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.BackgroundRole:
            region = str(self.dataframe.iloc[index.row()].get("Region", ""))
            if region == "无可行工作点":
                return QColor("#fff2f0")
            if region == "弱磁":
                return QColor("#f3f7ff")
            if region == "功率限制":
                return QColor("#fff8e8")
        return None

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self.dataframe.columns[section])
        return str(section + 1)


class OperatingPointTable(QTableView):
    pointSelected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.table_model = OperatingPointTableModel(self)
        self.setModel(self.table_model)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(False)
        self.setWordWrap(False)
        self.verticalHeader().setDefaultSectionSize(25)
        self.horizontalHeader().setStretchLastSection(True)
        self.selectionModel().currentRowChanged.connect(self._on_current_row_changed)

    def set_dataframe(self, dataframe: pd.DataFrame) -> None:
        self.table_model.set_dataframe(dataframe)
        self.resizeColumnsToContents()
        for column in range(self.table_model.columnCount()):
            self.setColumnWidth(column, min(max(self.columnWidth(column), 86), 145))

    def select_index(self, row: int) -> None:
        if 0 <= row < self.table_model.rowCount():
            self.selectRow(row)
            model_index = self.table_model.index(row, 0)
            self.scrollTo(
                model_index, QAbstractItemView.ScrollHint.PositionAtCenter
            )

    def _on_current_row_changed(
        self, current: QModelIndex, _previous: QModelIndex
    ) -> None:
        if current.isValid():
            self.pointSelected.emit(current.row())
