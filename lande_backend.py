from __future__ import annotations

import time
from typing import Any

from can_adapter import detect_kind, open_serial_bus
from lande_motor import (
    LandeMotor,
    MODE_NAMES,
    MODE_SERVO,
    MODE_TORQUE_POSITION,
    MODE_VELOCITY,
    MODE_TORQUE,
)


MODE_KEYS = {
    "servo": MODE_SERVO,
    "torque_position": MODE_TORQUE_POSITION,
    "velocity": MODE_VELOCITY,
    "torque": MODE_TORQUE,
}

MODE_KEYS_REVERSE = {value: key for key, value in MODE_KEYS.items()}


class LandeBackend:
    """GUI backend for LANDA PA043."""

    model_key = "lande_pa043"
    model_name = "LANDA PA043"
    supported_modes = (
        "servo",
        "torque_position",
        "velocity",
        "torque",
    )

    def __init__(
        self,
        channel: str,
        adapter: str = "auto",
        bitrate: int = 1_000_000,
    ):
        self.channel = channel
        self.kind = detect_kind(channel, adapter)
        self.bus = open_serial_bus(
            channel=channel,
            kind=self.kind,
            bitrate=bitrate,
        )
        self.motors: dict[int, LandeMotor] = {}

    def get_motor(self, motor_id: int) -> LandeMotor:
        motor_id = int(motor_id)
        if motor_id not in self.motors:
            raise KeyError(f"PA043 Motor ID 0x{motor_id:02X} not found")
        return self.motors[motor_id]

    def _ensure_motor(self, motor_id: int) -> LandeMotor:
        motor_id = int(motor_id)
        motor = self.motors.get(motor_id)
        if motor is None:
            motor = LandeMotor(self.bus, motor_id)
            self.motors[motor_id] = motor
        return motor

    def scan(
        self,
        start_id: int = 0x00,
        end_id: int = 0x10,
    ) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        found_ids: set[int] = set()

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
        self.get_motor(motor_id).enable()

    def disable(self, motor_id: int) -> None:
        self.get_motor(motor_id).disable()

    def get_control_mode(self, motor_id: int) -> int:
        return self.get_motor(motor_id).get_control_mode()

    def set_control_mode(
        self,
        motor_id: int,
        mode: str,
        save: bool = True,
    ) -> int:
        if mode not in MODE_KEYS:
            raise ValueError(f"Unsupported PA043 control mode: {mode}")

        motor = self.get_motor(motor_id)

        # PA043 parameter writes must be performed in Reset State.
        motor.disable()
        time.sleep(0.05)

        mode_value = MODE_KEYS[mode]
        motor.set_control_mode(mode_value)

        if save:
            motor.save_parameters()
            time.sleep(0.05)

        readback = motor.get_control_mode()
        if readback != mode_value:
            raise RuntimeError(
                "PA043 control-mode verification failed: "
                f"wanted 0x{mode_value:02X}, read 0x{readback:02X}"
            )
        return readback

    def send_command(
        self,
        motor_id: int,
        mode: str,
        *,
        position: float = 0.0,
        velocity: float = 0.0,
        pos_kp: float = 0.0,
        pos_kd: float = 0.0,
        vel_kp: float = 0.0,
        vel_kd: float = 0.0,
        vel_ki: float = 0.0,
        torque: float = 0.0,
        feedback_timeout: float = 0.03,
    ):
        motor = self.get_motor(motor_id)

        if mode == "servo":
            return motor.send_servo(
                position=position,
                velocity=velocity,
                pos_kp=pos_kp,
                pos_kd=pos_kd,
                vel_kp=vel_kp,
                vel_kd=vel_kd,
                vel_ki=vel_ki,
                feedback_timeout=feedback_timeout,
            )

        if mode == "torque_position":
            return motor.send_torque_position(
                position=position,
                velocity=velocity,
                pos_kp=pos_kp,
                pos_kd=pos_kd,
                torque=torque,
                feedback_timeout=feedback_timeout,
            )

        if mode == "velocity":
            return motor.send_velocity(
                velocity=velocity,
                vel_kp=vel_kp,
                vel_kd=vel_kd,
                vel_ki=vel_ki,
                feedback_timeout=feedback_timeout,
            )

        if mode == "torque":
            return motor.send_torque(
                torque=torque,
                feedback_timeout=feedback_timeout,
            )

        raise ValueError(f"Unsupported PA043 control mode: {mode}")

    def get_state(self, motor_id: int) -> dict[str, Any]:
        motor = self.get_motor(motor_id)
        state = dict(motor.get_states())
        state.setdefault("id", motor_id)
        return state

    def shutdown(self) -> None:
        # Reset State is non-motion; send it before closing the adapter.
        for motor in list(self.motors.values()):
            try:
                motor.disable()
            except Exception:
                pass
        self.motors.clear()
        self.bus.shutdown()
