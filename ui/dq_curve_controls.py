"""Compact menu for dq curve and internal-point visibility."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QToolButton


class DqCurveControls(QToolButton):
    """Backward-named compact replacement for the old checkbox panel."""

    curveVisibilityChanged = Signal(str, bool)
    internalPointsVisibilityChanged = Signal(bool)
    currentSpeedHighlightChanged = Signal(bool)
    operatingPointDisplayModeChanged = Signal(str)

    CURVES = [
        ("current_limit", "电流圆"),
        ("voltage_limit", "电压极限"),
        ("mtpa", "MTPA"),
        ("mtpv", "MTPV"),
        ("local_mtpv", "当前转速MTPV"),
        ("constant_torque", "恒转矩曲线"),
        ("optimal", "实际工作轨迹"),
    ]

    DISPLAY_MODES = [
        ("all", "全部内部点"),
        ("current_speed", "当前转速轨迹"),
        ("all_with_speed", "全部点 + 当前转速高亮"),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setText("显示选项")
        self.setProperty("role", "displayMenu")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        self.setMenu(menu)

        self.actions: dict[str, QAction] = {}
        for key, label in self.CURVES:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(
                lambda checked, curve_key=key: (
                    self.curveVisibilityChanged.emit(curve_key, checked)
                )
            )
            self.actions[key] = action

        menu.addSeparator()
        self.internal_points_action = menu.addAction("内部工作点")
        self.internal_points_action.setCheckable(True)
        self.internal_points_action.setChecked(True)
        self.internal_points_action.toggled.connect(
            self.internalPointsVisibilityChanged
        )

        self.current_speed_highlight_action = menu.addAction(
            "当前转速高亮"
        )
        self.current_speed_highlight_action.setCheckable(True)
        self.current_speed_highlight_action.setChecked(True)
        self.current_speed_highlight_action.toggled.connect(
            self.currentSpeedHighlightChanged
        )

        mode_menu = menu.addMenu("内部点显示模式")
        self.display_mode_group = QActionGroup(self)
        self.display_mode_group.setExclusive(True)
        self.display_mode_actions: dict[str, QAction] = {}
        for mode, label in self.DISPLAY_MODES:
            action = mode_menu.addAction(label)
            action.setCheckable(True)
            action.setData(mode)
            self.display_mode_group.addAction(action)
            self.display_mode_actions[mode] = action
            action.toggled.connect(
                lambda checked, selected_mode=mode: (
                    self.operatingPointDisplayModeChanged.emit(selected_mode)
                    if checked
                    else None
                )
            )
        self.display_mode_actions["all_with_speed"].setChecked(True)
