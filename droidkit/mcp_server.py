# SPDX-License-Identifier: Apache-2.0
"""Minimal, dependency-free MCP server (stdio, newline-delimited JSON-RPC 2.0).

Implements the subset of Model Context Protocol 2024-11-05 that agent clients
need: initialize, tools/list, tools/call, ping.  Every tool maps onto the
droidkit CLI surface, so an agent can drive the container, install/launch apps,
read the screen, configure the virtual sensors, harden the device and run the
anti-virtualization audit without a shell.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import traceback

from . import __version__, config
from .adb import Adb
from . import apps, audit, container, perf, sensors, stealth, ui
from .uinput_touch import Touch, TouchError

PROTOCOL = "2024-11-05"

TOOLS: dict[str, dict] = {}


def tool(name: str, description: str, schema: dict):
    def deco(fn):
        TOOLS[name] = {"description": description, "schema": schema, "fn": fn}
        return fn
    return deco


def _adb() -> Adb:
    return Adb()


def _text(s) -> dict:
    return {"content": [{"type": "text", "text": s if isinstance(s, str) else json.dumps(s, ensure_ascii=False, indent=2)}]}


def _img(path: str, note: str = "") -> dict:
    data = base64.b64encode(open(path, "rb").read()).decode()
    return {"content": [
        {"type": "image", "data": data, "mimeType": "image/png"},
        {"type": "text", "text": note or path},
    ]}


# --------------------------------------------------------------------- tools
@tool("device_status", "Container + Android boot status, image, focus window.", {"type": "object", "properties": {}})
def _device_status(args):
    return _text(container.Container().status())


@tool("device_up", "Start the Android container and wait for boot.",
      {"type": "object", "properties": {"wait": {"type": "boolean", "default": True}}})
def _device_up(args):
    return _text(container.Container().up(wait=args.get("wait", True)))


@tool("device_down", "Stop the Android container.", {"type": "object", "properties": {}})
def _device_down(args):
    container.Container().down()
    return _text("stopped")


@tool("device_restart", "Restart the container (data persists).", {"type": "object", "properties": {}})
def _device_restart(args):
    container.Container().restart()
    return _text("restarted")


@tool("shell", "Run a shell command inside Android as adb shell.",
      {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]})
def _shell(args):
    return _text(_adb().sh(args["command"]))


@tool("app_list", "List installed third-party packages.", {"type": "object", "properties": {}})
def _app_list(args):
    return _text(apps.packages(_adb()))


@tool("app_install", "Install an APK (auto-selects arm64-v8a for translated ARM apps).",
      {"type": "object", "properties": {"apk": {"type": "string"}, "abi": {"type": "string"}}, "required": ["apk"]})
def _app_install(args):
    return _text(apps.install(_adb(), args["apk"], args.get("abi")))


@tool("app_launch", "Launch an app by package (optional activity).",
      {"type": "object", "properties": {"package": {"type": "string"}, "activity": {"type": "string"}}, "required": ["package"]})
def _app_launch(args):
    return _text(apps.launch(_adb(), args["package"], args.get("activity")))


@tool("app_stop", "Force-stop an app.", {"type": "object", "properties": {"package": {"type": "string"}}, "required": ["package"]})
def _app_stop(args):
    return _text(apps.stop(_adb(), args["package"]))


@tool("screen_shot", "Capture the device screen (PNG returned inline).", {"type": "object", "properties": {}})
def _screen_shot(args):
    path = os.path.join(tempfile.gettempdir(), "droidkit-mcp.png")
    _adb().screenshot(path)
    return _img(path, "screenshot")


@tool("input_tap", "Tap at screen coordinates.",
      {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]})
def _input_tap(args):
    _adb().tap(args["x"], args["y"])
    return _text(f"tap {args['x']},{args['y']}")


@tool("input_swipe", "Swipe between two points.",
      {"type": "object", "properties": {"x1": {"type": "integer"}, "y1": {"type": "integer"},
                                        "x2": {"type": "integer"}, "y2": {"type": "integer"},
                                        "ms": {"type": "integer", "default": 300}},
       "required": ["x1", "y1", "x2", "y2"]})
def _input_swipe(args):
    _adb().swipe(args["x1"], args["y1"], args["x2"], args["y2"], args.get("ms", 300))
    return _text("swipe")


@tool("input_text", "Type text into the focused field.",
      {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})
def _input_text(args):
    _adb().text(args["text"])
    return _text("typed")


@tool("input_key", "Send a key event (e.g. KEYCODE_BACK, KEYCODE_HOME).",
      {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]})
def _input_key(args):
    _adb().key(args["key"])
    return _text("key sent")


# ------------------------------------------------------- human-like touch (uinput)
_SEL_PROPS = {
    "text": {"type": "string", "description": "visible text, exact match"},
    "id": {"type": "string", "description": "resource-id, exact match"},
    "desc": {"type": "string", "description": "content-desc, exact match"},
    "sel": {"type": "string", "description": "raw selector, e.g. text~:登录"},
    "wait_s": {"type": "number", "description": "seconds to wait for the element"},
    "human": {"type": "boolean", "default": True,
              "description": "jitter + realistic timing (disable only for pixel-exact tests)"},
}


def _touch(args) -> Touch:
    return Touch(_adb(), human=args.get("human", True))


def _selector(args) -> str:
    if args.get("sel"):
        return args["sel"]
    if args.get("id"):
        return f"id:{args['id']}"
    if args.get("text"):
        return f"text:{args['text']}"
    if args.get("desc"):
        return f"desc:{args['desc']}"
    return ""


@tool("touch_tap", "Tap an element or a point with a synthetic finger (real touchscreen device, deviceId != -1).",
      {"type": "object",
       "properties": {**_SEL_PROPS,
                      "x": {"type": "integer"}, "y": {"type": "integer"},
                      "hold_ms": {"type": "integer"}}})
def _touch_tap(args):
    t = _touch(args)
    sel = _selector(args)
    try:
        if sel:
            node = t.tap_element(sel, timeout=args.get("wait_s", 0))
            return _text(f"tapped {node.label() or node.cls} at {node.center}")
        if "x" in args and "y" in args:
            t.tap(args["x"], args["y"], args.get("hold_ms"))
            return _text(f"tapped {args['x']},{args['y']}")
    except TouchError as e:
        return _text(f"error: {e}")
    return _text("error: give text/id/desc/sel or x,y")


@tool("touch_long_press", "Press and hold an element/point (long click).",
      {"type": "object",
       "properties": {**_SEL_PROPS,
                      "x": {"type": "integer"}, "y": {"type": "integer"},
                      "hold_ms": {"type": "integer", "default": 700}}})
def _touch_long(args):
    t = _touch(args)
    sel = _selector(args)
    try:
        if sel:
            node = t.locate(sel, timeout=args.get("wait_s", 0))
            x, y = node.center
            t.long_press(x, y, args.get("hold_ms", 700))
            return _text(f"held {node.label() or node.cls} at {x},{y}")
        if "x" in args and "y" in args:
            t.long_press(args["x"], args["y"], args.get("hold_ms", 700))
            return _text(f"held {args['x']},{args['y']}")
    except TouchError as e:
        return _text(f"error: {e}")
    return _text("error: give text/id/desc/sel or x,y")


@tool("touch_swipe", "Swipe along a curved, jittered path (drag / fling).",
      {"type": "object",
       "properties": {"x1": {"type": "integer"}, "y1": {"type": "integer"},
                      "x2": {"type": "integer"}, "y2": {"type": "integer"},
                      "ms": {"type": "integer"}, "human": {"type": "boolean", "default": True}},
       "required": ["x1", "y1", "x2", "y2"]})
def _touch_swipe(args):
    _touch(args).swipe(args["x1"], args["y1"], args["x2"], args["y2"], args.get("ms"))
    return _text(f"swiped {args['x1']},{args['y1']} -> {args['x2']},{args['y2']}")


@tool("touch_scroll", "One-finger scroll in a direction.",
      {"type": "object",
       "properties": {"direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                      "distance": {"type": "integer", "default": 600},
                      "ms": {"type": "integer"}, "human": {"type": "boolean", "default": True}},
       "required": ["direction"]})
def _touch_scroll(args):
    try:
        _touch(args).scroll(args["direction"], args.get("distance", 600), args.get("ms"))
    except TouchError as e:
        return _text(f"error: {e}")
    return _text(f"scrolled {args['direction']} {args.get('distance', 600)}")


@tool("touch_ui", "List on-screen elements with coordinates and clickability.",
      {"type": "object", "properties": {"limit": {"type": "integer", "default": 40}}})
def _touch_ui(args):
    return _text(ui.describe(_touch(args).nodes(), limit=args.get("limit", 40)))


@tool("touch_status", "Touch injector status: daemon, uinput device, InputReader binding.",
      {"type": "object", "properties": {}})
def _touch_status(args):
    return _text(_touch(args).status())


@tool("touch_ensure", "Start the injector daemon and (re)create the /dev/input node.",
      {"type": "object", "properties": {}})
def _touch_ensure(args):
    try:
        return _text(_touch(args).ensure())
    except TouchError as e:
        return _text(f"error: {e}")


@tool("ui_dump", "Dump the current UI hierarchy XML.", {"type": "object", "properties": {}})
def _ui_dump(args):
    return _text(_adb().ui_dump())


@tool("logcat", "Tail logcat, optionally filtered by tag.",
      {"type": "object", "properties": {"lines": {"type": "integer", "default": 60},
                                        "filter": {"type": "string"}}})
def _logcat(args):
    flt = f"-s {args['filter']}:*" if args.get("filter") else ""
    return _text(_adb().sh(f"logcat -d {flt} | tail -{int(args.get('lines', 60))}"))


@tool("sensor_config", "Push virtual-sensor config: GPS route, speed m/s, cadence Hz, target packages, Build spoof.",
      {"type": "object", "properties": {
          "route": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
          "speed": {"type": "number", "default": 2.8},
          "cadence_hz": {"type": "number", "default": 3.34},
          "targets": {"type": "array", "items": {"type": "string"}},
          "build": {"type": "object"}}})
def _sensor_config(args):
    cfg = sensors.set_config(_adb(), route=args.get("route"), speed=args.get("speed", 2.8),
                             cadence_hz=args.get("cadence_hz", 3.34),
                             targets=args.get("targets"), build=args.get("build"))
    return _text(cfg)


@tool("sensor_route_circle", "Generate a circular GPS route and apply it.",
      {"type": "object", "properties": {"lat": {"type": "number"}, "lng": {"type": "number"},
                                        "radius_m": {"type": "number", "default": 60},
                                        "speed": {"type": "number", "default": 2.8},
                                        "cadence_hz": {"type": "number", "default": 3.34},
                                        "targets": {"type": "array", "items": {"type": "string"}}},
       "required": ["lat", "lng"]})
def _sensor_circle(args):
    route = sensors.circle((args["lat"], args["lng"]), args.get("radius_m", 60))
    cfg = sensors.set_config(_adb(), route=route, speed=args.get("speed", 2.8),
                             cadence_hz=args.get("cadence_hz", 3.34),
                             targets=args.get("targets"))
    return _text({"route_points": len(route), **cfg})


@tool("sensor_cmd", "Send a runtime sensor command: start|stop|hold|status|speed <v>|cadence <v>|seek <lat,lng>|reload.",
      {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]})
def _sensor_cmd(args):
    sensors.command(_adb(), args["cmd"])
    return _text(f"sent: {args['cmd']}")


@tool("sensor_status", "Injection framework status + virtual sensor config + module logs.",
      {"type": "object", "properties": {}})
def _sensor_status(args):
    return _text(sensors.status(_adb()))


@tool("module_install", "Install and enable the virtual sensor Xposed module, scoping it to packages.",
      {"type": "object", "properties": {"scope": {"type": "array", "items": {"type": "string"}}}})
def _module_install(args):
    return _text(sensors.install_module(_adb(), args.get("scope")))


@tool("stealth_apply", "Apply anti-virtualization hardening (proc masks + property rewrite).",
      {"type": "object", "properties": {"masks": {"type": "boolean", "default": True},
                                        "props": {"type": "boolean", "default": True}}})
def _stealth_apply(args):
    return _text(stealth.apply(_adb(), masks=args.get("masks", True), props=args.get("props", True)))


@tool("stealth_status", "Current hardening state (cpuinfo, kernel, cgroup, props).", {"type": "object", "properties": {}})
def _stealth_status(args):
    return _text(stealth.status(_adb()))


@tool("audit_run", "Run the anti-virtualization detector; returns score + per-check result.",
      {"type": "object", "properties": {"only": {"type": "string"}}})
def _audit_run(args):
    rep = audit.run(_adb(), args.get("only"))
    return _text(rep)


@tool("perf_tune", "Apply Android + host performance tuning.", {"type": "object", "properties": {}})
def _perf_tune(args):
    return _text({"host": perf.host_tune(config.CONTAINER), "android": perf.android_tune(_adb())})


@tool("perf_bench", "Measure cold-start time of an app.",
      {"type": "object", "properties": {"package": {"type": "string"},
                                        "activity": {"type": "string"},
                                        "runs": {"type": "integer", "default": 5}},
       "required": ["package"]})
def _perf_bench(args):
    return _text(perf.bench_start(_adb(), args["package"], args.get("activity"), args.get("runs", 5)))


# ------------------------------------------------------------------ jsonrpc
def _respond(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error(id_, code, msg):
    _respond({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": msg}})


def _handle(req: dict) -> None:
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        _respond({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": (req.get("params") or {}).get("protocolVersion", PROTOCOL),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "droidkit", "version": __version__},
        }})
        return
    if method in ("notifications/initialized", "initialized"):
        return
    if method == "ping":
        _respond({"jsonrpc": "2.0", "id": rid, "result": {}})
        return
    if method == "tools/list":
        _respond({"jsonrpc": "2.0", "id": rid, "result": {"tools": [
            {"name": n, "description": t["description"], "inputSchema": t["schema"]}
            for n, t in TOOLS.items()
        ]}})
        return
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        entry = TOOLS.get(name)
        if not entry:
            _error(rid, -32602, f"unknown tool: {name}")
            return
        try:
            result = entry["fn"](args)
            result.setdefault("isError", False)
            _respond({"jsonrpc": "2.0", "id": rid, "result": result})
        except Exception as e:  # noqa: BLE001
            _respond({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}],
                "isError": True,
            }})
        return
    if method in ("resources/list", "prompts/list"):
        _respond({"jsonrpc": "2.0", "id": rid, "result": {method.split("/")[0]: []}})
        return
    if rid is not None:
        _error(rid, -32601, f"method not found: {method}")


def serve() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            if isinstance(req, list):
                for r in req:
                    _handle(r)
            else:
                _handle(req)
        except Exception:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    serve()
