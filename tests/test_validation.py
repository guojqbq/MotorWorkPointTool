import pytest

from models.motor_parameters import MotorParameters, ParameterValidationError


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"pole_pairs": 0}, "极对数"),
        ({"rs_ohm": -0.1}, "定子相电阻"),
        ({"ld_mh": 0.0}, "d轴电感"),
        ({"lq_mh": 0.0}, "q轴电感"),
        ({"flux_pm_wb": 0.0}, "永磁体磁链"),
        ({"udc_v": 0.0}, "直流母线"),
        ({"imax_a": 0.0}, "最大电流"),
        ({"max_speed_rpm": 0.0}, "最大机械转速"),
        ({"speed_points": 1}, "转速点数"),
        ({"id_min_a": 1.0}, "Id_min"),
        ({"pmax_kw": -1.0}, "最大机械功率"),
        ({"voltage_utilization": 1.1}, "电压利用系数"),
        ({"modulation": "BAD"}, "调制方式"),
        ({"current_definition": "line"}, "输入电流定义"),
    ],
)
def test_invalid_parameters_have_clear_chinese_message(changes, message):
    values = MotorParameters.example_ipmsm().as_input_dict()
    key_map = {
        "rs_ohm": "Rs",
        "ld_mh": "Ld_mH",
        "lq_mh": "Lq_mH",
        "flux_pm_wb": "flux_pm",
        "udc_v": "Udc",
        "imax_a": "Imax",
        "id_min_a": "Id_min",
        "pmax_kw": "Pmax_kW",
    }
    for key, value in changes.items():
        values[key_map.get(key, key)] = value
    with pytest.raises(ParameterValidationError) as caught:
        MotorParameters.from_input_dict(values)
    assert message in str(caught.value)


def test_spmsm_and_ipmsm_are_auto_detected():
    assert MotorParameters.example_spmsm().motor_type == "SPMSM"
    assert MotorParameters.example_ipmsm().motor_type == "IPMSM"
