"""Isolated architecture tests: mocks only, no real USB/CAN drivers are opened."""
from __future__ import annotations

import ast
from collections import deque
from dataclasses import replace
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# These are intentional test doubles, never a runtime dependency fallback.
can_stub = types.ModuleType("can")

class Message:
    def __init__(self, arbitration_id=0, data=b"", is_extended_id=True,
                 is_fd=False, bitrate_switch=False, is_remote_frame=False,
                 is_error_frame=False, is_rx=True, dlc=None, **kwargs):
        self.arbitration_id = arbitration_id
        self.data = bytearray(data)
        self.is_extended_id = is_extended_id
        self.is_fd = is_fd
        self.bitrate_switch = bitrate_switch
        self.is_remote_frame = is_remote_frame
        self.is_error_frame = is_error_frame
        self.is_rx = is_rx
        self.dlc = len(data) if dlc is None else dlc

def forbidden_open(*args, **kwargs):
    raise AssertionError("A mock-only test tried to open real hardware")

can_stub.Message = Message
can_stub.Bus = forbidden_open
can_stub.detect_available_configs = lambda **kwargs: []
serial_stub = types.ModuleType("serial")
serial_stub.__path__ = []
serial_stub.Serial = forbidden_open
serial_tools = types.ModuleType("serial.tools")
serial_tools.__path__ = []
serial_ports = types.ModuleType("serial.tools.list_ports")
serial_ports.comports = lambda: []
serial_tools.list_ports = serial_ports
serial_stub.tools = serial_tools
sys.modules.update({"can": can_stub, "serial": serial_stub,
                    "serial.tools": serial_tools, "serial.tools.list_ports": serial_ports})

from can_profiles import BusProfile
from can_adapters import AdapterCapabilities, AdapterDevice
from can_adapters import registry as adapters
from can_adapters.usbcan_a import UsbCanAAdapter
from motors import get_motor_spec, list_motor_models, list_motor_brands
from motors.registry import MotorSpec
from motors.damiao import DaMiao6248PBackend, DaMiao8009PBackend
from motors.damiao.models import J6248P, J8009P
from motor_service import MotorService

class FakeBus:
    def __init__(self):
        self.sent = []
        self.rx = deque()
        self.closed = False
    def send(self, msg, timeout=None):
        self.sent.append(msg)
    def recv(self, timeout=None):
        return self.rx.popleft() if self.rx else None
    def shutdown(self):
        self.closed = True


def backend_with_mock(cls):
    b = cls.__new__(cls)
    b.bus = FakeBus()
    b._txn_lock = threading.RLock()
    motor = Mock()
    motor.motor_id = 1
    motor.motor_type = cls.motor_type
    motor.get_states.return_value = {}
    b.controller = Mock()
    b.controller.motors = {1: motor}
    b.controller._motors_by_feedback = {1: motor}
    b.controller.get_motor.return_value = motor
    return b, motor


class ProfileContractTests(unittest.TestCase):
    def test_public_profile_alias(self):
        from motors import BusProfile as old
        self.assertIs(old, BusProfile)

    def test_legacy_keys_preserved(self):
        models = {m["key"] for m in list_motor_models()}
        self.assertEqual(models, {"damiao_6248p", "damiao_8009p", "lande_pa043"})

    def test_vendor_grouping(self):
        self.assertEqual(list_motor_brands(), [
            {"key": "damiao", "name": "DaMiao"}, {"key": "lande", "name": "LANDA"}])
        self.assertEqual(get_motor_spec("damiao_8009p").brand, "damiao")

    def test_existing_profiles_and_bitrate_accessor(self):
        for model in list_motor_models():
            spec = get_motor_spec(model["key"])
            self.assertEqual(spec.default_bitrate, 1_000_000)
            self.assertEqual(model["default_bitrate"], spec.get_bus_profile().nominal_bitrate)

    def test_canfd_candidate_is_not_hardware_confirmation(self):
        p = get_motor_spec("damiao_8009p").get_bus_profile("canfd_1m_5m")
        self.assertFalse(p.implemented)
        self.assertEqual(p.evidence, "candidate_not_hardware_verified")
        self.assertIn("unverified", p.label)

    def test_mode_sets_preserved(self):
        self.assertEqual(J6248P.supported_modes, ("mit", "pos_vel", "vel", "force_pos"))
        self.assertEqual(J8009P.supported_modes, ("mit", "pos_vel", "vel"))

    def test_invalid_profiles(self):
        for data in (0, -1, None):
            with self.subTest(data=data), self.assertRaises((TypeError, ValueError)):
                BusProfile("test", "Test", True, 1_000_000, data)
        with self.assertRaises(ValueError):
            BusProfile("test", "Test", False, 1_000_000, 5_000_000)
        with self.assertRaises(TypeError):
            BusProfile("test", "Test", False, True)

    def test_duplicate_profile_key(self):
        s = get_motor_spec("damiao_6248p")
        with self.assertRaises(ValueError):
            replace(s, bus_profiles=(s.get_bus_profile(), s.get_bus_profile()))

    def test_unknown_profile(self):
        with self.assertRaises(ValueError):
            get_motor_spec("lande_pa043").get_bus_profile("canfd_1m_5m")

    def test_mapping_references_are_model_specific(self):
        self.assertEqual(J6248P.mapping_reference, (12.566, 20.0, 120.0))
        self.assertEqual(J8009P.mapping_reference, (12.5, 45.0, 54.0))


class AdapterContractTests(unittest.TestCase):
    def test_categories_not_adapter_brands(self):
        result = {a["key"]: a for a in adapters.list_adapter_types()}
        self.assertEqual(result["gs_usb"]["backend_kind"], "direct_usb")
        self.assertEqual(result["socketcan"]["backend_kind"], "os_stack")
        self.assertTrue(all(not a["capabilities"]["can_fd"] for a in result.values()))

    def test_ch340_only_candidate(self):
        port = types.SimpleNamespace(device="COM7", vid=0x1A86, pid=0x7523,
                                     description="USB-SERIAL CH340", hwid="USB VID:PID=1A86:7523")
        with patch.object(serial_ports, "comports", return_value=[port]):
            device, = UsbCanAAdapter().discover()
        self.assertFalse(device.auto_selectable)
        self.assertEqual(device.hardware_family, "ch340_serial")
        self.assertIn("unverified", device.label)

    def test_auto_does_not_choose_ch340(self):
        d = AdapterDevice("usbcan_a", "COM7", "Candidate", "serial", auto_selectable=False)
        candidates = {"usbcan_a": Mock(transport="serial", supported=lambda: True,
                                      discover=lambda: [d])}
        with patch.dict(adapters._ADAPTERS, candidates, clear=True):
            with self.assertRaises(RuntimeError):
                adapters.resolve_adapter("auto", "COM7")
            with self.assertRaises(RuntimeError):
                adapters.resolve_adapter("auto")

    def test_explicit_waveshare_selection_kept(self):
        with patch.object(UsbCanAAdapter, "supported", return_value=True):
            self.assertEqual(adapters.resolve_adapter("usbcan_a", "COM7"), ("usbcan_a", "COM7"))

    def test_unidentified_serials_are_still_listed(self):
        port = types.SimpleNamespace(device="COM99", description="UART", hwid="other")
        with patch.dict(adapters._ADAPTERS, {}, clear=True), patch.object(serial_ports, "comports", return_value=[port]):
            d, = adapters.discover_all()
        self.assertEqual(d.adapter, "unknown_serial")
        self.assertFalse(d.auto_selectable)

    def test_direct_fd_open_rejected_before_discovery(self):
        with patch.object(adapters, "resolve_adapter", side_effect=AssertionError("must not enumerate")):
            with self.assertRaisesRegex(RuntimeError, "CAN-FD"):
                adapters.open_can_bus("usbcan_a", "COM7", fd=True, data_bitrate=5_000_000)

    def test_classic_data_rate_is_rejected(self):
        with self.assertRaises(ValueError):
            adapters.open_can_bus("usbcan_a", "COM7", data_bitrate=5_000_000)

    def test_classic_wrapper_rejects_fd_and_brs(self):
        raw = FakeBus()
        b = adapters.ThreadSafeBus(raw, adapter_kind="test", channel=0)
        for msg in (Message(data=b"1", is_fd=True), Message(data=b"1", bitrate_switch=True), Message(data=b"1"*9)):
            with self.subTest(msg=msg), self.assertRaises(ValueError):
                b.send(msg)
        self.assertEqual(raw.sent, [])

    def test_classic_open_preserves_backend_call(self):
        raw = FakeBus()
        backend = adapters.get_adapter("usbcan_a")
        with patch.object(backend, "open", return_value=raw) as opened:
            b = adapters.open_can_bus("usbcan_a", "COM7")
        opened.assert_called_once_with("COM7", 1_000_000)
        b.send(Message(data=b"123", is_extended_id=False))
        self.assertEqual(len(raw.sent), 1)

    def test_direct_backend_failure_does_not_claim_connected(self):
        backend = adapters.get_adapter("usbcan_a")
        with patch.object(backend, "open", side_effect=RuntimeError("open failed")):
            with self.assertRaises(RuntimeError):
                adapters.open_can_bus("usbcan_a", "COM7")


class ServiceContractTests(unittest.TestCase):
    def test_catalog_without_discovery(self):
        with patch("motor_service.list_adapter_devices", side_effect=AssertionError("discovery")):
            result = MotorService.capabilities(include_devices=False)
        self.assertEqual(result["devices"], [])
        self.assertEqual(len(result["brands"]), 2)

    def test_fd_profile_does_not_open_or_disconnect(self):
        s = MotorService()
        with patch("motor_service.open_can_bus", side_effect=AssertionError("open")), \
             patch("motor_service.resolve_adapter", side_effect=AssertionError("discover")), \
             patch.object(s, "disconnect", side_effect=AssertionError("disconnect")):
            with self.assertRaisesRegex(RuntimeError, "not implemented"):
                s.connect(adapter="usbcan_a", channel="COM7", motor_model="damiao_8009p", bus_profile="canfd_1m_5m")

    def test_fd_flag_alone_cannot_enable_protocol(self):
        original = get_motor_spec("damiao_8009p")
        candidate = replace(original.get_bus_profile("canfd_1m_5m"), implemented=True)
        spec = replace(original, bus_profiles=(candidate,), default_bus_profile=candidate.key)
        with patch("motor_service.get_motor_spec", return_value=spec), \
             patch("motor_service.open_can_bus", side_effect=AssertionError("open")):
            with self.assertRaisesRegex(RuntimeError, "protocol binding"):
                MotorService().connect(adapter="usbcan_a", channel="COM7", motor_model=spec.key)

    def test_bitrate_conflict_before_open(self):
        with patch("motor_service.open_can_bus", side_effect=AssertionError("open")):
            with self.assertRaises(ValueError):
                MotorService().connect(adapter="usbcan_a", channel="COM7", motor_model="lande_pa043", bitrate=500_000)

    def test_legacy_connection_signature_defaults_to_classic(self):
        s = MotorService()
        bus = FakeBus()
        with patch("motor_service.open_can_bus", return_value=bus) as opened:
            info = s.connect(adapter="usbcan_a", channel="COM7", motor_model="lande_pa043")
        self.assertEqual(info["bus_profile"], "classic_1m")
        self.assertEqual(info["connection_state"], "adapter_open")
        self.assertEqual(opened.call_args.kwargs["fd"], False)
        self.assertEqual(bus.sent, [])
        s.disconnect()
        self.assertTrue(bus.closed)

    def test_default_motion_lock_unchanged(self):
        self.assertFalse(get_motor_spec("lande_pa043").motion_safe_default)


class MotorContractTests(unittest.TestCase):
    def test_old_lande_import_is_same_class(self):
        import lande_motor
        from motors.lande.protocol import LandeMotor
        from motors.lande import LandeBackend
        self.assertIs(lande_motor.LandeMotor, LandeMotor)
        self.assertEqual(LandeBackend.model_key, "lande_pa043")
        self.assertEqual(lande_motor._float_to_uint(12.5, -12.5, 12.5, 16), 65535)

    def test_registration_idempotent_on_reimport(self):
        import importlib
        import motors
        before = list_motor_models()
        importlib.reload(motors)
        self.assertEqual(before, list_motor_models())

    def test_pa043_frame_bytes_preserved(self):
        from lande_motor import LandeMotor
        bus = FakeBus()
        m = LandeMotor(bus, 1)
        m.disable(feedback_timeout=0)
        self.assertEqual(bytes(bus.sent[-1].data), bytes([255]*7+[253]))
        self.assertEqual(bus.sent[-1].arbitration_id, 1)
        m.save_parameters()
        self.assertEqual(bytes(bus.sent[-1].data), bytes.fromhex("67 00 00 00 00 00 00 76"))
        self.assertEqual(bus.sent[-1].arbitration_id, 0x601)

    def test_pa043_destructive_commands_guarded(self):
        from lande_motor import LandeMotor
        bus = FakeBus()
        m = LandeMotor(bus, 1)
        for func in (m.restore_defaults, m.start_electric_angle_calibration):
            with self.assertRaises(ValueError): func()
        self.assertEqual(bus.sent, [])

    def test_damiao_8009_force_pos_still_rejected(self):
        b, motor = backend_with_mock(DaMiao8009PBackend)
        with self.assertRaises(ValueError): b.send_command(1, "force_pos")
        motor.send_cmd_force_pos.assert_not_called()

    def test_damiao_shared_mode_dispatch(self):
        for cls in (DaMiao6248PBackend, DaMiao8009PBackend):
            b, m = backend_with_mock(cls)
            b.send_command(1, "pos_vel", position=1.25, velocity_limit=2.5)
            m.send_cmd_pos_vel.assert_called_once_with(target_position=1.25, velocity_limit=2.5)
            b.send_command(1, "vel", velocity=-0.1)
            m.send_cmd_vel.assert_called_once_with(target_velocity=-0.1)

    def test_enable_does_not_rewrite_mode(self):
        b, m = backend_with_mock(DaMiao6248PBackend)
        b.enable(1)
        m.enable.assert_called_once()
        m.ensure_control_mode.assert_not_called()

    def test_6248_force_pos_limits(self):
        b, m = backend_with_mock(DaMiao6248PBackend)
        b.send_command(1, "force_pos", position=.5, velocity_limit=1.2, torque_limit_ratio=.25)
        m.send_cmd_force_pos.assert_called_once_with(target_position=.5, velocity_limit=1.2, torque_limit_ratio=.25)
        with self.assertRaises(ValueError): b.send_command(1, "force_pos", torque_limit_ratio=1.1)

    def test_scan_has_no_motion_command_fallback(self):
        b, m = backend_with_mock(DaMiao6248PBackend)
        m.request_motor_feedback.side_effect = RuntimeError("unsupported")
        b._ensure_motor = lambda mid: m
        with self.assertRaisesRegex(RuntimeError, "no motion-command fallback"):
            b.scan(1, 1)
        m.send_cmd_mit.assert_not_called()
        m.enable.assert_not_called()

    def test_scan_range_unchanged(self):
        b, _ = backend_with_mock(DaMiao6248PBackend)
        for start,end in ((0,1),(1,16),(2,1)):
            with self.assertRaises(ValueError): b.scan(start,end)


class LayoutContractTests(unittest.TestCase):
    def test_no_uart_or_empty_fd_runtime_added(self):
        self.assertFalse((ROOT/"motors/damiao/uart.py").exists())
        self.assertFalse((ROOT/"motors/damiao/canfd.py").exists())

    def test_flat_modules_removed(self):
        self.assertFalse((ROOT/"motors/damiao.py").exists())
        self.assertFalse((ROOT/"motors/lande.py").exists())

    def test_gui_profile_and_vendor_fields_present(self):
        html = (ROOT/"templates/custom_gui.html").read_text(encoding="utf-8")
        for term in ('id="motorBrand"','id="busProfile"','bus_profile:$("busProfile").value', 'id="dial"'):
            self.assertIn(term,html)

    def test_flask_route_names_preserved(self):
        tree=ast.parse((ROOT/"gui_server.py").read_text(encoding="utf-8"))
        routes={d.args[0].value for f in tree.body if isinstance(f,ast.FunctionDef)
                for d in f.decorator_list if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute)
                and d.func.attr=="route" and d.args and isinstance(d.args[0],ast.Constant)}
        expected={"/", "/api/capabilities", "/api/state", "/api/connect", "/api/disconnect",
                  "/api/scan", "/api/select", "/api/control_mode", "/api/settings", "/api/enable",
                  "/api/disable", "/api/target", "/api/spin", "/api/command"}
        self.assertTrue(expected.issubset(routes), expected-routes)


if __name__ == "__main__":
    print("ISOLATED CONTRACT TESTS: test doubles only; no hardware or dependency integration proof.", flush=True)
    unittest.main(verbosity=2)
