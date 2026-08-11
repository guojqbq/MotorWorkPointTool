import os
from dataclasses import replace

import pytest

from calculation.envelope_solver import SolverSettings
from models.motor_parameters import MotorParameters


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover - GUI dependency is optional for calc-only CI
    QEvent = None
    QApplication = None

_QT_APPLICATION = (
    QApplication.instance() or QApplication([])
    if QApplication is not None
    else None
)


@pytest.fixture(scope="session", autouse=True)
def qt_application_session():
    """Keep one QApplication alive, matching the real desktop process."""

    yield _QT_APPLICATION
    if _QT_APPLICATION is not None:
        _QT_APPLICATION.processEvents()


@pytest.fixture(autouse=True)
def flush_qt_deferred_deletes():
    """Release pyqtgraph scenes before the next GUI regression test."""

    yield
    if _QT_APPLICATION is not None:
        _QT_APPLICATION.sendPostedEvents(
            None, QEvent.Type.DeferredDelete
        )
        _QT_APPLICATION.processEvents()


@pytest.fixture
def fast_settings() -> SolverSettings:
    return SolverSettings(coarse_id_points=401, fine_id_points=201)


@pytest.fixture
def spmsm_parameters() -> MotorParameters:
    return replace(
        MotorParameters.example_spmsm(),
        speed_points=31,
        pmax_kw=None,
    )


@pytest.fixture
def ipmsm_parameters() -> MotorParameters:
    return replace(
        MotorParameters.example_ipmsm(),
        speed_points=31,
        pmax_kw=None,
    )
