"""Offline PA043 GUI motion-lock contract tests. No real serial/CAN is opened."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Stub only the GUI's two imported application dependencies. Nothing can open
# USB, CAN, serial, the installed DaMiao SDK, or an HTTP listener.
service_stub = types.ModuleType("motor_service")
service_stub.MotorService = type("NoHardwareMotorService", (), {})
sys.modules["motor_service"] = service_stub

motors_stub = types.ModuleType("motors")
specs = {
    "lande_pa043": types.SimpleNamespace(
        supported_modes=("servo", "torque_position", "velocity", "torque"),
        brand="lande", name="LANDA PA043", motion_safe_default=False,
        default_scan_start=0, default_scan_end=16,
    ),
    "damiao_6248p": types.SimpleNamespace(
        supported_modes=("mit", "pos_vel", "vel", "force_pos"),
        brand="damiao", name="DM-J6248P", motion_safe_default=True,
        default_scan_start=1, default_scan_end=15,
    ),
}
motors_stub.get_motor_spec = lambda key: specs[key]
sys.modules["motors"] = motors_stub

# The GUI HTTP route functions are tested as Python callables here, so no
# actual Flask server/socket or Flask dependency is needed.
class FakeFlask:
    def __init__(self, *args, **kwargs):
        pass

    def route(self, *args, **kwargs):
        return lambda func: func


fake_request = types.SimpleNamespace(get_json=lambda silent=True: {})
flask_stub = types.ModuleType("flask")
flask_stub.Flask = FakeFlask
flask_stub.jsonify = lambda value: value
flask_stub.render_template = lambda name: name
flask_stub.request = fake_request
sys.modules["flask"] = flask_stub

import gui_server as gui  # noqa: E402


class FakeService:
    def __init__(self):
        self.connected = True
        self.motor_model = "lande_pa043"
        self.mode = "servo"
        self.calls = []
        self.disable_feedback = {"pos": 1.2, "id": 1}

    def connection_info(self):
        return {
            "connected": self.connected,
            "motor_model": self.motor_model if self.connected else None,
            "adapter": "slcan" if self.connected else None,
            "channel": "COM10" if self.connected else None,
            "bus_profile": "classic_1m" if self.connected else None,
            "bitrate": 1_000_000 if self.connected else None,
        }

    def get_state(self, mid):
        return {"pos": 1.2, "vel": 0.0, "torq": 0.0}

    def enable(self, mid):
        self.calls.append(("enable", mid))
        return {"pos": 1.2, "id": mid}

    def disable(self, mid):
        self.calls.append(("disable", mid))
        return self.disable_feedback

    def connect(self, **kwargs):
        self.calls.append(("connect", kwargs.get("motor_model")))
        self.connected = True
        self.motor_model = kwargs["motor_model"]

    def disconnect(self):
        self.calls.append(("disconnect", None))
        self.connected = False

    def scan(self, start_id=None, end_id=None):
        self.calls.append(("scan", start_id, end_id))
        return [{"id": 1, "control_mode_key": self.mode, "firmware": 260209}]

    def set_control_mode(self, mid, mode, save=True):
        self.calls.append(("set_control_mode", mid, mode))
        self.mode = mode

    def send_command(self, mid, mode, **kwargs):
        self.calls.append(("send_command", mid, mode))
        return {"pos": kwargs.get("position", 1.2)}


class Pa043MotionLockTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeService()
        gui._service = self.fake
        gui._motors = [{"id": 1, "control_mode_key": "servo", "firmware": 260209}]
        gui._tracks = {1: {
            "enabled": False, "spin_dir": 0, "cmd_pos": 1.2,
            "target_pos": 1.2, "fail": 0,
        }}
        gui._selected_ids = [1]
        gui._focus_id = 1
        gui._control_mode = "servo"
        gui._pa043_motion_unlocked = False
        self.old_ensure_loop = gui._ensure_loop
        gui._ensure_loop = lambda: None
        fake_request.get_json = lambda silent=True: {}

    def tearDown(self):
        gui._ensure_loop = self.old_ensure_loop
        gui._pa043_motion_unlocked = False

    def post(self, fn, payload):
        fake_request.get_json = lambda silent=True: payload
        result = fn()
        if isinstance(result, tuple):
            return result[0], result[1]
        return result, 200

    def unlock(self):
        return self.post(gui.motion_lock, {
            "action": "unlock",
            "confirmation": gui.PA043_UNLOCK_CONFIRMATION,
        })

    def test_initial_lock_even_with_legacy_environment_variable(self):
        with patch.dict(os.environ, {"ALLOW_PA043_MOTION": "1"}):
            self.assertFalse(gui._motion_allowed())
            state = gui._state_payload()
            self.assertFalse(state["motion_unlocked"])
            self.assertTrue(state["motion_unlock_ready"])

    def test_unlock_requires_explicit_confirmation(self):
        body, status = self.post(gui.motion_lock, {"action": "unlock"})
        self.assertEqual(status, 400)
        self.assertFalse(gui._motion_allowed())
        self.assertFalse(any(item[0] == "enable" for item in self.fake.calls))

    def test_unlock_rejects_unknown_motor_mode(self):
        gui._motors[0]["control_mode_key"] = None
        body, status = self.unlock()
        self.assertEqual(status, 409)
        self.assertIn("mode", body["error"])
        self.assertFalse(gui._motion_allowed())

    def test_unlock_rejects_enabled_motor(self):
        gui._tracks[1]["enabled"] = True
        _, status = self.unlock()
        self.assertEqual(status, 409)

    def test_unlock_is_only_permission_not_enable(self):
        body, status = self.unlock()
        self.assertEqual(status, 200)
        self.assertTrue(body["state"]["motion_unlocked"])
        self.assertTrue(gui._motion_allowed())
        self.assertEqual(self.fake.calls, [])
        # The interlock must remain unlocked while motor is enabled.
        gui._tracks[1]["enabled"] = True
        self.assertTrue(gui._motion_allowed())

    def test_lock_stops_tracking_and_sends_disable(self):
        self.unlock()
        gui._tracks[1]["enabled"] = True
        gui._tracks[1]["spin_dir"] = 1
        body, status = self.post(gui.motion_lock, {"action": "lock"})
        self.assertEqual(status, 200)
        self.assertFalse(body["state"]["motion_unlocked"])
        self.assertFalse(gui._tracks[1]["enabled"])
        self.assertEqual(gui._tracks[1]["spin_dir"], 0)
        self.assertIn(("disable", 1), self.fake.calls)
        self.assertEqual(body["warnings"], [])

    def test_disable_timeout_keeps_software_lock_and_reports_warning(self):
        self.unlock()
        self.fake.disable_feedback = None
        body, status = self.post(gui.motion_lock, {"action": "lock"})
        self.assertEqual(status, 200)
        self.assertFalse(gui._motion_allowed())
        self.assertTrue(body["warnings"])

    def test_enable_denied_when_locked_and_verified_when_unlocked(self):
        body, status = self.post(gui.enable, {"ids": [1]})
        self.assertEqual(status, 409)
        self.assertNotIn(("enable", 1), self.fake.calls)
        self.unlock()
        body, status = self.post(gui.enable, {"ids": [1]})
        self.assertEqual(status, 200)
        self.assertIn(("enable", 1), self.fake.calls)
        self.assertTrue(body["state"]["motion_unlocked"])

    def test_enable_no_feedback_rolls_back(self):
        self.unlock()
        self.fake.enable = lambda mid: None
        with patch.object(gui.traceback, "print_exc"):
            body, status = self.post(gui.enable, {"ids": [1]})
        self.assertEqual(status, 500)
        self.assertIn("feedback", body["error"])
        self.assertFalse(gui._tracks[1]["enabled"])
        self.assertIn(("disable", 1), self.fake.calls)

    def test_position_and_raw_commands_guarded(self):
        _, status = self.post(gui.target, {"ids": [1], "rad": 1.25})
        self.assertEqual(status, 409)
        _, status = self.post(gui.command, {
            "ids": [1], "mode": "servo", "command": {"position": 1.25}
        })
        self.assertEqual(status, 409)
        self.assertFalse(any(call[0] == "send_command" for call in self.fake.calls))
        self.unlock()
        _, status = self.post(gui.command, {
            "ids": [1], "mode": "torque_position", "command": {"position": 1.25}
        })
        self.assertEqual(status, 409)

    def test_rescan_automatically_relocks(self):
        self.unlock()
        body, status = self.post(gui.scan, {})
        self.assertEqual(status, 200)
        self.assertFalse(body["state"]["motion_unlocked"])
        self.assertIn(("disable", 1), self.fake.calls)

    def test_mode_change_automatically_relocks(self):
        self.unlock()
        body, status = self.post(gui.control_mode, {
            "ids": [1], "mode": "torque_position"
        })
        self.assertEqual(status, 200)
        self.assertFalse(body["state"]["motion_unlocked"])
        self.assertEqual(body["state"]["control_mode"], "torque_position")
        self.assertIn(("disable", 1), self.fake.calls)

    def test_disconnect_automatically_relocks(self):
        self.unlock()
        body, status = self.post(gui.disconnect, {})
        self.assertEqual(status, 200)
        self.assertFalse(gui._motion_allowed())
        self.assertFalse(self.fake.connected)
        self.assertIn(("disable", 1), self.fake.calls)

    def test_reconnect_does_not_inherit_unlock(self):
        self.unlock()
        body, status = self.post(gui.connect, {
            "adapter": "slcan", "channel": "COM10",
            "motor_model": "lande_pa043", "bus_profile": "classic_1m",
        })
        self.assertEqual(status, 200)
        self.assertFalse(body["state"]["motion_unlocked"])
        self.assertIn(("disable", 1), self.fake.calls)

    def test_damiao_behavior_unchanged(self):
        self.fake.motor_model = "damiao_6248p"
        self.assertTrue(gui._motion_allowed())
        _, status = self.unlock()
        self.assertEqual(status, 409)

    def test_relock_available_even_if_motion_guard_disallows_motion(self):
        self.unlock()
        gui._motors[0]["control_mode_key"] = None
        self.assertFalse(gui._motion_allowed())
        self.assertTrue(gui._state_payload()["motion_unlocked"])
        body, status = self.post(gui.motion_lock, {"action": "lock"})
        self.assertEqual(status, 200)
        self.assertFalse(body["state"]["motion_unlocked"])

    def test_scan_disable_failure_still_relocks_and_does_not_scan(self):
        self.unlock()
        self.fake.disable_feedback = None
        with patch.object(gui.traceback, "print_exc"):
            _, status = self.post(gui.scan, {})
        self.assertEqual(status, 500)
        self.assertFalse(gui._motion_allowed())
        self.assertFalse(any(call[0] == "scan" for call in self.fake.calls))


if __name__ == "__main__":
    print("PA043 GUI MOTION LOCK: OFFLINE STUB TESTS ONLY; NO MOTOR CONNECTED")
    unittest.main(verbosity=2)
