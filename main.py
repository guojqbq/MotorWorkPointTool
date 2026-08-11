"""Application entry point."""

from __future__ import annotations

import logging
import sys
import tempfile
import traceback as traceback_module
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from app_version import __version__
from ui.main_window import MainWindow


LOGGER = logging.getLogger(__name__)


def format_exception_details(
    exc_type: type[BaseException],
    exc_value: BaseException,
    traceback_object,
) -> tuple[str, str]:
    """Build concise dialog details plus the complete Python traceback."""

    full_traceback = "".join(
        traceback_module.format_exception(
            exc_type, exc_value, traceback_object
        )
    )
    frames = traceback_module.extract_tb(traceback_object)
    if frames:
        origin = frames[-1]
        filename = origin.filename
        line_number = origin.lineno
    else:
        filename = "<unknown>"
        line_number = 0
    dialog_text = (
        f"异常类型：{exc_type.__name__}\n"
        f"文件名：{filename}\n"
        f"行号：{line_number}\n"
        f"错误信息：{exc_value}\n\n"
        f"完整 Python traceback：\n{full_traceback}"
    )
    return dialog_text, full_traceback


def configure_logging() -> Path:
    """Configure a persistent application log in the user's data directory."""

    log_directory = Path(
        QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
    )
    log_path = log_directory / "pmsm_performance_tool.log"
    try:
        log_directory.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=log_path,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            encoding="utf-8",
        )
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "PMSMPerformanceTool"
        fallback.mkdir(parents=True, exist_ok=True)
        log_path = fallback / "pmsm_performance_tool.log"
        logging.basicConfig(
            filename=log_path,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            encoding="utf-8",
        )
    return log_path


def run_packaged_smoke_test(output_directory: str | Path) -> None:
    """Exercise packaged calculation, plotting, and every export backend."""

    from calculation.characteristic_limit_resolver import (
        resolve_characteristic_limits,
    )
    from calculation.envelope_solver import EnvelopeSolver, SolverSettings
    from calculation.operating_map_solver import OperatingMapSolver
    from models.characteristic_input import CharacteristicInput
    from models.analysis_result import AnalysisResult
    from models.loss_model_parameters import LossModelParameters
    from models.map_calculation_settings import MapCalculationSettings
    from models.motor_parameters import MotorParameters
    from services.export_service import (
        export_analysis_excel,
        export_operating_map_csv,
        export_operating_map_npz,
        export_operating_points_csv,
    )
    from services.case_repository import CaseRepository
    from ui.operating_map_plot import OperatingMapPlot

    target = Path(output_directory)
    target.mkdir(parents=True, exist_ok=True)
    parameters = replace(
        MotorParameters.example_ipmsm(),
        max_speed_rpm=3000.0,
        speed_points=5,
    )
    characteristic = replace(
        CharacteristicInput(), max_speed_rpm=3000.0
    )
    losses = LossModelParameters()
    settings = MapCalculationSettings(
        full_speed_points=5,
        full_torque_points=7,
    )
    limits = resolve_characteristic_limits(parameters, characteristic)
    external = EnvelopeSolver(
        parameters,
        SolverSettings(coarse_id_points=101, fine_id_points=51),
        limits,
    ).solve()
    operating_map = OperatingMapSolver(
        parameters, losses, settings, limits
    ).solve("full")
    export_operating_points_csv(external, target / "external.csv")
    export_operating_map_csv(operating_map, target / "map.csv")
    export_operating_map_npz(operating_map, target / "map.npz")
    export_analysis_excel(
        parameters,
        losses,
        settings,
        operating_map,
        target / "analysis.xlsx",
        characteristic_input=characteristic,
        resolved_limits=limits,
    )
    smoke_result = AnalysisResult(
        calculation_parameters=parameters,
        external_characteristic=external,
        operating_map=operating_map,
        profile="full",
        cache_key="packaged-smoke",
        resolved_limits=limits,
    )
    case_repository = CaseRepository(target / "cases")
    case_repository.save(
        "smoke_case",
        "packaged smoke",
        parameters,
        characteristic,
        losses,
        settings,
        smoke_result,
    )
    loaded_case = case_repository.load("smoke_case")
    if loaded_case.external.empty or loaded_case.operating_points.empty:
        raise RuntimeError("发布包案例保存/加载冒烟测试失败。")
    plot = OperatingMapPlot()
    try:
        plot.set_result(operating_map)
        plot.export_png(str(target / "map.png"))
    finally:
        plot.close()
        plot.deleteLater()
    expected = (
        "external.csv",
        "map.csv",
        "map.npz",
        "analysis.xlsx",
        "map.png",
        "cases/smoke_case/case.json",
        "cases/smoke_case/external.csv",
        "cases/smoke_case/operating_points.npz",
    )
    missing = [
        name
        for name in expected
        if not (target / name).is_file()
        or (target / name).stat().st_size == 0
    ]
    if missing:
        raise RuntimeError(f"发布包冒烟测试缺少输出：{', '.join(missing)}")


def main() -> int:
    QCoreApplication.setOrganizationName("PMSM Tools")
    QCoreApplication.setApplicationName("PMSM Performance Tool")
    QCoreApplication.setApplicationVersion(__version__)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    log_path = configure_logging()
    if "--smoke-test" in sys.argv:
        argument_index = sys.argv.index("--smoke-test")
        output_directory = (
            sys.argv[argument_index + 1]
            if argument_index + 1 < len(sys.argv)
            else Path.cwd() / "packaged_smoke_output"
        )
        try:
            run_packaged_smoke_test(output_directory)
        except Exception:
            LOGGER.exception("Packaged smoke test failed")
            return 1
        return 0

    def show_unhandled_exception(
        exc_type, exc_value, traceback_object
    ) -> None:
        dialog_text, full_traceback = format_exception_details(
            exc_type, exc_value, traceback_object
        )
        LOGGER.critical(
            "Unhandled Python exception (log: %s)\n%s",
            log_path,
            full_traceback,
        )
        sys.__excepthook__(exc_type, exc_value, traceback_object)
        QMessageBox.critical(
            None,
            "未处理错误",
            dialog_text,
        )

    sys.excepthook = show_unhandled_exception
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
