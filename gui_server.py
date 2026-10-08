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
DEFAULT_VEL_KP = 0.0
DEFAULT_VEL_KD = 0.0
DEFAULT_VEL_KI = 0.0

# GUI command defaults by motor model and active control mode.
# DaMiao values preserve the legacy master-branch MIT defaults.
# LANDA values follow the LDP043A01 vendor-manual recommendations.
CONTROL_DEFAULTS = {
    "damiao_6248p": {
        "mit": {"kp": 4.0, "kd": 2.0},
    },
    "damiao_8009p": {
        "mit": {"kp": 4.0, "kd": 2.0},
    },
    "lande_pa043": {
        "servo": {
            "kp": 5.0,
            "kd": 0.0,
            "vel_kp": 10.0,
            "vel_kd": 0.0,
            "vel_ki": 0.02,
        },
        "torque_position": {
            "kp": 3.0,
            "kd": 0.1,
        },
        "velocity": {
            "vel_kp": 1.0,
            "vel_kd": 0.0,
            "vel_ki": 0.002,
        },
    },
}

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
_vel_kp = DEFAULT_VEL_KP
_vel_kd = DEFAULT_VEL_KD
_vel_ki = DEFAULT_VEL_KI
_errors: list[dict[str, Any]] = []
_error_seq = 0
_loop_thread: threading.Thread | None = None
_loop_stop = threading.Event()

# PA043 motion permission is session-scoped and must be explicitly approved
# through the GUI. A leftover environment variable cannot bypass this lock.
_pa043_motion_unlocked = False
PA043_UNLOCK_CONFIRMATION = "I_ACCEPT_PA043_MOTION"


def _json_error(message: str, status: int = 400):
    return jsonify({"success": False, "error": str(message)}), status


def _motor_model() -> str | None:
    return _service.motor_model


def _motion_allowed() -> bool:
    model = _motor_model()
    if not model:
        return False
    if model == "lande_pa043":
        return _pa043_motion_unlocked and _pa043_unlock_blocker() is None
    return bool(get_motor_spec(model).motion_safe_default)


def _pa043_unlock_blocker(*, require_disabled: bool = False) -> str | None:
    """Fail closed if the connected PA043 and its true mode are not verified."""
    if not _service.connected or _service.motor_model != "lande_pa043":
        return "PA043 is not connected"
    if not _motors:
        return "No PA043 motor has been discovered"
    supported_modes = get_motor_spec("lande_pa043").supported_modes
    if _control_mode not in supported_modes:
        return "No supported PA043 control mode has been selected"
    for info in _motors:
        # _choose_control_mode can fall back to servo when the real motor mode
        # times out. Never use that fallback as evidence for unlocking motion.
        if info.get("control_mode_key") != _control_mode:
            return (
                f"Motor ID {info.get('id')} mode is unknown or differs from "
                f"selected mode {_control_mode!r}; rescan before unlocking"
            )
    if require_disabled and any(track.get("enabled") for track in _tracks.values()):
        return "Disable all motors before unlocking PA043 motion"
    return None


def _relock_pa043_motion(*, disable: bool = False) -> list[str]:
    """Under _lock: stop host commands first; optionally request motor disable.

    Warning strings mean the physical disable could not be verified. A host
    software lock is NOT an emergency stop or a hardware torque-off guarantee.
    """
    global _pa043_motion_unlocked
    previously_unlocked = _pa043_motion_unlocked
    was_enabled = any(track.get("enabled") for track in _tracks.values())
    _pa043_motion_unlocked = False
    for track in _tracks.values():
        track["enabled"] = False
        track["spin_dir"] = 0
        track["target_pos"] = track.get("cmd_pos")

    warnings: list[str] = []
    if disable and _service.connected and _service.motor_model == "lande_pa043" and (previously_unlocked or was_enabled):
        for info in _motors:
            mid = int(info["id"])
            try:
                feedback = _service.disable(mid)
                if feedback is None:
                    warnings.append(f"Motor ID {mid}: disable sent but no feedback received")
            except Exception as exc:
                warnings.append(f"Motor ID {mid}: disable failed: {exc}")
    return warnings


def _position_mode() -> bool:
    return _control_mode in POSITION_MODES


def _recommended_control_defaults() -> dict[str, float]:
    defaults = {
        "kp": DEFAULT_KP,
        "kd": DEFAULT_KD,
        "vel_kp": DEFAULT_VEL_KP,
        "vel_kd": DEFAULT_VEL_KD,
        "vel_ki": DEFAULT_VEL_KI,
    }
    model_defaults = CONTROL_DEFAULTS.get(_service.motor_model or "", {})
    defaults.update(model_defaults.get(_control_mode, {}))
    return defaults


def _apply_recommended_control_defaults() -> None:
    global _kp, _kd, _vel_kp, _vel_kd, _vel_ki
    defaults = _recommended_control_defaults()
    _kp = float(defaults["kp"])
    _kd = float(defaults["kd"])
    _vel_kp = float(defaults["vel_kp"])
    _vel_kd = float(defaults["vel_kd"])
    _vel_ki = float(defaults["vel_ki"])


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
        "motion_unlocked": bool(_pa043_motion_unlocked) if model == "lande_pa043" else False,
        "motion_unlock_ready": model == "lande_pa043" and _pa043_unlock_blocker(require_disabled=True) is None,
        "motion_unlock_reason": (
            _pa043_unlock_blocker(require_disabled=True)
            if model == "lande_pa043" and not _pa043_motion_unlocked else ""
        ),
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
        "vel_kp": _vel_kp,
        "vel_kd": _vel_kd,
        "vel_ki": _vel_ki,
        "recommended_defaults": dict(
            CONTROL_DEFAULTS
            .get(model or "", {})
            .get(_control_mode, {})
        ),
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
    previous_mode = _control_mode
    _motors = _service.scan(start_id, end_id)
    _reset_tracks(
        keep_selected=keep_selected,
        prefer_focus=prefer_focus,
        preserve_enabled=False,
    )
    _control_mode = _choose_control_mode()
    if _control_mode != previous_mode:
        _apply_recommended_control_defaults()
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
            "vel_kp": _vel_kp,
            "vel_kd": _vel_kd,
            "vel_ki": _vel_ki,
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


@app.route("/api/motion_lock", methods=["POST"])
def motion_lock():
    """Manual PA043 motion authorization for the current connection only."""
    global _pa043_motion_unlocked
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or "").strip().lower()

    if action not in {"unlock", "lock"}:
        return _json_error("action must be 'unlock' or 'lock'")

    with _lock:
        if not _service.connected or _service.motor_model != "lande_pa043":
            return _json_error("PA043 must be connected to change its motion lock", 409)

        if action == "unlock":
            if data.get("confirmation") != PA043_UNLOCK_CONFIRMATION:
                return _json_error("Explicit PA043 motion safety confirmation is required", 400)
            blocker = _pa043_unlock_blocker(require_disabled=True)
            if blocker:
                return _json_error(f"Cannot unlock PA043: {blocker}", 409)
            _pa043_motion_unlocked = True
            return jsonify({"success": True, "state": _state_payload()})

        warnings = _relock_pa043_motion(disable=True)
        return jsonify({
            "success": True,
            "state": _state_payload(),
            "warnings": warnings,
        })


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
            # The previous connection's approval must never transfer to a new
            # motor model, CAN channel, or connection attempt.
            warnings = _relock_pa043_motion(disable=True)
            if warnings:
                raise RuntimeError("Previous PA043 motor disable is unverified: " + "; ".join(warnings))
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
            _relock_pa043_motion()
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
        warnings = _relock_pa043_motion(disable=True)
        _service.disconnect()
        _motors = []
        _tracks = {}
        _selected_ids = []
        _focus_id = None
        _control_mode = ""
    return jsonify({"success": True, "warnings": warnings})


@app.route("/api/scan", methods=["POST"])
def scan():
    data = request.get_json(silent=True) or {}
    if not _service.connected:
        return _json_error("Not connected")

    start_id = data.get("start_id")
    end_id = data.get("end_id")

    try:
        with _lock:
            if _service.motor_model == "lande_pa043":
                warnings = _relock_pa043_motion(disable=True)
                if warnings:
                    raise RuntimeError("PA043 software lock active, but motor disable is unverified: " + "; ".join(warnings))
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
            if _service.motor_model == "lande_pa043":
                warnings = _relock_pa043_motion(disable=True)
                if warnings:
                    raise RuntimeError("PA043 software lock active, but motor disable is unverified: " + "; ".join(warnings))
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
            _apply_recommended_control_defaults()
            payload = _state_payload()

        return jsonify({"success": True, "state": payload})
    except Exception as exc:
        traceback.print_exc()
        return _json_error(f"Mode change failed: {exc}", 500)


@app.route("/api/settings", methods=["POST"])
def settings():
    global _kp, _kd, _vel_kp, _vel_kd, _vel_ki, _max_speed_rad_s
    data = request.get_json(silent=True) or {}

    with _lock:
        if "kp" in data:
            _kp = max(0.0, min(250.0, float(data["kp"])))
        if "kd" in data:
            _kd = max(0.0, min(50.0, float(data["kd"])))
        if "vel_kp" in data:
            _vel_kp = max(0.0, min(250.0, float(data["vel_kp"])))
        if "vel_kd" in data:
            _vel_kd = max(0.0, min(50.0, float(data["vel_kd"])))
        if "vel_ki" in data:
            _vel_ki = max(0.0, min(0.05, float(data["vel_ki"])))
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
    try:
        with _lock:
            if not _motion_allowed():
                return _json_error("Motion is locked; unlock PA043 in the GUI first", 409)
            attempted: list[int] = []
            try:
                for mid in ids:
                    attempted.append(mid)
                    feedback = _service.enable(mid)
                    if _service.motor_model == "lande_pa043" and feedback is None:
                        raise RuntimeError(f"PA043 Motor ID {mid} enable produced no feedback")
                    track = _tracks.setdefault(mid, _track_from_state(mid))
                    pos = _state_pos(_safe_state(mid))
                    if pos is not None:
                        track["cmd_pos"] = pos
                        track["target_pos"] = pos
                    track["enabled"] = True
                    track["spin_dir"] = 0
                    track["fail"] = 0
            except Exception:
                # A partially successful multi-motor Enable must not leave a
                # GUI-controlled actuator enabled after a failed request.
                for mid in attempted:
                    try:
                        stop_feedback = _service.disable(mid)
                        if _service.motor_model == "lande_pa043" and stop_feedback is None:
                            _note_error(f"Motor {mid}: disable after Enable failure has no feedback")
                    except Exception as exc:
                        _note_error(f"Motor {mid} disable after Enable failure: {exc}")
                    if mid in _tracks:
                        _tracks[mid]["enabled"] = False
                        _tracks[mid]["spin_dir"] = 0
                raise
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
    if data.get("deg") is None and data.get("rad") is None:
        return _json_error("deg or rad is required")

    try:
        with _lock:
            if not _motion_allowed():
                return _json_error("Motion is locked for this motor model", 409)
            if not _position_mode():
                return _json_error(
                    f"Dial requires a position-capable mode: {', '.join(sorted(POSITION_MODES))}",
                    409,
                )
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
    with _lock:
        if want:
            if not _motion_allowed():
                return _json_error("Motion is locked for this motor model", 409)
            if not _position_mode():
                return _json_error("Spin requires MIT/servo/torque_position mode", 409)
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
    results: dict[int, Any] = {}

    try:
        with _lock:
            if not _motion_allowed():
                return _json_error("Motion is locked for this motor model", 409)
            if _service.motor_model == "lande_pa043" and mode != _control_mode:
                return _json_error("PA043 command mode does not match verified control mode", 409)
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
