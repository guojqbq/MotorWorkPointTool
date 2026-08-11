"""Capture a deterministic offscreen UI preview for release verification."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    if font_path.is_file():
        QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont("Microsoft YaHei UI", 10))
    window = MainWindow(auto_calculate=False)
    window.resize(1600, 960)
    panel = window.parameter_panel
    panel.inductance_model.setCurrentIndex(
        panel.inductance_model.findData("SATURATION_MAP")
    )
    panel.set_calculating(True)
    panel.start_progress()
    panel.update_progress_stage("内部 Map", 6665, 9801)
    panel.update_progress(68)
    panel.update_progress_elapsed(32.5)
    window.show()
    app.processEvents()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(args.output)):
        raise RuntimeError(f"无法保存界面截图：{args.output}")
    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
