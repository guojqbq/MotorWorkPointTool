"""Modern, compact engineering-application stylesheet."""

APP_STYLESHEET = """
QMainWindow, QWidget {
    background: #F4F6F8;
    color: #172033;
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 10pt;
}
QScrollArea, QScrollArea > QWidget > QWidget {
    background: #F4F6F8;
    border: none;
}
QLabel[role="panelTitle"] {
    font-size: 18pt;
    font-weight: 700;
    color: #172033;
}
QLabel[role="cardTitle"] {
    color: #344054;
    font-size: 10.5pt;
    font-weight: 650;
    padding-left: 3px;
}
QLabel[role="muted"], QLabel[role="unit"] {
    color: #667085;
    background: transparent;
}
QLabel[role="formatHint"] {
    color: #475467;
    background: #F8FAFC;
    border: 1px solid #D8DEE8;
    border-radius: 6px;
    padding: 7px;
}
QLabel[role="formatExample"] {
    color: #172033;
    background: #F8FAFC;
    border: 1px solid #D8DEE8;
    border-radius: 7px;
    padding: 10px;
    font-family: "Cascadia Mono", "Consolas";
}
QLabel[role="derived"] {
    background: #EEF4FF;
    border: 1px solid #C7D7FE;
    border-radius: 7px;
    color: #1849A9;
    padding: 9px;
}
QFrame[role="plotCard"], QFrame[role="progressCard"] {
    background: #FFFFFF;
    border: 1px solid #D8DEE8;
    border-radius: 8px;
}
QFrame[role="progressCard"] {
    border-left: 4px solid #2563EB;
}
QFrame[role="progressCard"][state="completed"] {
    border-left-color: #16A34A;
}
QFrame[role="progressCard"][state="failed"],
QFrame[role="progressCard"][state="cancelled"] {
    border-left-color: #DC2626;
}
QFrame[role="progressCard"] QLabel[role="progressTitle"] {
    background: transparent;
    color: #172033;
    font-weight: 700;
    font-size: 10.5pt;
}
QFrame[role="progressCard"][state="completed"] QLabel[role="progressTitle"] {
    color: #15803D;
}
QFrame[role="progressCard"][state="failed"] QLabel[role="progressTitle"],
QFrame[role="progressCard"][state="cancelled"] QLabel[role="progressTitle"] {
    color: #B42318;
}
QFrame[role="plotCard"] QTabWidget::pane {
    background: #FFFFFF;
    border: 1px solid #E4E8EF;
    border-radius: 5px;
}
QGroupBox {
    background: #FFFFFF;
    border: 1px solid #D8DEE8;
    border-radius: 8px;
    margin-top: 14px;
    padding: 12px 9px 9px 9px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #344054;
}
QToolButton[role="sectionHeader"] {
    background: #FFFFFF;
    color: #172033;
    border: 1px solid #D8DEE8;
    border-radius: 7px;
    min-height: 34px;
    padding: 3px 10px;
    font-weight: 650;
    text-align: left;
}
QToolButton[role="sectionHeader"]:hover {
    background: #F8FAFC;
    border-color: #B8C2D1;
}
QToolButton[role="displayMenu"] {
    background: #FFFFFF;
    border: 1px solid #D0D5DD;
    border-radius: 6px;
    min-height: 28px;
    padding: 2px 10px;
    font-weight: 600;
}
QToolButton[role="displayMenu"]:hover {
    background: #F8FAFC;
    border-color: #98A2B3;
}
QPushButton {
    background: #FFFFFF;
    color: #344054;
    border: 1px solid #D0D5DD;
    border-radius: 7px;
    min-height: 32px;
    padding: 1px 10px;
    font-weight: 500;
}
QPushButton:hover {
    background: #F8FAFC;
    border-color: #98A2B3;
}
QPushButton:pressed {
    background: #EAECF0;
}
QPushButton:disabled {
    color: #98A2B3;
    background: #F2F4F7;
    border-color: #E4E7EC;
}
QPushButton[role="primary"] {
    background: #2563EB;
    color: #FFFFFF;
    border-color: #2563EB;
    min-height: 40px;
    font-size: 10.5pt;
    font-weight: 700;
}
QPushButton[role="primary"]:hover {
    background: #1D4ED8;
    border-color: #1D4ED8;
}
QPushButton[role="primary"]:pressed {
    background: #1E40AF;
}
QPushButton[role="danger"] {
    background: #FFFFFF;
    color: #B42318;
    border-color: #FDA29B;
}
QPushButton[role="danger"]:hover {
    background: #FEF3F2;
    border-color: #F97066;
}
QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {
    background: #FFFFFF;
    color: #172033;
    border: 1px solid #D0D5DD;
    border-radius: 7px;
    min-height: 32px;
    min-width: 128px;
    padding: 0 9px;
    selection-background-color: #DBEAFE;
}
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QLineEdit:focus {
    border: 1px solid #2563EB;
}
QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QLineEdit:disabled {
    color: #98A2B3;
    background: #F2F4F7;
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    width: 18px;
    background: #F8FAFC;
    border-left: 1px solid #E4E7EC;
}
QSpinBox::up-button, QDoubleSpinBox::up-button {
    border-top-right-radius: 6px;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    border-bottom-right-radius: 6px;
}
QComboBox::drop-down {
    width: 25px;
    border: none;
    border-left: 1px solid #E4E7EC;
}
QComboBox QAbstractItemView {
    background: #FFFFFF;
    color: #172033;
    border: 1px solid #D0D5DD;
    selection-background-color: #DBEAFE;
    selection-color: #172033;
    padding: 4px;
}
QCheckBox {
    spacing: 7px;
}
QTabBar::tab {
    background: #EEF2F6;
    color: #475467;
    border: 1px solid #D8DEE8;
    padding: 7px 13px;
}
QTabBar::tab:selected {
    background: #FFFFFF;
    color: #2563EB;
    font-weight: 650;
}
QTableView {
    background: #FFFFFF;
    alternate-background-color: #F8FAFC;
    border: 1px solid #D8DEE8;
    gridline-color: #EAECF0;
    selection-background-color: #DBEAFE;
    selection-color: #172033;
}
QHeaderView::section {
    background: #EEF2F6;
    color: #344054;
    border: none;
    border-right: 1px solid #D8DEE8;
    border-bottom: 1px solid #D8DEE8;
    padding: 7px;
    font-weight: 650;
}
QProgressBar {
    border: 1px solid #C7D7FE;
    border-radius: 7px;
    background: #EEF4FF;
    color: #172033;
    min-height: 20px;
    text-align: center;
    font-weight: 650;
}
QProgressBar::chunk {
    background: #2563EB;
    border-radius: 6px;
}
QFrame[role="progressCard"][state="completed"] QProgressBar::chunk {
    background: #16A34A;
}
QFrame[role="progressCard"][state="failed"] QProgressBar::chunk,
QFrame[role="progressCard"][state="cancelled"] QProgressBar::chunk {
    background: #DC2626;
}
QSplitter::handle {
    background: #E4E7EC;
}
QSplitter::handle:horizontal {
    width: 6px;
}
QSplitter::handle:vertical {
    height: 6px;
}
QStatusBar {
    background: #FFFFFF;
    color: #475467;
    border-top: 1px solid #D8DEE8;
}
"""
