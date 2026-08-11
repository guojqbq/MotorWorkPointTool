"""Domain models for the PMSM performance tool."""

from .motor_parameters import MotorParameters, ParameterValidationError
from .operating_point import OperatingPoint, operating_points_to_dataframe

__all__ = [
    "MotorParameters",
    "OperatingPoint",
    "ParameterValidationError",
    "operating_points_to_dataframe",
]
from .saturation_map import InductanceSaturationMap
from .inductance_model import InductanceModel
from .winding_connection import OpenWindingTopology, WindingConnection

__all__ = [
    "InductanceModel",
    "InductanceSaturationMap",
    "OpenWindingTopology",
    "WindingConnection",
]
