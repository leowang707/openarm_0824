"""Model identity and SDK presets; mapping spans are NOT safe torque limits.

Preset reference values are checked in tests, not pushed into motor registers.
P/non-P identity cannot be inferred from a UART firmware number.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class DaMiaoModel:
    key: str
    name: str
    family: str
    sdk_motor_type: str
    supported_modes: tuple[str, ...]
    mapping_reference: tuple[float, float, float]


J6248P = DaMiaoModel(
    "damiao_6248p", "DaMiao DM-J6248P", "6248P", "6248P",
    ("mit", "pos_vel", "vel", "force_pos"), (12.566, 20.0, 120.0),
)
J8009P = DaMiaoModel(
    "damiao_8009p", "DaMiao DM-J8009P-2EC", "8009", "8009",
    ("mit", "pos_vel", "vel"), (12.5, 45.0, 54.0),
)
MODELS = {model.key: model for model in (J6248P, J8009P)}
