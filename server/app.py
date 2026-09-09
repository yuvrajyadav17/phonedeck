"""PhoneDeck HTTP server.

Serves the dashboard to the phone and exposes the small API behind it. Bound
to loopback only -- the phone gets in through the `adb reverse` USB tunnel set
up by bridge.py, so this port is never visible on your LAN.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from flask import Flask, jsonify, request, send_file, send_from_directory

from . import (actions, claude, icons, macros, nowplaying, sensors,
               stats, weather)
from .bridge import Bridge
from . import config
from .config import (
    HOST,
    LOG_FILE,
    PORT,
    STATS_POLL_MS,
    WEB_DIR,
    get_token,
    load_shortcuts,
    save_shortcuts,
)

log = logging.getLogger("phonedeck")

TOKEN = get_token()
bridge = Bridge()


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)

    # ------------------------------------------------------------ auth ----
    def authorised() -> bool:
        supplied = (
            request.headers.get("X-PhoneDeck-Token")
            or request.args.get("t")
            or ""
        )
        # Constant-time-ish compare; the token is long and random enough that
        # timing is not a realistic attack here, but it costs nothing.
        return len(supplied) == len(TOKEN) and supplied == TOKEN

    def guard(view: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any):
            if not authorised():
                return jsonify({"ok": False, "error": "unauthorised"}), 401
            return view(*args, **kwargs)
        wrapper.__name__ = view.__name__
        return wrapper

    # ----------------------------------------------------------- pages ----
    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/editor")
    def editor():
        return send_from_directory(WEB_DIR, "editor.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        return send_from_directory(WEB_DIR, filename)

    # ------------------------------------------------------------- api ----
    @app.get("/api/health")
    def health():
        """Unauthenticated liveness probe, used by the app's splash screen."""
        return jsonify({"ok": True, "service": "phonedeck",
                        "poll_ms": STATS_POLL_MS})

    @app.post("/api/claude/hook")
    def api_claude_hook():
        """Receives Claude Code hook events.

        Deliberately unauthenticated, and it always answers 200 with an empty
        object. Claude treats a 4xx response from a hook as a decision to block
        the action, so a 401 here would stall real sessions -- and the endpoint
        only moves a status light. It is reachable on loopback only, like
        /api/health.
        """
        try:
            payload = request.get_json(silent=True) or {}
            if isinstance(payload, dict):
                claude.tracker.handle_event(payload)
        except Exception:  # noqa: BLE001 - a tracker fault must not reach Claude
            log.exception("claude hook failed")
        return jsonify({}), 200

    @app.get("/api/stats")
    @guard
    def api_stats():
        include = request.args.get("processes", "1") != "0"
        return jsonify({"ok": True, "stats": stats.snapshot(include)})

    @app.get("/api/shortcuts")
    @guard
    def api_shortcuts():
        return jsonify({"ok": True, "shortcuts": load_shortcuts()})

    @app.put("/api/shortcuts")
    @guard
    def api_save_shortcuts():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or "groups" not in payload:
            return jsonify({"ok": False,
                            "error": "expected an object with 'groups'"}), 400
        if not isinstance(payload["groups"], list):
            return jsonify({"ok": False, "error": "'groups' must be a list"}), 400
        save_shortcuts(payload)
        return jsonify({"ok": True, "message": "saved"})

    @app.post("/api/run/<button_id>")
    @guard
    def api_run(button_id: str):
        button = actions.find_button(load_shortcuts(), button_id)
        if button is None:
            return jsonify({"ok": False,
                            "error": f"no button with id {button_id!r}"}), 404
        try:
            result = actions.run_action(button.get("action", {}))
        except actions.ActionError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001 - report, never crash the server
            log.exception("action %s failed", button_id)
            return jsonify({"ok": False, "error": str(exc)}), 500
        status = 200 if result["ok"] else 400
        return jsonify({"label": button.get("label"), **result}), status

    @app.post("/api/run-inline")
    @guard
    def api_run_inline():
        """Run an action object directly -- the editor's 'Test' button."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "expected an action object"}), 400
        try:
            result = actions.run_action(payload)
        except actions.ActionError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001 - always answer with JSON
            log.exception("inline action failed")
            return jsonify({"ok": False, "error": str(exc)}), 500
        return jsonify(result), 200 if result["ok"] else 400

    @app.post("/api/process/<int:pid>/kill")
    @guard
    def api_kill(pid: int):
        try:
            message = actions.kill_process(pid)
        except actions.ActionError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "message": message})

    @app.get("/api/icon/<slot_id>")
    @guard
    def api_icon(slot_id: str):
        """The real application logo for a top-bar slot.

        Only ids present in shortcuts.json resolve, so this cannot be used to
        read arbitrary files off the machine.
        """
        slot = actions.find_slot(load_shortcuts(), slot_id)
        if slot is None:
            return jsonify({"ok": False, "error": "no such slot"}), 404
        path = icons.icon_png(slot_id, slot)
        if path is None:
            return jsonify({"ok": False, "error": "no icon available"}), 404
        # Icons change only when the app is updated; let the WebView keep them.
        return send_file(str(path), mimetype="image/png", max_age=3600)

    @app.post("/api/macro/record/<command>")
    @guard
    def api_macro_record(command: str):
        """Start or stop recording. Stopping returns the captured events."""
        if command == "start":
            return jsonify(macros.recorder.start())
        if command == "stop":
            # The editor's Stop button is itself a click on the PC, so it asks
            # for it to be trimmed. Stopping from the phone does not.
            trim = request.args.get("trim") in ("1", "true", "yes")
            return jsonify(macros.recorder.stop(trim_last_click=trim))
        return jsonify({"ok": False, "error": "use start or stop"}), 400

    @app.get("/api/macro/status")
    @guard
    def api_macro_status():
        return jsonify({"ok": True, **macros.recorder.status()})

    @app.get("/api/device")
    @guard
    def api_device():
        return jsonify({"ok": True, "device": bridge.snapshot()})

    @app.post("/api/device/relaunch")
    @guard
    def api_device_relaunch():
        return jsonify(bridge.relaunch())

    @app.errorhandler(404)
    def not_found(_exc):
        return jsonify({"ok": False, "error": "not found"}), 404

    return app


def main() -> None:
    # A tray app has no console, so the log file is the only way to see what
    # happened after the fact.
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))
    except OSError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    # Flask's request log is noise once this runs as a background service.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    app = create_app()
    sensors.start()
    weather.weather.start(config.WEATHER_LAT, config.WEATHER_LON,
                          config.WEATHER_PLACE)
    nowplaying.now_playing.start()
    bridge.start()

    log.info("PhoneDeck listening on http://%s:%s", HOST, PORT)
    log.info("Open in a desktop browser:  http://%s:%s/?t=%s", HOST, PORT, TOKEN)

    def serve() -> None:
        app.run(host=HOST, port=PORT, threaded=True, debug=False,
                use_reloader=False)

    http = threading.Thread(target=serve, name="http", daemon=True)
    http.start()

    # The tray icon owns the main thread from here: it is what makes the
    # background process reachable. If it cannot start -- pystray or Pillow
    # missing, or no desktop session -- fall back to serving headlessly, which
    # is exactly the previous behaviour.
    try:
        from . import tray
        tray.run(bridge)
    except Exception:  # noqa: BLE001 - never let the tray take the server down
        log.exception("tray unavailable; continuing without it")
        http.join()


if __name__ == "__main__":
    main()
