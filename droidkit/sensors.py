"""Virtual sensor / GPS control plane.

The module (android/module) runs inside the target app process and reads its
configuration from /data/local/tmp/droidkit/:

    config.json  route points, speed, cadence, Build spoof
    targets.txt  packages to inject into
    cmd          one-shot commands (start/stop/hold/speed/cadence/seek)

This module is the host side: it pushes configuration, installs/enables the
module through the Vector (LSPosed) CLI, and reports what the device says.
"""
from __future__ import annotations

import json
import math
import time

from . import config
from .adb import Adb

CLI = "/data/adb/modules/zygisk_vector/cli"


def _push_json(adb: Adb, path: str, obj) -> None:
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        tmp = fh.name
    try:
        adb.push(tmp, path)
    finally:
        os.unlink(tmp)


def set_config(adb: Adb, route: list[list[float]] | None = None, speed: float = 2.8,
               cadence_hz: float = 3.34, loop: bool = True, auto_start: bool = True,
               hide_artifacts: bool = True, build: dict | None = None,
               targets: list[str] | None = None) -> dict:
    adb.root()
    adb.sh(f"mkdir -p {config.ANDROID_DIR} && chmod 755 {config.ANDROID_DIR}")
    # Partial updates must not wipe the route/build already on the device.
    old = {}
    try:
        import json as _json
        raw = adb.sh(f"cat {config.ANDROID_DIR}/config.json 2>/dev/null")
        if raw.strip().startswith("{"):
            old = _json.loads(raw)
    except Exception:
        old = {}
    if route is None:
        route = old.get("route") or []
    if build is None:
        build = old.get("build") or {}
    cfg = {
        "route": route or [],
        "speed": speed,
        "cadence_hz": cadence_hz,
        "loop": loop,
        "auto_start": auto_start,
        "hide_artifacts": hide_artifacts,
        "build": build or {},
    }
    _push_json(adb, f"{config.ANDROID_DIR}/config.json", cfg)
    if targets is not None:
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write("\n".join(targets) + "\n")
            tmp = fh.name
        try:
            adb.push(tmp, f"{config.ANDROID_DIR}/targets.txt")
        finally:
            os.unlink(tmp)
    adb.sh(f"chmod 644 {config.ANDROID_DIR}/*")
    return cfg


def command(adb: Adb, cmd: str) -> str:
    adb.sh(f"echo {json.dumps(cmd)} > {config.ANDROID_DIR}/cmd 2>/dev/null; "
           f"chmod 666 {config.ANDROID_DIR}/cmd")
    time.sleep(0.4)
    return cmd


def circle(center: tuple[float, float], radius_m: float, points: int = 16) -> list[list[float]]:
    lat, lng = center
    dlat = radius_m / 111320.0
    dlng = radius_m / (111320.0 * math.cos(math.radians(lat)))
    out = []
    for i in range(points):
        a = 2 * math.pi * i / points
        out.append([round(lat + dlat * math.sin(a), 6), round(lng + dlng * math.cos(a), 6)])
    out.append(out[0])
    return out


def line(start: tuple[float, float], end: tuple[float, float], points: int = 8) -> list[list[float]]:
    return [[round(start[0] + (end[0] - start[0]) * i / (points - 1), 6),
             round(start[1] + (end[1] - start[1]) * i / (points - 1), 6)]
            for i in range(points)]


def install_module(adb: Adb, scope: list[str] | None = None) -> dict:
    """Install the Xposed module APK and enable+scope it through Vector."""
    adb.root()
    apk = config.MODULE_APK
    if not apk.exists():
        raise FileNotFoundError(f"{apk} not built; run android/module/build.sh")
    out = adb.install(str(apk))
    res = {"install": out.strip().splitlines()[-1]}
    if scope:
        res["enable"] = adb.sh(f"{CLI} modules enable {config.MODULE_PKG}").strip()
        res["scope"] = []
        for pkg in scope:
            res["scope"].append(adb.sh(f"{CLI} scope add {config.MODULE_PKG} {pkg}/0").strip())
    return res


def status(adb: Adb) -> dict:
    adb.root()
    st = {
        "module_installed": bool(adb.sh(f"pm path {config.MODULE_PKG}").strip()),
        "framework": adb.sh(f"{CLI} status 2>&1 | head -8").strip(),
        "module_list": adb.sh(f"{CLI} modules ls 2>&1 | head -6").strip(),
        "config": adb.sh(f"cat {config.ANDROID_DIR}/config.json 2>/dev/null | head -c 800").strip(),
        "targets": adb.sh(f"cat {config.ANDROID_DIR}/targets.txt 2>/dev/null").strip(),
        "zygote_zygisk": adb.sh(
            "for p in $(pidof zygote64); do grep -c -i zygisk /proc/$p/maps 2>/dev/null; done").strip(),
        "sensors_native": adb.sh("dumpsys sensorservice 2>/dev/null | head -3").strip(),
        "logs": adb.sh("logcat -d -s DroidKit:* 2>/dev/null | tail -8").strip(),
    }
    return st


def tail_log(adb: Adb, lines: int = 30) -> str:
    return adb.sh(f"logcat -d -s DroidKit:* 2>/dev/null | tail -{int(lines)}").strip()
