from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.main_window import MainWindow
from ui.numeric_inputs import NoWheelDoubleSpinBox, NoWheelSpinBox


def _wheel_event(delta: int = 120) -> QWheelEvent:
    return QWheelEvent(
        QPointF(8.0, 8.0),
        QPointF(8.0, 8.0),
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )


def test_numeric_inputs_ignore_wheel_and_hide_step_buttons():
    app = QApplication.instance() or QApplication([])
    for editor in (NoWheelSpinBox(), NoWheelDoubleSpinBox()):
        editor.setRange(0, 1000)
        editor.setValue(100)
        QApplication.sendEvent(editor, _wheel_event())
        assert editor.value() == 100
        assert (
            editor.buttonSymbols()
            == QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        editor.close()
    app.processEvents()


def test_numeric_inputs_accept_keyboard_and_tab_navigation():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    layout = QVBoxLayout(host)
    first = NoWheelSpinBox()
    second = NoWheelDoubleSpinBox()
    first.setRange(0, 1000)
    second.setRange(0.0, 1000.0)
    layout.addWidget(first)
    layout.addWidget(second)
    QWidget.setTabOrder(first, second)
    host.show()
    host.activateWindow()
    app.processEvents()
    first.setFocus()
    first.selectAll()
    QTest.keyClicks(first, "321")
    QTest.keyClick(first, Qt.Key.Key_Enter)
    assert first.value() == 321
    QTest.keyClick(first, Qt.Key.Key_Tab)
    assert second.hasFocus() or second.lineEdit().hasFocus()
    host.close()
    app.processEvents()


def test_scroll_area_still_scrolls_with_keyboard_only_editors():
    app = QApplication.instance() or QApplication([])
    scroll = QScrollArea()
    scroll.resize(240, 180)
    content = QWidget()
    layout = QVBoxLayout(content)
    editor = NoWheelDoubleSpinBox()
    editor.setRange(0.0, 1000.0)
    editor.setValue(844.0)
    layout.addWidget(editor)
    for index in range(40):
        layout.addWidget(QLabel(f"row {index}"))
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    scroll.show()
    app.processEvents()
    bar = scroll.verticalScrollBar()
    assert bar.maximum() > 0
    before = bar.value()
    QApplication.sendEvent(scroll.viewport(), _wheel_event(-120))
    app.processEvents()
    assert bar.value() > before
    assert editor.value() == 844.0
    scroll.close()


def test_top_action_bar_is_fixed_above_main_splitter_and_reports_stale():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(auto_calculate=False)
    window.resize(1500, 900)
    window.show()
    app.processEvents()
    assert window.top_action_bar is window.parameter_panel.fixed_calculation_area
    assert window.top_action_bar.geometry().top() == 0
    assert window.main_splitter.geometry().top() >= window.top_action_bar.height()
    window._parameters_changed()
    assert "结果已过期" in window.parameter_panel.calculation_stage_label.text()
    window.close()


def test_application_entry_uses_qt_maximize_mechanism():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(
        encoding="utf-8"
    )
    assert "window.showMaximized()" in source
    assert "setGeometry(" not in source
