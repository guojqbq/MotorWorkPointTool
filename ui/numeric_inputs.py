"""Keyboard-only numeric editors that let wheel events reach the page."""

from __future__ import annotations

from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractSpinBox, QDoubleSpinBox, QSpinBox


class _NoWheelMixin:
    def _configure_numeric_input(self) -> None:
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setKeyboardTracking(False)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt API
        # Ignoring, rather than accepting, propagates the event to the parent
        # scroll area. Hovering an editor therefore scrolls the page without
        # mutating the parameter value.
        event.ignore()


class NoWheelSpinBox(_NoWheelMixin, QSpinBox):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._configure_numeric_input()


class NoWheelDoubleSpinBox(_NoWheelMixin, QDoubleSpinBox):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._configure_numeric_input()
