"""Parameters for optional copper-temperature and iron-loss estimates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class LossModelParameters:
    """Whole-motor empirical loss settings.

    The iron-loss coefficients are empirical whole-motor coefficients.  They
    are deliberately disabled by default because uncalibrated values must not
    silently affect formal results.
    """

    iron_loss_enabled: bool = False
    iron_loss_model: str = "three_term"
    kh: float = 0.0
    ke: float = 0.0
    kex: float = 0.0
    alpha: float = 2.0
    k1: float = 0.0
    k2: float = 0.0
    model_name: str = "未标定铁耗估算模型"
    coefficient_source: str = ""
    calibration_note: str = "演示/估算用途；系数需通过实测损耗数据标定。"
    reference_temperature_c: float = 20.0
    winding_temperature_c: float = 20.0
    copper_alpha_per_c: float = 0.00393
    temperature_correction_enabled: bool = False
    minimum_efficiency_output_w: float = 100.0

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if self.iron_loss_model not in {"three_term", "simplified"}:
            errors.append("铁耗模型必须为 three_term 或 simplified。")
        for name, value in {
            "Kh": self.kh,
            "Ke": self.ke,
            "Kex": self.kex,
            "K1": self.k1,
            "K2": self.k2,
        }.items():
            if value < 0:
                errors.append(f"{name} 不能为负数。")
        if not 1.0 <= self.alpha <= 4.0:
            errors.append("铁耗磁密指数 alpha 必须在 1 到 4 之间。")
        if self.copper_alpha_per_c < 0:
            errors.append("铜电阻温度系数不能为负数。")
        if self.minimum_efficiency_output_w < 0:
            errors.append("效率最小输出功率阈值不能为负数。")
        resistance_factor = 1.0 + self.copper_alpha_per_c * (
            self.winding_temperature_c - self.reference_temperature_c
        )
        if resistance_factor <= 0:
            errors.append("温度修正后的定子电阻必须大于零。")
        return errors

    def validated(self) -> "LossModelParameters":
        errors = self.validation_errors()
        if errors:
            raise ValueError("\n".join(errors))
        return self

    def resistance_at_temperature(self, reference_resistance_ohm: float) -> float:
        if not self.temperature_correction_enabled:
            return float(reference_resistance_ohm)
        factor = 1.0 + self.copper_alpha_per_c * (
            self.winding_temperature_c - self.reference_temperature_c
        )
        return float(reference_resistance_ohm) * factor

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any] | None) -> "LossModelParameters":
        if not values:
            return cls()
        known = {field_name for field_name in cls.__dataclass_fields__}
        return cls(
            **{key: value for key, value in values.items() if key in known}
        ).validated()
