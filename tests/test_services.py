import json

from calculation.envelope_solver import EnvelopeSolver
from models.motor_parameters import MotorParameters
from models.operating_point import RESULT_COLUMNS
from services.export_service import export_operating_points_csv
from services.export_service import (
    export_analysis_excel,
    export_operating_map_csv,
    export_operating_map_npz,
)
from services.project_io import (
    PROJECT_FORMAT,
    PROJECT_VERSION,
    load_parameters,
    load_project,
    save_parameters,
    save_project,
)
from calculation.operating_map_solver import OperatingMapSolver
from models.loss_model_parameters import LossModelParameters
from models.map_calculation_settings import MapCalculationSettings
import numpy as np
import pandas as pd


def test_parameter_json_round_trip(tmp_path):
    original = MotorParameters.example_ipmsm()
    path = tmp_path / "motor.json"
    save_parameters(original, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format"] == PROJECT_FORMAT
    assert payload["version"] == PROJECT_VERSION
    assert payload["units"]["Ld_mH"] == "mH"
    assert load_parameters(path) == original


def test_csv_export_has_required_columns_and_excel_bom(
    ipmsm_parameters, fast_settings, tmp_path
):
    dataframe = EnvelopeSolver(ipmsm_parameters, fast_settings).solve()
    path = tmp_path / "points.csv"
    export_operating_points_csv(dataframe, path)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    header = path.read_text(encoding="utf-8-sig").splitlines()[0].split(",")
    assert header == RESULT_COLUMNS


def test_v1_project_round_trip_and_old_file_defaults(tmp_path):
    motor = MotorParameters.example_ipmsm()
    losses = LossModelParameters(
        iron_loss_enabled=True, kh=2.0, model_name="calibrated"
    )
    settings = MapCalculationSettings(
        preview_speed_points=7, preview_torque_points=9
    )
    path = tmp_path / "analysis.json"
    save_project(motor, losses, settings, path)
    assert load_project(path) == (motor, losses, settings)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["version"] = "1.0"
    payload.pop("loss_model")
    payload.pop("map_settings")
    old_path = tmp_path / "old_v1.json"
    old_path.write_text(json.dumps(payload), encoding="utf-8")
    loaded_motor, loaded_losses, loaded_settings = load_project(old_path)
    assert loaded_motor == motor
    assert loaded_losses == LossModelParameters()
    assert loaded_settings == MapCalculationSettings()


def test_internal_map_csv_npz_and_excel_exports(tmp_path):
    motor = MotorParameters.example_ipmsm()
    losses = LossModelParameters()
    settings = MapCalculationSettings(
        preview_speed_points=5,
        preview_torque_points=6,
        full_speed_points=7,
        full_torque_points=8,
    )
    result = OperatingMapSolver(motor, losses, settings).solve("preview")

    csv_path = export_operating_map_csv(result, tmp_path / "map.csv")
    assert csv_path.read_bytes().startswith(b"\xef\xbb\xbf")
    csv_frame = pd.read_csv(csv_path)
    assert len(csv_frame) == 30
    assert set(csv_frame["CalculationProfile"]) == {"preview"}
    assert csv_frame["IronLossIsEstimate"].all()

    npz_path = export_operating_map_npz(result, tmp_path / "map.npz")
    with np.load(npz_path) as archive:
        assert archive["SpeedGrid"].shape == (5, 6)
        assert archive["TorqueGrid"].shape == (5, 6)
        assert archive["FeasibleMask"].dtype == bool
        assert str(archive["CalculationProfile"]) == "preview"

    excel_path = export_analysis_excel(
        motor, losses, settings, result, tmp_path / "analysis.xlsx"
    )
    workbook = pd.ExcelFile(excel_path)
    assert set(workbook.sheet_names) == {
        "Parameters",
        "ExternalCharacteristic",
        "InternalOperatingPoints",
        "EfficiencyMap",
        "CopperLossMap",
        "IronLossMap",
    }
