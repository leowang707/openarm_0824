"""DaMiao brand registration. Old motors.damiao imports remain valid."""
from ..registry import MotorSpec, register_motor
from .common import MODE_TO_DRIVER, REGISTER_TO_MODE, SCAN_ID_MIN, SCAN_ID_MAX
from .classic import _DaMiaoBackend, DaMiao6248PBackend, DaMiao8009PBackend
from .models import J6248P, J8009P
from .profiles import CLASSIC_1M, J8009_CANFD_1M_5M_OBSERVED

for model, backend, profiles in (
    (J6248P, DaMiao6248PBackend, (CLASSIC_1M,)),
    (J8009P, DaMiao8009PBackend, (CLASSIC_1M, J8009_CANFD_1M_5M_OBSERVED)),
):
    register_motor(MotorSpec(
        key=model.key, name=model.name, backend=backend,
        bus_profiles=profiles, default_bus_profile="classic_1m",
        default_scan_start=SCAN_ID_MIN, default_scan_end=SCAN_ID_MAX,
        supported_modes=model.supported_modes, motion_safe_default=True,
        brand="damiao", brand_name="DaMiao", family=model.family,
        protocol_family="damiao_classic",
    ))
