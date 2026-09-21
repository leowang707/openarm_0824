from __future__ import annotations

import math
import os
import threading
import time
import traceback
from typing import Any

from flask import Flask, jsonify, render_template, request

from motor_service import MotorService
from motors import get_motor_spec


TWO_PI = 2.0 * math.pi
CMD_HZ = 25.0
MAX_SPEED_DEG_S = 60.0
DEFAULT_SPEED_DEG_S = 18.0
DEFAULT_KP = 4.0
DEFAULT_KD = 2.0
POSITION_LIMIT_RAD = 12.0
POSITION_MODES = {"mit", "pos_vel", "servo", "torque_position"}

_template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
app = Flask(__name__, template_folder=_template_dir)

_lock = threading.RLock()
_service = MotorService()
_motors: list[dict[str, Any]] = []
_tracks: dict[int, dict[str, Any]] = {}
_selected_ids: list[int] = []
_focus_id: int | None = None
_control_mode = ""
_max_speed_rad_s = math.radians(DEFAULT_SPEED_DEG_S)
_kp = DEFAULT_KP
_kd = DEFAULT_KD
_errors: list[dict[str, Any]] = []
_error_seq = 0
_loop_thread: threading.Thread | None = None
_loop_stop = threading.Event()

# PA043 stays motion-locked by default. Set ALLOW_PA043_MOTION=1 only after
# validating feedback and safe hold behavior on the bench.
ALLOW_PA043_MOTION = os.environ.get("ALLOW_PA043_MOTION", "0") == "1"


def _json_error(message: str, status: int = 400):
    return jsonify({"success": False, "error": str(message)}), status


def _motor_model() -> str | None:
    return _service.motor_model


def _motion_allowed() -> bool:
    model = _motor_model()
    if not model:
        return False
    if model == "lande_pa043":
        return ALLOW_PA043_MOTION
    return bool(get_motor_spec(model).motion_safe_default)


def _position_mode() -> bool:
    return _control_mode in POSITION_MODES


def _motor_map() -> dict[int, dict[str, Any]]:
    return {int(item["id"]): item for item in _motors}


def _safe_state(mid: int) -> dict[str, Any]:
    try:
        return dict(_service.get_state(mid) or {})
    except Exception:
        return {}


def _state_pos(state: dict[str, Any]) -> float | None:
    value = state.get("pos")
    if value is None:
        value = state.get("position")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _deg_mod(pos: float | None) -> float | None:
    if pos is None:
        return None
    return (math.degrees(float(pos)) % 360.0 + 360.0) % 360.0


def _nearest_target(current: float, clicked_deg: float) -> float:
    clicked = math.radians(float(clicked_deg) % 360.0)
    current_mod = current % TWO_PI
    delta = (clicked - current_mod + math.pi) % TWO_PI - math.pi
    return max(-POSITION_LIMIT_RAD, min(POSITION_LIMIT_RAD, current + delta))


def _note_error(message: str) -> None:
    global _error_seq
    text = str(message).strip() or "unknown error"
    print("[gui]", text, flush=True)
    with _lock:
        _error_seq += 1
        _errors.append({"seq": _error_seq, "msg": text, "t": time.strftime("%H:%M:%S")})
        del _errors[:-20]


def _track_from_state(mid: int, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = previous or {}
    state = _safe_state(mid)
    pos = _state_pos(state)
    if pos is None:
        pos = previous.get("cmd_pos")
    return {
        "enabled": bool(previous.get("enabled", False)),
        "cmd_pos": pos,
        "target_pos": previous.get("target_pos", pos),
        "spin_dir": int(previous.get("spin_dir", 0) or 0),
        "fail": int(previous.get("fail", 0) or 0),
    }


def _reset_tracks(
    *,
    keep_selected: list[int] | None = None,
    prefer_focus: int | None = None,
    preserve_enabled: bool = False,
) -> None:
    global _tracks, _selected_ids, _focus_id

    found_ids = [int(item["id"]) for item in _motors]
    old = _tracks
    new_tracks: dict[int, dict[str, Any]] = {}

    for mid in found_ids:
        previous = old.get(mid, {})
        track = _track_from_state(mid, previous)
        if not preserve_enabled:
            track["enabled"] = False
            track["spin_dir"] = 0
        new_tracks[mid] = track

    _tracks = new_tracks

    desired = keep_selected if keep_selected is not None else _selected_ids
    _selected_ids = [mid for mid in desired if mid in _tracks]
    if not _selected_ids and found_ids:
        _selected_ids = [found_ids[0]]

    if prefer_focus in _tracks:
        _focus_id = prefer_focus
    elif _focus_id not in _tracks:
        _focus_id = _selected_ids[0] if _selected_ids else None


def _motors_payload() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for info in _motors:
        mid = int(info["id"])
        state = _safe_state(mid)
        track = _tracks.get(mid, {})
        item = dict(info)
        item.update(state)
        pos = _state_pos(item)
        if pos is None:
            pos = track.get("cmd_pos")
        target = track.get("target_pos")
        item.update(
            {
                "id": mid,
                "selected": mid in _selected_ids,
                "focused": mid == _focus_id,
                "enabled": bool(track.get("enabled")),
                "spinning": bool(track.get("spin_dir")),
                "pos": pos,
                "pos_deg_mod": _deg_mod(pos),
                "target_rad": target,
                "target_deg_mod": _deg_mod(target),
            }
        )
        out.append(item)
    return out


def _state_payload() -> dict[str, Any]:
    info = _service.connection_info()
    model = info.get("motor_model")
    spec = get_motor_spec(model) if model else None

    focus_state = _safe_state(_focus_id) if _focus_id is not None else {}
    focus_track = _tracks.get(_focus_id, {}) if _focus_id is not None else {}
    focus_pos = _state_pos(focus_state)
    if focus_pos is None:
        focus_pos = focus_track.get("cmd_pos")
    focus_target = focus_track.get("target_pos")

    enabled_ids = [mid for mid, tr in _tracks.items() if tr.get("enabled")]
    spinning_ids = [mid for mid, tr in _tracks.items() if tr.get("spin_dir")]

    return {
        **info,
        "motor_model_name": spec.name if spec else None,
        "motor_brand": spec.brand if spec else None,
        "supported_modes": list(spec.supported_modes) if spec else [],
        "motion_allowed": _motion_allowed(),
        "dial_allowed": _motion_allowed() and _position_mode(),
        "control_mode": _control_mode,
        "selected_ids": list(_selected_ids),
        "focus_id": _focus_id,
        "enabled_ids": enabled_ids,
        "spinning_ids": spinning_ids,
        "spinning": bool(spinning_ids),
        "motors": _motors_payload(),
        "focus_state": focus_state,
        "pos_rad": focus_pos,
        "pos_deg_mod": _deg_mod(focus_pos),
        "target_rad": focus_target,
        "target_deg_mod": _deg_mod(focus_target),
        "cmd_rad": focus_track.get("cmd_pos"),
        "max_deg_s": math.degrees(_max_speed_rad_s),
        "kp": _kp,
        "kd": _kd,
        "errors": list(_errors),
        "error_seq": _error_seq,
    }


def _parse_ids(data: dict[str, Any]) -> list[int]:
    raw = data.get("ids")
    if raw is None and data.get("id") is not None:
        raw = [data.get("id")]
    if raw is None:
        raw = list(_selected_ids)

    result: list[int] = []
    seen: set[int] = set()
    valid = set(_motor_map())
    for value in raw:
        mid = int(value)
        if mid in seen or mid not in valid:
            continue
        seen.add(mid)
        result.append(mid)
    return result


def _choose_control_mode() -> str:
    spec = get_motor_spec(_service.motor_model) if _service.motor_model else None
    if spec is None:
        return ""

    if _focus_id is not None:
        info = _motor_map().get(_focus_id, {})
        key = info.get("control_mode_key")
        if key in spec.supported_modes:
            return str(key)

    return str(spec.supported_modes[0]) if spec.supported_modes else ""


def _rescan(start_id: int | None = None, end_id: int | None = None) -> list[dict[str, Any]]:
    global _motors, _control_mode
    keep_selected = list(_selected_ids)
    prefer_focus = _focus_id
    _motors = _service.scan(start_id, end_id)
    _reset_tracks(
        keep_selected=keep_selected,
        prefer_focus=prefer_focus,
        preserve_enabled=False,
    )
    _control_mode = _choose_control_mode()
    return _motors


def _position_command_kwargs(mode: str, position: float, velocity: float) -> dict[str, float]:
    if mode == "mit":
        return {
            "position": position,
            "velocity": velocity,
            "torque": 0.0,
            "kp": _kp,
            "kd": _kd,
        }
    if mode == "pos_vel":
        return {
            "position": position,
            "velocity_limit": _max_speed_rad_s,
        }
    if mode == "servo":
        return {
            "position": position,
            "velocity": velocity,
            "pos_kp": _kp,
            "pos_kd": _kd,
            "vel_kp": 0.0,
            "vel_kd": 0.0,
            "vel_ki": 0.0,
            "feedback_timeout": 0.01,
        }
    if mode == "torque_position":
        return {
            "position": position,
            "velocity": velocity,
            "pos_kp": _kp,
            "pos_kd": _kd,
            "torque": 0.0,
            "feedback_timeout": 0.01,
        }
    raise ValueError(f"Control mode {mode!r} is not a position/dial mode")


def _control_loop() -> None:
    dt = 1.0 / CMD_HZ

    while not _loop_stop.is_set():
        t0 = time.perf_counter()

        try:
            with _lock:
                if _service.connected and _motion_allowed() and _position_mode():
                    step = _max_speed_rad_s * dt

                    for mid, track in list(_tracks.items()):
                        if not track.get("enabled"):
                            continue

                        cmd = track.get("cmd_pos")
                        if cmd is None:
                            cmd = _state_pos(_safe_state(mid))
                            if cmd is not None:
                                track["cmd_pos"] = cmd

                        spin_dir = int(track.get("spin_dir", 0) or 0)
                        target = track.get("target_pos")

                        if spin_dir:
                            if cmd is None:
                                cmd = 0.0

                            direction = 1 if spin_dir > 0 else -1
                            next_cmd = float(cmd) + direction * step

                            if next_cmd >= POSITION_LIMIT_RAD:
                                next_cmd = POSITION_LIMIT_RAD
                                direction = -1
                            elif next_cmd <= -POSITION_LIMIT_RAD:
                                next_cmd = -POSITION_LIMIT_RAD
                                direction = 1

                            velocity = direction * _max_speed_rad_s
                            track["spin_dir"] = direction
                            track["target_pos"] = next_cmd

                        elif target is not None:
                            if cmd is None:
                                cmd = float(target)

                            error = float(target) - float(cmd)
                            if abs(error) <= step:
                                next_cmd = float(target)
                                velocity = 0.0
                            else:
                                direction = 1.0 if error > 0.0 else -1.0
                                next_cmd = float(cmd) + direction * step
                                velocity = direction * _max_speed_rad_s
                        else:
                            continue

                        try:
                            _service.send_command(
                                mid,
                                _control_mode,
                                **_position_command_kwargs(
                                    _control_mode,
                                    next_cmd,
                                    velocity,
                                ),
                            )
                            track["cmd_pos"] = next_cmd
                            track["fail"] = 0

                        except Exception as exc:
                            track["fail"] = int(track.get("fail", 0)) + 1
                            if track["fail"] >= 3:
                                track["enabled"] = False
                                track["spin_dir"] = 0
                            _note_error(f"Motor {mid} command failed: {exc}")

        except Exception as exc:
            _note_error(f"Control loop failed: {exc}")

        elapsed = time.perf_counter() - t0
        _loop_stop.wait(max(0.001, dt - elapsed))


def _ensure_loop() -> None:
    global _loop_thread
    if _loop_thread is not None and _loop_thread.is_alive():
        return
    _loop_stop.clear()
    _loop_thread = threading.Thread(
        target=_control_loop,
        name="motor-gui-control",
        daemon=True,
    )
    _loop_thread.start()


@app.route("/")
def index():
    return render_template("custom_gui.html")


@app.route("/api/capabilities")
def capabilities():
    return jsonify({"success": True, **MotorService.capabilities(include_devices=request.args.get("devices", "1") != "0")})


@app.route("/api/state")
def state():
    with _lock:
        return jsonify({"success": True, "state": _state_payload()})


@app.route("/api/connect", methods=["POST"])
def connect():
    global _motors, _tracks, _selected_ids, _focus_id, _control_mode
    data = request.get_json(silent=True) or {}
    adapter = str(data.get("adapter") or "").strip()
    channel = data.get("channel")
    motor_model = str(data.get("motor_model") or "").strip()
    bus_profile = str(data.get("bus_profile") or "").strip() or None

    if not adapter:
        return _json_error("adapter is required")
    if not motor_model:
        return _json_error("motor_model is required")

    try:
        with _lock:
            _ensure_loop()
            _service.connect(
                adapter=adapter,
                channel=channel,
                motor_model=motor_model,
                bus_profile=bus_profile,
            )
            _motors = []
            _tracks = {}
            _selected_ids = []
            _focus_id = None
            _control_mode = ""
            _rescan()
            payload = _state_payload()
        return jsonify({"success": True, "state": payload})
    except Exception as exc:
        traceback.print_exc()
        with _lock:
            _service.disconnect()
            _motors = []
            _tracks = {}
            _selected_ids = []
            _focus_id = None
            _control_mode = ""
        return _json_error(f"Connect failed: {exc}", 500)


@app.route("/api/disconnect", methods=["POST"])
def disconnect():
    global _motors, _tracks, _selected_ids, _focus_id, _control_mode
    with _lock:
        _service.disconnect()
        _motors = []
        _tracks = {}
        _selected_ids = []
        _focus_id = None
        _control_mode = ""
    return jsonify({"success": True})


@app.route("/api/scan", methods=["POST"])
def scan():
    data = request.get_json(silent=True) or {}
    if not _service.connected:
        return _json_error("Not connected")

    start_id = data.get("start_id")
    end_id = data.get("end_id")

    try:
        with _lock:
            _rescan(
                None if start_id is None else int(start_id),
                None if end_id is None else int(end_id),
            )
            payload = _state_payload()
        return jsonify({"success": True, "state": payload})
    except Exception as exc:
        traceback.print_exc()
        return _json_error(f"Scan failed: {exc}", 500)


@app.route("/api/select", methods=["POST"])
def select():
    global _selected_ids, _focus_id
    data = request.get_json(silent=True) or {}
    with _lock:
        ids = _parse_ids(data)
        _selected_ids = ids

        focus = data.get("focus")
        if focus is not None and int(focus) in _motor_map():
            _focus_id = int(focus)
        elif _focus_id not in _motor_map():
            _focus_id = ids[0] if ids else None

        return jsonify({"success": True, "state": _state_payload()})


@app.route("/api/control_mode", methods=["POST"])
def control_mode():
    global _control_mode, _motors
    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode") or "").strip()
    ids = _parse_ids(data)

    if not ids:
        return _json_error("Select at least one motor")
    if not mode:
        return _json_error("mode is required")

    try:
        with _lock:
            for mid in ids:
                _service.set_control_mode(mid, mode, save=True)
                if mid in _tracks:
                    _tracks[mid]["enabled"] = False
                    _tracks[mid]["spin_dir"] = 0

            _control_mode = mode
            spec = get_motor_spec(_service.motor_model)
            _motors = _service.scan(spec.default_scan_start, spec.default_scan_end)
            _reset_tracks(
                keep_selected=ids,
                prefer_focus=_focus_id,
                preserve_enabled=False,
            )
            payload = _state_payload()

        return jsonify({"success": True, "state": payload})
    except Exception as exc:
        traceback.print_exc()
        return _json_error(f"Mode change failed: {exc}", 500)


@app.route("/api/settings", methods=["POST"])
def settings():
    global _kp, _kd, _max_speed_rad_s
    data = request.get_json(silent=True) or {}

    with _lock:
        if "kp" in data:
            _kp = max(0.0, min(250.0, float(data["kp"])))
        if "kd" in data:
            _kd = max(0.0, min(50.0, float(data["kd"])))
        if "max_deg_s" in data:
            deg_s = max(1.0, min(MAX_SPEED_DEG_S, float(data["max_deg_s"])))
            _max_speed_rad_s = math.radians(deg_s)

        return jsonify({"success": True, "state": _state_payload()})


@app.route("/api/enable", methods=["POST"])
def enable():
    data = request.get_json(silent=True) or {}
    ids = _parse_ids(data)

    if not ids:
        return _json_error("Select at least one motor")
    if not _motion_allowed():
        return _json_error(
            "Motion is locked for this motor model. For PA043, validate real feedback first; "
            "then start the server with ALLOW_PA043_MOTION=1.",
            409,
        )

    try:
        with _lock:
            for mid in ids:
                _service.enable(mid)
                track = _tracks.setdefault(mid, _track_from_state(mid))
                pos = _state_pos(_safe_state(mid))
                if pos is not None:
                    track["cmd_pos"] = pos
                    track["target_pos"] = pos
                track["enabled"] = True
                track["spin_dir"] = 0
                track["fail"] = 0
            payload = _state_payload()

        return jsonify({"success": True, "state": payload})
    except Exception as exc:
        traceback.print_exc()
        return _json_error(f"Enable failed: {exc}", 500)


@app.route("/api/disable", methods=["POST"])
def disable():
    data = request.get_json(silent=True) or {}
    ids = _parse_ids(data)

    try:
        with _lock:
            for mid in ids:
                _service.disable(mid)
                if mid in _tracks:
                    _tracks[mid]["enabled"] = False
                    _tracks[mid]["spin_dir"] = 0
            payload = _state_payload()

        return jsonify({"success": True, "state": payload})
    except Exception as exc:
        traceback.print_exc()
        return _json_error(f"Disable failed: {exc}", 500)


@app.route("/api/target", methods=["POST"])
def target():
    data = request.get_json(silent=True) or {}
    ids = _parse_ids(data)

    if not ids:
        return _json_error("Select at least one motor")
    if not _motion_allowed():
        return _json_error("Motion is locked for this motor model", 409)
    if not _position_mode():
        return _json_error(
            f"Dial requires a position-capable mode: {', '.join(sorted(POSITION_MODES))}",
            409,
        )

    if data.get("deg") is None and data.get("rad") is None:
        return _json_error("deg or rad is required")

    try:
        with _lock:
            for mid in ids:
                track = _tracks.setdefault(mid, _track_from_state(mid))
                track["spin_dir"] = 0

                current = _state_pos(_safe_state(mid))
                if current is None:
                    current = track.get("cmd_pos")
                if current is None:
                    current = 0.0

                if data.get("rad") is not None:
                    target_pos = float(data["rad"])
                    target_pos = max(
                        -POSITION_LIMIT_RAD,
                        min(POSITION_LIMIT_RAD, target_pos),
                    )
                else:
                    target_pos = _nearest_target(current, float(data["deg"]))

                track["target_pos"] = target_pos
                if track.get("cmd_pos") is None:
                    track["cmd_pos"] = current

            payload = _state_payload()

        return jsonify({"success": True, "state": payload})
    except Exception as exc:
        traceback.print_exc()
        return _json_error(f"Target update failed: {exc}", 500)


@app.route("/api/spin", methods=["POST"])
def spin():
    data = request.get_json(silent=True) or {}
    ids = _parse_ids(data)
    want = bool(data.get("enabled", True))
    direction = 1 if int(data.get("direction", 1)) >= 0 else -1

    if not ids:
        return _json_error("Select at least one motor")
    if not _motion_allowed():
        return _json_error("Motion is locked for this motor model", 409)
    if not _position_mode():
        return _json_error("Spin requires MIT/servo/torque_position mode", 409)

    with _lock:
        if want:
            not_enabled = [mid for mid in ids if not _tracks.get(mid, {}).get("enabled")]
            if not_enabled:
                return _json_error(
                    "Enable selected motors before starting spin: "
                    + ", ".join(str(mid) for mid in not_enabled)
                )

            for mid in ids:
                track = _tracks[mid]
                if track.get("cmd_pos") is None:
                    pos = _state_pos(_safe_state(mid))
                    track["cmd_pos"] = 0.0 if pos is None else pos
                track["target_pos"] = track["cmd_pos"]
                track["spin_dir"] = direction

        else:
            for mid in ids:
                if mid in _tracks:
                    track = _tracks[mid]
                    track["spin_dir"] = 0

                    current = _state_pos(_safe_state(mid))
                    if current is None:
                        current = track.get("cmd_pos")

                    track["cmd_pos"] = current
                    track["target_pos"] = current

        return jsonify({"success": True, "state": _state_payload()})


@app.route("/api/command", methods=["POST"])
def command():
    data = request.get_json(silent=True) or {}
    ids = _parse_ids(data)
    mode = str(data.get("mode") or _control_mode).strip()
    command_data = dict(data.get("command") or {})

    if not ids:
        return _json_error("Select at least one motor")
    if not mode:
        return _json_error("mode is required")
    if not _motion_allowed():
        return _json_error("Motion is locked for this motor model", 409)

    results: dict[int, Any] = {}

    try:
        with _lock:
            for mid in ids:
                results[mid] = _service.send_command(mid, mode, **command_data)

                if mode in POSITION_MODES and "position" in command_data and mid in _tracks:
                    pos = float(command_data["position"])
                    _tracks[mid]["cmd_pos"] = pos
                    _tracks[mid]["target_pos"] = pos
                    _tracks[mid]["spin_dir"] = 0

            payload = _state_payload()

        return jsonify({"success": True, "results": results, "state": payload})
    except Exception as exc:
        traceback.print_exc()
        return _json_error(f"Command failed: {exc}", 500)


def run_server(host: str = "127.0.0.1", port: int = 5000) -> None:
    _ensure_loop()
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run_server()
