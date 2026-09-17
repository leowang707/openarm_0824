from __future__ import annotations

import threading
import time
from typing import Any

from lande_motor import (
    LandeMotor,
    MODE_NAMES,
    MODE_SERVO,
    MODE_TORQUE,
    MODE_TORQUE_POSITION,
    MODE_VELOCITY,
)

from .base import MotorBackend
from .registry import MotorSpec, register_motor


MODE_KEYS = {
    "servo": MODE_SERVO,
    "torque_position": MODE_TORQUE_POSITION,
    "velocity": MODE_VELOCITY,
    "torque": MODE_TORQUE,
}
MODE_KEYS_REVERSE = {value: key for key, value in MODE_KEYS.items()}


class LandeBackend(MotorBackend):
    model_key = "lande_pa043"
    model_name = "LANDA PA043"
    supported_modes = (
        "servo",
        "torque_position",
        "velocity",
        "torque",
    )

    def __init__(self, bus: Any) -> None:
        super().__init__(bus)
        self.motors: dict[int, LandeMotor] = {}
        # A full request/reply transaction must be serialized, not only each
        # individual bus.send()/recv().
        self._txn_lock = threading.RLock()

    def get_motor(self, motor_id: int) -> LandeMotor:
        motor_id = int(motor_id)
        try:
            return self.motors[motor_id]
        except KeyError as exc:
            raise KeyError(f"PA043 Motor ID 0x{motor_id:X} not found") from exc

    def _ensure_motor(self, motor_id: int) -> LandeMotor:
        motor_id = int(motor_id)
        motor = self.motors.get(motor_id)
        if motor is None:
            motor = LandeMotor(self.bus, motor_id)
            self.motors[motor_id] = motor
        return motor

    def scan(self, start_id: int = 0x00, end_id: int = 0x10) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        found_ids: set[int] = set()

        with self._txn_lock:
            for motor_id in range(int(start_id), int(end_id) + 1):
                motor = self._ensure_motor(motor_id)

                try:
                    firmware = motor.get_firmware_version()
                except TimeoutError:
                    continue

                found_ids.add(motor_id)

                try:
                    control_mode = motor.get_control_mode()
                except TimeoutError:
                    control_mode = None

                try:
                    stored_id = motor.get_motor_id()
                except TimeoutError:
                    stored_id = None

                found.append(
                    {
                        "id": motor_id,
                        "motor_id": motor_id,
                        "stored_id": stored_id,
                        "firmware": firmware,
                        "control_mode": control_mode,
                        "control_mode_key": MODE_KEYS_REVERSE.get(control_mode),
                        "control_mode_name": (
                            MODE_NAMES.get(control_mode, "Unknown")
                            if control_mode is not None
                            else "Unknown"
                        ),
                        "status": "Reset State",
                    }
                )

        for motor_id in list(self.motors):
            if motor_id not in found_ids:
                del self.motors[motor_id]

        return found

    def enable(self, motor_id: int) -> None:
        with self._txn_lock:
            self.get_motor(motor_id).enable()

    def disable(self, motor_id: int) -> None:
        with self._txn_lock:
            self.get_motor(motor_id).disable()

    def get_control_mode(self, motor_id: int) -> str | None:
        with self._txn_lock:
            value = self.get_motor(motor_id).get_control_mode()
        return MODE_KEYS_REVERSE.get(value)

    def set_control_mode(self, motor_id: int, mode: str, save: bool = True) -> int:
        if mode not in MODE_KEYS:
            raise ValueError(f"Unsupported PA043 control mode: {mode}")

        with self._txn_lock:
            motor = self.get_motor(motor_id)
            motor.disable()
            time.sleep(0.05)

            expected = MODE_KEYS[mode]
            motor.set_control_mode(expected)

            if save:
                motor.save_parameters()
                time.sleep(0.05)

            actual = motor.get_control_mode()
            if actual != expected:
                raise RuntimeError(
                    "PA043 control-mode verification failed: "
                    f"wanted 0x{expected:02X}, read 0x{actual:02X}"
                )
            return actual

    def send_command(self, motor_id: int, mode: str, **kwargs: Any):
        with self._txn_lock:
            motor = self.get_motor(motor_id)

            if mode == "servo":
                return motor.send_servo(
                    position=float(kwargs.get("position", 0.0)),
                    velocity=float(kwargs.get("velocity", 0.0)),
                    pos_kp=float(kwargs.get("pos_kp", kwargs.get("kp", 0.0))),
                    pos_kd=float(kwargs.get("pos_kd", kwargs.get("kd", 0.0))),
                    vel_kp=float(kwargs.get("vel_kp", 0.0)),
                    vel_kd=float(kwargs.get("vel_kd", 0.0)),
                    vel_ki=float(kwargs.get("vel_ki", 0.0)),
                    feedback_timeout=float(kwargs.get("feedback_timeout", 0.03)),
                )

            if mode == "torque_position":
                return motor.send_torque_position(
                    position=float(kwargs.get("position", 0.0)),
                    velocity=float(kwargs.get("velocity", 0.0)),
                    pos_kp=float(kwargs.get("pos_kp", kwargs.get("kp", 0.0))),
                    pos_kd=float(kwargs.get("pos_kd", kwargs.get("kd", 0.0))),
                    torque=float(kwargs.get("torque", 0.0)),
                    feedback_timeout=float(kwargs.get("feedback_timeout", 0.03)),
                )

            if mode == "velocity":
                return motor.send_velocity(
                    velocity=float(kwargs.get("velocity", 0.0)),
                    vel_kp=float(kwargs.get("vel_kp", kwargs.get("kp", 0.0))),
                    vel_kd=float(kwargs.get("vel_kd", kwargs.get("kd", 0.0))),
                    vel_ki=float(kwargs.get("vel_ki", 0.0)),
                    feedback_timeout=float(kwargs.get("feedback_timeout", 0.03)),
                )

            if mode == "torque":
                return motor.send_torque(
                    torque=float(kwargs.get("torque", 0.0)),
                    feedback_timeout=float(kwargs.get("feedback_timeout", 0.03)),
                )

        raise ValueError(f"Unsupported PA043 control mode: {mode}")

    def get_state(self, motor_id: int) -> dict[str, Any]:
        state = dict(self.get_motor(motor_id).get_states())
        state.setdefault("id", int(motor_id))
        state.setdefault("motor_id", int(motor_id))
        return state

    def shutdown(self) -> None:
        with self._txn_lock:
            for motor in list(self.motors.values()):
                try:
                    motor.disable()
                except Exception:
                    pass
            self.motors.clear()


register_motor(
    MotorSpec(
        key=LandeBackend.model_key,
        name=LandeBackend.model_name,
        backend=LandeBackend,
        default_bitrate=1_000_000,
        default_scan_start=0x00,
        default_scan_end=0x10,
        supported_modes=LandeBackend.supported_modes,
        # Keep PA043 motion locked by default until real feedback has been
        # validated on the bench.
        motion_safe_default=False,
    )
)
