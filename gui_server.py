from __future__ import annotations

import os
import threading
import traceback
from typing import Any

from flask import Flask, jsonify, render_template, request

from motor_service import MotorService
from motors import get_motor_spec


_template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
app = Flask(__name__, template_folder=_template_dir)

_lock = threading.RLock()
_service = MotorService()
_motors: list[dict[str, Any]] = []
_selected_ids: list[int] = []
_focus_id: int | None = None

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


def _motor_map() -> dict[int, dict[str, Any]]:
    return {int(item["id"]): item for item in _motors}


def _safe_state(mid: int) -> dict[str, Any]:
    try:
        return dict(_service.get_state(mid) or {})
    except Exception:
        return {}


def _motors_payload() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for info in _motors:
        mid = int(info["id"])
        state = _safe_state(mid)
        item = dict(info)
        item.update(state)
        item["id"] = mid
        item["selected"] = mid in _selected_ids
        item["focused"] = mid == _focus_id
        out.append(item)
    return out


def _state_payload() -> dict[str, Any]:
    info = _service.connection_info()
    model = info.get("motor_model")
    spec = get_motor_spec(model) if model else None
    focus_state = _safe_state(_focus_id) if _focus_id is not None else {}

    return {
        **info,
        "motor_model_name": spec.name if spec else None,
        "supported_modes": list(spec.supported_modes) if spec else [],
        "motion_allowed": _motion_allowed(),
        "selected_ids": list(_selected_ids),
        "focus_id": _focus_id,
        "motors": _motors_payload(),
        "focus_state": focus_state,
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


def _rescan(start_id: int | None = None, end_id: int | None = None) -> list[dict[str, Any]]:
    global _motors, _selected_ids, _focus_id
    motors = _service.scan(start_id, end_id)
    found_ids = [int(item["id"]) for item in motors]
    _motors = motors
    _selected_ids = [mid for mid in _selected_ids if mid in found_ids]
    if not _selected_ids and found_ids:
        _selected_ids = [found_ids[0]]
    if _focus_id not in found_ids:
        _focus_id = _selected_ids[0] if _selected_ids else None
    return motors


@app.route("/")
def index():
    return render_template("custom_gui.html")


@app.route("/api/capabilities")
def capabilities():
    return jsonify({"success": True, **MotorService.capabilities()})


@app.route("/api/state")
def state():
    with _lock:
        return jsonify({"success": True, "state": _state_payload()})


@app.route("/api/connect", methods=["POST"])
def connect():
    global _motors, _selected_ids, _focus_id
    data = request.get_json(silent=True) or {}
    adapter = str(data.get("adapter") or "auto")
    channel = data.get("channel")
    motor_model = str(data.get("motor_model") or "").strip()

    if not motor_model:
        return _json_error("motor_model is required")

    try:
        with _lock:
            _service.connect(
                adapter=adapter,
                channel=channel,
                motor_model=motor_model,
            )
            _motors = []
            _selected_ids = []
            _focus_id = None
            _rescan()
            payload = _state_payload()
        return jsonify({"success": True, "state": payload})
    except Exception as exc:
        traceback.print_exc()
        with _lock:
            _service.disconnect()
            _motors = []
            _selected_ids = []
            _focus_id = None
        return _json_error(f"Connect failed: {exc}", 500)


@app.route("/api/disconnect", methods=["POST"])
def disconnect():
    global _motors, _selected_ids, _focus_id
    with _lock:
        _service.disconnect()
        _motors = []
        _selected_ids = []
        _focus_id = None
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
        elif _focus_id not in ids:
            _focus_id = ids[0] if ids else None
        return jsonify({"success": True, "state": _state_payload()})


@app.route("/api/control_mode", methods=["POST"])
def control_mode():
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
            # Refresh model metadata after changing mode.
            _rescan()
            payload = _state_payload()
        return jsonify({"success": True, "state": payload})
    except Exception as exc:
        traceback.print_exc()
        return _json_error(f"Mode change failed: {exc}", 500)


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
            payload = _state_payload()
        return jsonify({"success": True, "state": payload})
    except Exception as exc:
        traceback.print_exc()
        return _json_error(f"Disable failed: {exc}", 500)


@app.route("/api/command", methods=["POST"])
def command():
    data = request.get_json(silent=True) or {}
    ids = _parse_ids(data)
    mode = str(data.get("mode") or "").strip()
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
            payload = _state_payload()
        return jsonify({"success": True, "results": results, "state": payload})
    except Exception as exc:
        traceback.print_exc()
        return _json_error(f"Command failed: {exc}", 500)


def run_server(host: str = "127.0.0.1", port: int = 5000) -> None:
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run_server()
