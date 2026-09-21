from __future__ import annotations

import threading
import time
from typing import Any

from ..base import MotorBackend
from .common import MODE_TO_DRIVER, REGISTER_TO_MODE, SCAN_ID_MIN, SCAN_ID_MAX
from .models import J6248P, J8009P


class _DaMiaoBackend(MotorBackend):
    """Shared DaMiao backend over the repository's generic CAN bus."""

    motor_type = ""
    supported_modes: tuple[str, ...] = ("mit",)

    def __init__(self, bus: Any) -> None:
        super().__init__(bus)

        from damiao_motor import DaMiaoController

        # Inject the already-open generic bus so DaMiao motors keep using the
        # repository's cross-platform CAN adapter registry.
        controller = DaMiaoController.__new__(DaMiaoController)
        controller.bus = bus
        controller.motors = {}
        controller._motors_by_feedback = {}
        controller._polling_thread = None
        controller._polling_active = False
        controller._polling_lock = threading.Lock()
        controller._fd = False  # Classic CAN for this repository path.
        controller._adapter_kind = getattr(bus, "adapter_kind", "external")

        self.controller = controller
        self._txn_lock = threading.RLock()

    @property
    def motors(self):
        return self.controller.motors

    def _ensure_motor(self, motor_id: int, feedback_id: int = 0x00):
        motor_id = int(motor_id)
        if motor_id in self.controller.motors:
            return self.controller.get_motor(motor_id)
        return self.controller.add_motor(
            motor_id=motor_id,
            feedback_id=feedback_id,
            motor_type=self.motor_type,
        )

    def get_motor(self, motor_id: int):
        return self.controller.get_motor(int(motor_id))

    def _read_control_mode(self, motor, timeout: float = 0.50) -> str | None:
        try:
            value = int(motor.get_register(10, timeout=timeout))
        except Exception:
            return None
        return REGISTER_TO_MODE.get(value)

    def scan(self, start_id: int = SCAN_ID_MIN, end_id: int = SCAN_ID_MAX) -> list[dict[str, Any]]:
        start_id = int(start_id)
        end_id = int(end_id)
        if start_id < SCAN_ID_MIN or end_id > SCAN_ID_MAX or end_id < start_id:
            raise ValueError(
                "DaMiao automatic scan currently supports logical Motor IDs "
                f"0x{SCAN_ID_MIN:X}..0x{SCAN_ID_MAX:X}. The installed "
                "damiao-motor feedback router uses only the low 4 bits of D[0]."
            )

        found_ids: set[int] = set()

        with self._txn_lock:
            flush = getattr(self.controller, "flush_bus", None)
            if callable(flush):
                try:
                    flush()
                except Exception:
                    pass

            for motor_id in range(start_id, end_id + 1):
                motor = self._ensure_motor(motor_id)
                try:
                    motor.state = {}
                except Exception:
                    pass

                try:
                    motor.request_motor_feedback()
                except Exception as exc:
                    # A scan must not call motion APIs: some dependency versions
                    # implicitly enable a disabled motor when sending a command.
                    raise RuntimeError(
                        f"Read-only status request failed for ID {motor_id}; "
                        "no motion-command fallback was sent"
                    ) from exc

                deadline = time.perf_counter() + 0.15
                while time.perf_counter() < deadline:
                    state = motor.get_states() or {}
                    if state.get("can_id") is not None or state.get("arbitration_id") is not None:
                        found_ids.add(motor_id)
                        break
                    time.sleep(0.01)

        for motor_id in list(self.controller.motors):
            if motor_id not in found_ids:
                self.controller.motors.pop(motor_id, None)
                self.controller._motors_by_feedback.pop(motor_id, None)

        result = []
        for motor_id in sorted(found_ids):
            motor = self.get_motor(motor_id)
            result.append(self._motor_info(motor, self._read_control_mode(motor)))
        return result

    def _motor_info(self, motor, mode: str | None = None) -> dict[str, Any]:
        state = motor.get_states() or {}
        return {
            "id": int(motor.motor_id),
            "motor_id": int(motor.motor_id),
            "feedback_id": getattr(motor, "feedback_id", None),
            "motor_type": self.motor_type,
            "status": state.get("status") or "Detected",
            "pos": state.get("pos"),
            "vel": state.get("vel"),
            "torq": state.get("torq"),
            "t_mos": state.get("t_mos"),
            "t_rotor": state.get("t_rotor"),
            "control_mode_key": mode,
            "control_mode_name": MODE_TO_DRIVER.get(mode, "Unknown") if mode else "Unknown",
        }

    def enable(self, motor_id: int) -> None:
        # Do not force MIT here. set_control_mode() owns mode selection.
        with self._txn_lock:
            self.get_motor(motor_id).enable()

    def disable(self, motor_id: int) -> None:
        with self._txn_lock:
            self.get_motor(motor_id).disable()

    def get_control_mode(self, motor_id: int) -> str | None:
        with self._txn_lock:
            return self._read_control_mode(self.get_motor(motor_id))

    def set_control_mode(self, motor_id: int, mode: str, save: bool = True):
        mode = str(mode).strip().lower()
        if mode not in self.supported_modes:
            raise ValueError(
                f"{self.model_name} does not expose {mode!r}; supported: "
                + ", ".join(self.supported_modes)
            )

        with self._txn_lock:
            motor = self.get_motor(motor_id)
            motor.disable()
            time.sleep(0.05)
            motor.ensure_control_mode(MODE_TO_DRIVER[mode])

            if save:
                store = getattr(motor, "store_parameters", None)
                if callable(store):
                    store()
                    time.sleep(0.02)

            actual = self._read_control_mode(motor)
            if actual is not None and actual != mode:
                raise RuntimeError(
                    "DaMiao control-mode verification failed: "
                    f"wanted {mode!r}, read {actual!r}"
                )
            return actual or mode

    def send_command(self, motor_id: int, mode: str = "mit", **kwargs: Any):
        mode = str(mode).strip().lower()
        if mode not in self.supported_modes:
            raise ValueError(
                f"{self.model_name} does not support {mode!r}; supported: "
                + ", ".join(self.supported_modes)
            )

        with self._txn_lock:
            motor = self.get_motor(motor_id)

            if mode == "mit":
                motor.send_cmd_mit(
                    target_position=float(kwargs.get("position", 0.0)),
                    target_velocity=float(kwargs.get("velocity", 0.0)),
                    stiffness=float(kwargs.get("kp", 0.0)),
                    damping=float(kwargs.get("kd", 0.0)),
                    feedforward_torque=float(kwargs.get("torque", 0.0)),
                )

            elif mode == "pos_vel":
                motor.send_cmd_pos_vel(
                    target_position=float(kwargs.get("position", 0.0)),
                    velocity_limit=abs(float(kwargs.get("velocity_limit", kwargs.get("velocity", 0.0)))),
                )

            elif mode == "vel":
                motor.send_cmd_vel(
                    target_velocity=float(kwargs.get("velocity", 0.0))
                )

            elif mode == "force_pos":
                ratio = float(kwargs.get("torque_limit_ratio", 0.0))
                if not 0.0 <= ratio <= 1.0:
                    raise ValueError("torque_limit_ratio must be within 0.0..1.0")
                motor.send_cmd_force_pos(
                    target_position=float(kwargs.get("position", 0.0)),
                    velocity_limit=abs(float(kwargs.get("velocity_limit", kwargs.get("velocity", 0.0)))),
                    torque_limit_ratio=ratio,
                )

            return motor.get_states() or {}

    def get_state(self, motor_id: int) -> dict[str, Any]:
        state = dict(self.get_motor(motor_id).get_states() or {})
        state.setdefault("id", int(motor_id))
        state.setdefault("motor_id", int(motor_id))
        return state

    def shutdown(self) -> None:
        with self._txn_lock:
            stop = getattr(self.controller, "_stop_polling", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
            for motor in list(self.controller.motors.values()):
                try:
                    motor.disable()
                except Exception:
                    pass
            self.controller.motors.clear()
            self.controller._motors_by_feedback.clear()


class DaMiao6248PBackend(_DaMiaoBackend):
    model_key = J6248P.key
    model_name = J6248P.name
    motor_type = J6248P.sdk_motor_type
    supported_modes = J6248P.supported_modes


class DaMiao8009PBackend(_DaMiaoBackend):
    model_key = J8009P.key
    model_name = J8009P.name
    motor_type = J8009P.sdk_motor_type
    supported_modes = J8009P.supported_modes
