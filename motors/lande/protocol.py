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

# The supplied PA043 manual specifies Classic CAN 2.0A standard frames
# (11-bit identifiers) at 1 Mbps. CAN FD is not part of the documented
# PA043 protocol.
CAN_STANDARD_ID_MAX = 0x7FF

# Manual page 20 states Motor ID range 0..1024, while page 17 states that
# parameter traffic uses Motor-ID + 0x600. Those statements conflict for
# IDs above 0x1FF on an 11-bit CAN 2.0A bus. Until the vendor documents
# the high-ID parameter addressing rule, parameter discovery is limited to
# the range that is representable without guessing.
DOCUMENTED_MOTOR_ID_MAX = 1024
PARAMETER_ADDRESSABLE_MOTOR_ID_MAX = CAN_STANDARD_ID_MAX - PARAM_CAN_BASE


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

        if not 0 <= self.motor_id <= CAN_STANDARD_ID_MAX:
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

        if can_id > CAN_STANDARD_ID_MAX:
            raise ValueError(
                f"Motor ID {self.motor_id} gives parameter "
                f"CAN ID 0x{can_id:X}, outside documented "
                f"CAN2.0A 11-bit range. The vendor manual "
                f"states Motor ID 0..{DOCUMENTED_MOTOR_ID_MAX} "
                f"but does not document parameter addressing "
                f"above 0x{PARAMETER_ADDRESSABLE_MOTOR_ID_MAX:X}."
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

            # Section 4.1 of the supplied manual defines parameter traffic
            # on Motor-ID + 0x600 using CAN2.0A standard frames. Filter on
            # the CAN identifier first so unrelated bus traffic cannot be
            # mistaken for a parameter response.
            if msg.is_extended_id:
                continue

            if msg.arbitration_id != self.parameter_can_id:
                continue

            data = bytes(msg.data)

            if len(data) != 8:
                continue

            # The response payload gives Motor-ID in one byte, while
            # the same manual also claims Motor IDs may be larger than 255.
            # The encoding of the upper Motor-ID bits is not documented.
            # Keep the historical low-byte check, but the arbitration ID
            # above is the authoritative discriminator for this driver.
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

    def get_firmware_version(
        self,
        timeout: float = 0.30,
    ) -> int:
        return self.read_int32(
            PARAM_FIRMWARE_VERSION,
            timeout,
        )

    def get_control_mode(
        self,
        timeout: float = 0.30,
    ) -> int:
        return self.read_int32(
            PARAM_CONTROL_MODE,
            timeout,
        )

    def get_motor_id(
        self,
        timeout: float = 0.30,
    ) -> int:
        return self.read_int32(
            PARAM_MOTOR_ID,
            timeout,
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
        # Manual section 4.3.1 marks bytes 2..6 as undefined. The driver
        # deliberately sends zero for every undefined byte.
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

    def restore_defaults(
        self,
        *,
        confirm: bool = False,
    ) -> None:
        if not confirm:
            raise ValueError(
                "restore_defaults requires confirm=True"
            )

        self._send_parameter_frame(
            [
                0x67,
                0x02,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x76,
            ]
        )

    def start_electric_angle_calibration(
        self,
        *,
        confirm: bool = False,
    ) -> None:
        if not confirm:
            raise ValueError(
                "electric-angle calibration requires confirm=True"
            )

        self._send_parameter_frame(
            [
                0x67,
                0x03,
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

    def enable(
        self,
        feedback_timeout: float = 0.03,
    ) -> Optional[dict]:
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
        if feedback_timeout <= 0:
            return None
        return self._recv_feedback(feedback_timeout)

    def disable(
        self,
        feedback_timeout: float = 0.03,
    ) -> Optional[dict]:
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
        if feedback_timeout <= 0:
            return None
        return self._recv_feedback(feedback_timeout)

    def set_zero(
        self,
        feedback_timeout: float = 0.03,
    ) -> Optional[dict]:
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

        if feedback_timeout <= 0:
            return None
        return self._recv_feedback(feedback_timeout)

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

                # Do not assign temperature/fault yet. The supplied
                # manual is internally inconsistent: the page-12 table
                # labels Byte6=Fault-ID, Byte7=Temp, while the page-13 prose
                # says Byte6=temperature, Byte7=fault. Preserve both raw
                # bytes until the vendor clarifies the encoding or bench
                # data conclusively identifies them.
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
