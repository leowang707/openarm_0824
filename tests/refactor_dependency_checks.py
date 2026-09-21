"""Real installed-library smoke tests; all CAN writes target FakeBus only."""
from __future__ import annotations
import ast
from importlib import metadata
from pathlib import Path
import struct
import sys
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import can
import serial
from damiao_motor.core.motor import DaMiaoMotor, MOTOR_TYPE_PRESETS
from motors.damiao import DaMiao6248PBackend, DaMiao8009PBackend
from motors.damiao.models import J6248P, J8009P

class FakeBus:
    adapter_kind = "test"
    def __init__(self): self.sent=[]
    def send(self,msg,timeout=None): self.sent.append(msg)
    def recv(self,timeout=None):
        time.sleep(.001)
        return None
    def shutdown(self): pass

class DependencyTests(unittest.TestCase):
    def test_installed_presets_match_reference(self):
        for model in (J6248P,J8009P):
            p=MOTOR_TYPE_PRESETS[model.sdk_motor_type]
            self.assertEqual((p["p_max"],p["v_max"],p["t_max"]),model.mapping_reference)

    def test_mit_and_float_payloads(self):
        for model in (J6248P,J8009P):
            b=FakeBus();m=DaMiaoMotor(1,0x11,b,motor_type=model.sdk_motor_type)
            p,v,t=model.mapping_reference
            m.send_cmd_mit(target_position=p,target_velocity=v,stiffness=500,damping=5,feedforward_torque=t)
            self.assertEqual(bytes(b.sent[-1].data),b"\xff"*8)
            self.assertFalse(b.sent[-1].is_extended_id)
            self.assertFalse(b.sent[-1].is_fd)
            m.send_cmd_pos_vel(target_position=1.25,velocity_limit=2.5)
            self.assertEqual(b.sent[-1].arbitration_id,0x101)
            self.assertEqual(bytes(b.sent[-1].data),struct.pack("<ff",1.25,2.5))
            m.send_cmd_vel(target_velocity=-3.0)
            self.assertEqual(b.sent[-1].arbitration_id,0x201)
            self.assertEqual(bytes(b.sent[-1].data),struct.pack("<f",-3.0)+b"\0"*4)

    def test_actual_controller_bus_injection(self):
        with patch("can.Bus",side_effect=AssertionError("unexpected hardware open")):
            for cls in (DaMiao6248PBackend,DaMiao8009PBackend):
                bus=FakeBus();b=cls(bus)
                try:
                    m=b._ensure_motor(1,feedback_id=0x11)
                    self.assertEqual(m.motor_type,cls.motor_type)
                    b.send_command(1,"vel",velocity=.1)
                    self.assertEqual(bus.sent[-1].arbitration_id,0x201)
                finally: b.shutdown()

    def test_6248_force_position_payload(self):
        b=FakeBus();m=DaMiaoMotor(1,0x11,b,motor_type="6248P")
        m.send_cmd_force_pos(target_position=.5,velocity_limit=1.2,torque_limit_ratio=.25)
        self.assertEqual(b.sent[-1].arbitration_id,0x301)
        self.assertEqual(bytes(b.sent[-1].data),struct.pack("<fHH",.5,120,2500))

    def test_flask_read_only_routes(self):
        import gui_server
        with patch("motor_service.list_adapter_devices",side_effect=AssertionError("unexpected discovery")):
            client=gui_server.app.test_client()
            self.assertEqual(client.get("/").status_code,200)
            r=client.get("/api/capabilities?devices=0")
            self.assertEqual(r.status_code,200)
            body=r.get_json()
            self.assertEqual({b["key"] for b in body["brands"]},{"damiao","lande"})
            self.assertEqual(len(body["motors"]),3)
            self.assertEqual(body["devices"],[])
            self.assertEqual(client.get("/api/state").status_code,200)

if __name__=="__main__":
    for name in ("python-can","pyserial","damiao-motor","Flask"):
        print(f"{name}={metadata.version(name)}",flush=True)
    unittest.main(verbosity=2)
