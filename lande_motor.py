from __future__ import annotations

import struct
import time
from typing import Optional

import can


# ============================================================
# PA043 parameter indices
# ============================================================

PARAM_CAN_BASE = 0x600

PARAM_FIRMWARE_VERSION = 10
PARAM_CONTROL_MODE = 11
PARAM_MOTOR_ID = 36


# ============================================================
# PA043 control modes
# ============================================================

MODE_SERVO = 0x01
MODE_TORQUE_POSITION = 0x02
MODE_VELOCITY = 0x03
MODE_TORQUE = 0x04

MODE_NAMES = {
    MODE_SERVO: "Servo",
    MODE_TORQUE_POSITION: "Torque-Position Mixed",
    MODE_VELOCITY: "Velocity",
    MODE_TORQUE: "Torque",
}


# ============================================================
# Default CAN communication mappings from manual
# ============================================================

THETA_MIN = -12.5
THETA_MAX = 12.5

VELOCITY_MIN = -10.0
VELOCITY_MAX = 10.0

KP_MIN = 0.0
KP_MAX = 250.0

KD_MIN = 0.0
KD_MAX = 50.0

KI_MIN = 0.0
KI_MAX = 0.05

TORQUE_MIN = -50.0
TORQUE_MAX = 50.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _float_to_uint(
    value: float,
    low: float,
    high: float,
    bits: int,
) -> int:
    value = _clamp(value, low, high)

    scale = (1 << bits) - 1

    return int(
        round(
            (value - low)
            * scale
            / (high - low)
        )
    )


def _uint_to_float(
    value: int,
    low: float,
    high: float,
    bits: int,
) -> float:
    scale = (1 << bits) - 1

    return (
        float(value)
        * (high - low)
        / scale
        + low
    )


class LandeMotor:
    def __init__(
        self,
        bus,
        motor_id: int,
    ):
        self.bus = bus
        self.motor_id = int(motor_id)

        if not 0 <= self.motor_id <= 0x7FF:
            raise ValueError(
                f"Invalid standard CAN Motor ID: "
                f"{self.motor_id}"
            )

        self._state = {
            "can_id": None,
            "reported_id": None,

            "pos": None,
            "vel": None,
            "torq": None,

            "status": "Reset/Unknown",

            # Manual page 12/13 has an inconsistency
            # regarding Byte6 / Byte7.
            "temperature": None,
            "fault": None,

            "raw_byte6": None,
            "raw_byte7": None,
        }

    # ========================================================
    # Basic CAN helpers
    # ========================================================

    @property
    def parameter_can_id(self) -> int:
        can_id = PARAM_CAN_BASE + self.motor_id

        if can_id > 0x7FF:
            raise ValueError(
                f"Motor ID {self.motor_id} gives parameter "
                f"CAN ID 0x{can_id:X}, outside CAN2.0A "
                f"11-bit range"
            )

        return can_id

    def _send(
        self,
        data,
    ) -> None:
        msg = can.Message(
            arbitration_id=self.motor_id,
            is_extended_id=False,
            data=bytes(data),
        )

        self.bus.send(msg)

    def _send_parameter_frame(
        self,
        data,
    ) -> None:
        msg = can.Message(
            arbitration_id=self.parameter_can_id,
            is_extended_id=False,
            data=bytes(data),
        )

        self.bus.send(msg)

    # ========================================================
    # Parameter protocol
    # ========================================================

    def _recv_parameter_reply(
        self,
        index: int,
        timeout: float,
    ) -> bytes:

        deadline = time.perf_counter() + timeout

        while time.perf_counter() < deadline:
            remain = deadline - time.perf_counter()

            msg = self.bus.recv(
                timeout=max(
                    0.0,
                    min(0.05, remain),
                )
            )

            if msg is None:
                continue

            data = bytes(msg.data)

            if len(data) != 8:
                continue

            if data[0] != (
                self.motor_id & 0xFF
            ):
                continue

            if data[1] != (
                index & 0xFF
            ):
                continue

            if data[6] != 0x00:
                continue

            if data[7] != 0xFF:
                continue

            return data[2:6]

        raise TimeoutError(
            f"No parameter response from "
            f"Motor ID {self.motor_id}, "
            f"index {index}"
        )

    def read_parameter_raw(
        self,
        index: int,
        timeout: float = 0.30,
    ) -> bytes:

        self._send_parameter_frame(
            [
                0x67,
                index & 0xFF,

                0x00,
                0x00,
                0x00,
                0x00,

                0x04,   # READ
                0x76,
            ]
        )

        return self._recv_parameter_reply(
            index,
            timeout,
        )

    def read_int32(
        self,
        index: int,
        timeout: float = 0.30,
    ) -> int:

        raw = self.read_parameter_raw(
            index,
            timeout,
        )

        return struct.unpack(
            "<i",
            raw,
        )[0]

    def read_float32(
        self,
        index: int,
        timeout: float = 0.30,
    ) -> float:

        raw = self.read_parameter_raw(
            index,
            timeout,
        )

        return struct.unpack(
            "<f",
            raw,
        )[0]

    def write_parameter_raw(
        self,
        index: int,
        raw4: bytes,
        timeout: float = 0.30,
    ) -> bytes:

        if len(raw4) != 4:
            raise ValueError(
                "Parameter data must be exactly 4 bytes"
            )

        self._send_parameter_frame(
            [
                0x67,
                index & 0xFF,

                raw4[0],
                raw4[1],
                raw4[2],
                raw4[3],

                0x15,   # WRITE
                0x76,
            ]
        )

        return self._recv_parameter_reply(
            index,
            timeout,
        )

    def write_int32(
        self,
        index: int,
        value: int,
        timeout: float = 0.30,
    ) -> int:

        raw = self.write_parameter_raw(
            index,
            struct.pack(
                "<i",
                int(value),
            ),
            timeout,
        )

        return struct.unpack(
            "<i",
            raw,
        )[0]

    def write_float32(
        self,
        index: int,
        value: float,
        timeout: float = 0.30,
    ) -> float:

        raw = self.write_parameter_raw(
            index,
            struct.pack(
                "<f",
                float(value),
            ),
            timeout,
        )

        return struct.unpack(
            "<f",
            raw,
        )[0]

    # ========================================================
    # Common parameters
    # ========================================================

    def get_firmware_version(self) -> int:
        return self.read_int32(
            PARAM_FIRMWARE_VERSION
        )

    def get_control_mode(self) -> int:
        return self.read_int32(
            PARAM_CONTROL_MODE
        )

    def get_motor_id(self) -> int:
        return self.read_int32(
            PARAM_MOTOR_ID
        )

    def set_control_mode(
        self,
        mode: int,
    ) -> int:

        if mode not in MODE_NAMES:
            raise ValueError(
                f"Unsupported PA043 mode: "
                f"0x{mode:02X}"
            )

        return self.write_int32(
            PARAM_CONTROL_MODE,
            mode,
        )

    def save_parameters(self) -> None:
        self._send_parameter_frame(
            [
                0x67,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x76,
            ]
        )

    # ========================================================
    # Motor state
    # ========================================================

    def enable(self) -> None:
        self._send(
            [
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFC,
            ]
        )

        self._state["status"] = "Motor State"

    def disable(self) -> None:
        self._send(
            [
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFD,
            ]
        )

        self._state["status"] = "Reset State"

    def set_zero(self) -> None:
        self._send(
            [
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFE,
            ]
        )

    # ========================================================
    # Feedback
    # ========================================================

    def _recv_feedback(
        self,
        timeout: float = 0.03,
    ) -> Optional[dict]:

        deadline = time.perf_counter() + timeout

        while time.perf_counter() < deadline:
            remain = deadline - time.perf_counter()

            msg = self.bus.recv(
                timeout=max(
                    0.0,
                    min(0.01, remain),
                )
            )

            if msg is None:
                continue

            if msg.is_extended_id:
                continue

            if msg.arbitration_id != self.motor_id:
                continue

            if len(msg.data) != 8:
                continue

            return self.decode_feedback(
                bytes(msg.data)
            )

        return None

    def decode_feedback(
        self,
        data: bytes,
    ) -> dict:

        if len(data) != 8:
            raise ValueError(
                "PA043 feedback must be 8 bytes"
            )

        reported_id = data[0]

        position_raw = (
            (data[1] << 8)
            | data[2]
        )

        velocity_raw = (
            (data[3] << 4)
            | (data[4] >> 4)
        )

        torque_raw = (
            ((data[4] & 0x0F) << 8)
            | data[5]
        )

        position = _uint_to_float(
            position_raw,
            THETA_MIN,
            THETA_MAX,
            16,
        )

        velocity = _uint_to_float(
            velocity_raw,
            VELOCITY_MIN,
            VELOCITY_MAX,
            12,
        )

        torque = _uint_to_float(
            torque_raw,
            TORQUE_MIN,
            TORQUE_MAX,
            12,
        )

        self._state.update(
            {
                "can_id": self.motor_id,
                "reported_id": reported_id,

                "pos": position,
                "vel": velocity,
                "torq": torque,

                "raw_byte6": data[6],
                "raw_byte7": data[7],
            }
        )

        return dict(self._state)

    def get_states(self) -> dict:
        return dict(self._state)

    # ========================================================
    # Servo mode 0x01
    # ========================================================

    def send_servo(
        self,
        position: float,
        velocity: float,

        pos_kp: float,
        pos_kd: float,

        vel_kp: float = 0.0,
        vel_kd: float = 0.0,
        vel_ki: float = 0.0,

        feedback_timeout: float = 0.03,
    ) -> Optional[dict]:

        p = _float_to_uint(
            position,
            THETA_MIN,
            THETA_MAX,
            16,
        )

        v = _float_to_uint(
            velocity,
            VELOCITY_MIN,
            VELOCITY_MAX,
            8,
        )

        pos_kp_i = _float_to_uint(
            pos_kp,
            KP_MIN,
            KP_MAX,
            8,
        )

        pos_kd_i = _float_to_uint(
            pos_kd,
            KD_MIN,
            KD_MAX,
            8,
        )

        vel_kp_i = _float_to_uint(
            vel_kp,
            KP_MIN,
            KP_MAX,
            8,
        )

        vel_kd_i = _float_to_uint(
            vel_kd,
            KD_MIN,
            KD_MAX,
            8,
        )

        vel_ki_i = _float_to_uint(
            vel_ki,
            KI_MIN,
            KI_MAX,
            8,
        )

        self._send(
            [
                (p >> 8) & 0xFF,
                p & 0xFF,

                v,

                pos_kp_i,
                pos_kd_i,

                vel_kp_i,
                vel_kd_i,
                vel_ki_i,
            ]
        )

        return self._recv_feedback(
            feedback_timeout
        )

    # ========================================================
    # Torque-Position Mixed mode 0x02
    # ========================================================

    def send_torque_position(
        self,
        position: float,
        velocity: float,

        pos_kp: float,
        pos_kd: float,

        torque: float,

        feedback_timeout: float = 0.03,
    ) -> Optional[dict]:

        p = _float_to_uint(
            position,
            THETA_MIN,
            THETA_MAX,
            16,
        )

        v = _float_to_uint(
            velocity,
            VELOCITY_MIN,
            VELOCITY_MAX,
            12,
        )

        kp = _float_to_uint(
            pos_kp,
            KP_MIN,
            KP_MAX,
            12,
        )

        kd = _float_to_uint(
            pos_kd,
            KD_MIN,
            KD_MAX,
            12,
        )

        tq = _float_to_uint(
            torque,
            TORQUE_MIN,
            TORQUE_MAX,
            12,
        )

        self._send(
            [
                (p >> 8) & 0xFF,
                p & 0xFF,

                (v >> 4) & 0xFF,

                ((v & 0x0F) << 4)
                | ((kp >> 8) & 0x0F),

                kp & 0xFF,

                (kd >> 4) & 0xFF,

                ((kd & 0x0F) << 4)
                | ((tq >> 8) & 0x0F),

                tq & 0xFF,
            ]
        )

        return self._recv_feedback(
            feedback_timeout
        )

    # ========================================================
    # Velocity mode 0x03
    # ========================================================

    def send_velocity(
        self,
        velocity: float,

        vel_kp: float,
        vel_kd: float,
        vel_ki: float,

        feedback_timeout: float = 0.03,
    ) -> Optional[dict]:

        v = _float_to_uint(
            velocity,
            VELOCITY_MIN,
            VELOCITY_MAX,
            16,
        )

        kp = _float_to_uint(
            vel_kp,
            KP_MIN,
            KP_MAX,
            12,
        )

        kd = _float_to_uint(
            vel_kd,
            KD_MIN,
            KD_MAX,
            12,
        )

        ki = _float_to_uint(
            vel_ki,
            KI_MIN,
            KI_MAX,
            12,
        )

        self._send(
            [
                (v >> 8) & 0xFF,
                v & 0xFF,

                (kp >> 4) & 0xFF,

                ((kp & 0x0F) << 4)
                | ((kd >> 8) & 0x0F),

                kd & 0xFF,

                (ki >> 4) & 0xFF,

                ((ki & 0x0F) << 4),

                0xAC,
            ]
        )

        return self._recv_feedback(
            feedback_timeout
        )

    # ========================================================
    # Torque mode 0x04
    # ========================================================

    def send_torque(
        self,
        torque: float,

        feedback_timeout: float = 0.03,
    ) -> Optional[dict]:

        tq = _float_to_uint(
            torque,
            TORQUE_MIN,
            TORQUE_MAX,
            16,
        )

        self._send(
            [
                (tq >> 8) & 0xFF,
                tq & 0xFF,

                0x00,
                0x00,
                0x00,
                0x00,
                0x00,

                0xAB,
            ]
        )

        return self._recv_feedback(
            feedback_timeout
        )