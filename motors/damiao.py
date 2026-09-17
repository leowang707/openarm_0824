from __future__ import annotations

import threading
import time
from typing import Any, Optional

from .base import MotorBackend
from .registry import MotorSpec, register_motor

MOTOR_TYPE = "6248P"


class DaMiaoBackend(MotorBackend):
    model_key = "damiao_6248p"
    model_name = "DaMiao DM-J6248P"
    supported_modes = ("mit",)

    def __init__(self, bus: Any) -> None:
        super().__init__(bus)

        from damiao_motor import DaMiaoController

        # The external package creates its own bus in __init__. We intentionally
        # inject the already-open generic bus so all motor models share the same
        # adapter registry and OS abstraction.
        controller = DaMiaoController.__new__(DaMiaoController)
        controller.bus = bus
        controller.motors = {}
        controller._motors_by_feedback = {}
        controller._polling_thread = None
        controller._polling_active = False
        controller._polling_lock = threading.Lock()
        controller._adapter_kind = getattr(bus, "adapter_kind", "external")
        self.controller = controller
        self._txn_lock = threading.RLock()

    @property
    def motors(self):
        return self.controller.motors

    def _ensure_motor(self, motor_id: int, feedback_id: int = 0x00):
        motor_id = int(motor_id)
        try:
            return self.controller.add_motor(
                motor_id=motor_id,
                feedback_id=feedback_id,
                motor_type=MOTOR_TYPE,
            )
        except ValueError:
            return self.controller.get_motor(motor_id)

    def get_motor(self, motor_id: int):
        return self.controller.get_motor(int(motor_id))

    @staticmethod
    def _state_pos(motor) -> Optional[float]:
        state = (motor.get_states() if motor is not None else None) or {}
        pos = state.get("pos")
        return None if pos is None else float(pos)

    @staticmethod
    def _send_mit(motor, position: float, velocity: float, torque: float, kp: float, kd: float) -> None:
        data = motor.encode_cmd_msg(position, velocity, torque, kp, kd)
        motor.send_raw(data)

    def scan(self, start_id: int = 0x01, end_id: int = 0x10) -> list[dict[str, Any]]:
        found_ids: set[int] = set()

        with self._txn_lock:
            flush = getattr(self.controller, "flush_bus", None)
            if callable(flush):
                try:
                    flush()
                except Exception:
                    pass

            for motor_id in range(int(start_id), int(end_id) + 1):
                motor = self._ensure_motor(motor_id)
                try:
                    motor.state = {}
                except Exception:
                    pass

                try:
                    motor.request_motor_feedback()
                except Exception:
                    # Some firmware only responds after a harmless zero-gain MIT
                    # frame. This does not enable the motor by itself.
                    try:
                        self._send_mit(motor, 0.0, 0.0, 0.0, 0.0, 0.0)
                    except Exception:
                        continue

                deadline = time.perf_counter() + 0.15
                while time.perf_counter() < deadline:
                    state = motor.get_states() or {}
                    if state.get("can_id") is not None or state.get("arbitration_id") is not None:
                        found_ids.add(motor_id)
                        break
                    time.sleep(0.01)

        # Remove temporary motors that did not answer.
        for motor_id in list(self.controller.motors):
            if motor_id not in found_ids:
                self.controller.motors.pop(motor_id, None)
                self.controller._motors_by_feedback.pop(motor_id, None)

        return [self._motor_info(self.get_motor(mid)) for mid in sorted(found_ids)]

    def _motor_info(self, motor) -> dict[str, Any]:
        state = motor.get_states() or {}
        return {
            "id": int(motor.motor_id),
            "motor_id": int(motor.motor_id),
            "feedback_id": getattr(motor, "feedback_id", None),
            "status": state.get("status") or "Detected",
            "pos": state.get("pos"),
            "vel": state.get("vel"),
            "torq": state.get("torq"),
            "control_mode_key": "mit",
            "control_mode_name": "MIT",
        }

    def enable(self, motor_id: int) -> None:
        with self._txn_lock:
            motor = self.get_motor(motor_id)
            ensure = getattr(motor, "ensure_control_mode", None)
            if callable(ensure):
                ensure("MIT")
            motor.enable()

    def disable(self, motor_id: int) -> None:
        with self._txn_lock:
            self.get_motor(motor_id).disable()

    def get_control_mode(self, motor_id: int) -> str | None:
        self.get_motor(motor_id)
        return "mit"

    def set_control_mode(self, motor_id: int, mode: str, save: bool = True):
        del save
        if mode.lower() != "mit":
            raise ValueError("DaMiao DM-J6248P backend currently exposes MIT mode")
        motor = self.get_motor(motor_id)
        ensure = getattr(motor, "ensure_control_mode", None)
        if callable(ensure):
            ensure("MIT")
        return "mit"

    def send_command(self, motor_id: int, mode: str = "mit", **kwargs: Any):
        if mode.lower() != "mit":
            raise ValueError("DaMiao backend currently supports only MIT mode")

        with self._txn_lock:
            motor = self.get_motor(motor_id)
            self._send_mit(
                motor,
                float(kwargs.get("position", 0.0)),
                float(kwargs.get("velocity", 0.0)),
                float(kwargs.get("torque", 0.0)),
                float(kwargs.get("kp", 0.0)),
                float(kwargs.get("kd", 0.0)),
            )
            return motor.get_states() or {}

    def get_state(self, motor_id: int) -> dict[str, Any]:
        motor = self.get_motor(motor_id)
        state = dict(motor.get_states() or {})
        state.setdefault("id", int(motor_id))
        state.setdefault("motor_id", int(motor_id))
        return state

    def shutdown(self) -> None:
        with self._txn_lock:
            for motor in list(self.controller.motors.values()):
                try:
                    motor.disable()
                except Exception:
                    pass
            self.controller.motors.clear()
            self.controller._motors_by_feedback.clear()


register_motor(
    MotorSpec(
        key=DaMiaoBackend.model_key,
        name=DaMiaoBackend.model_name,
        backend=DaMiaoBackend,
        default_bitrate=1_000_000,
        default_scan_start=0x01,
        default_scan_end=0x10,
        supported_modes=DaMiaoBackend.supported_modes,
        motion_safe_default=True,
    )
)
