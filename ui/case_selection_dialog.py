"""Single or multi case-selection dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class CaseSelectionDialog(QDialog):
    def __init__(
        self, names: list[str], *, multiple: bool, title: str, parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(420, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("请选择案例："))
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
            if multiple
            else QListWidget.SelectionMode.SingleSelection
        )
        for name in names:
            self.list_widget.addItem(QListWidgetItem(name))
        layout.addWidget(self.list_widget)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_names(self) -> list[str]:
        return [item.text() for item in self.list_widget.selectedItems()]
