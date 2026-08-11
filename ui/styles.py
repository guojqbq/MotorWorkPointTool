"""Application stylesheet."""

APP_STYLESHEET = """
QMainWindow, QWidget {
    background: #f7f9fc;
    color: #1d2939;
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 10pt;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #dfe5ee;
    border-radius: 7px;
    margin-top: 12px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #344054;
}
QLabel[role="panelTitle"] {
    font-size: 18pt;
    font-weight: 700;
    color: #101828;
}
QLabel[role="cardTitle"] {
    color: #344054;
    font-size: 10.5pt;
    font-weight: 650;
    padding-left: 3px;
}
QFrame[role="plotCard"] {
    background: #ffffff;
    border: 1px solid #d9e0ea;
    border-radius: 7px;
}
QFrame[role="plotCard"] QTabWidget::pane {
    background: #ffffff;
    border: 1px solid #e4e8ef;
    border-radius: 4px;
}
QSplitter::handle {
    background: #e7ebf1;
}
QSplitter::handle:horizontal {
    width: 6px;
}
QSplitter::handle:vertical {
    height: 6px;
}
QLabel[role="muted"], QLabel[role="unit"] {
    color: #667085;
}
QLabel[role="derived"] {
    background: #eef4ff;
    border: 1px solid #c7d7fe;
    border-radius: 6px;
    color: #1849a9;
    padding: 8px;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #cfd6e2;
    border-radius: 5px;
    padding: 7px 9px;
}
QPushButton:hover {
    background: #f2f4f7;
}
QPushButton:disabled {
    color: #98a2b3;
    background: #f2f4f7;
}
QPushButton[role="primary"] {
    background: #1463ff;
    color: white;
    border: 1px solid #1463ff;
    font-weight: 600;
    padding: 9px;
}
QPushButton[role="primary"]:hover {
    background: #004eeb;
}
QToolButton[role="sectionHeader"] {
    background: #eef2f6;
    border: 1px solid #d8dee8;
    border-radius: 5px;
    padding: 6px 8px;
    font-weight: 600;
    text-align: left;
}
QToolButton[role="sectionHeader"]:hover {
    background: #e4eaf2;
}
QToolButton[role="displayMenu"] {
    background: #ffffff;
    border: 1px solid #cfd6e2;
    border-radius: 5px;
    padding: 4px 9px;
    font-weight: 600;
}
QToolButton[role="displayMenu"]:hover {
    background: #f2f4f7;
}
QSpinBox, QDoubleSpinBox, QComboBox {
    background: white;
    border: 1px solid #cfd6e2;
    border-radius: 4px;
    padding: 4px;
    min-height: 23px;
}
QTableView {
    background: white;
    alternate-background-color: #f8fafc;
    border: 1px solid #dfe5ee;
    gridline-color: #eaecf0;
    selection-background-color: #dbe7ff;
    selection-color: #101828;
}
QHeaderView::section {
    background: #eef2f6;
    color: #344054;
    border: none;
    border-right: 1px solid #dfe5ee;
    border-bottom: 1px solid #dfe5ee;
    padding: 6px;
    font-weight: 600;
}
QProgressBar {
    border: 1px solid #d0d5dd;
    border-radius: 4px;
    background: white;
    text-align: center;
}
QProgressBar::chunk {
    background: #1463ff;
    border-radius: 3px;
}
"""
