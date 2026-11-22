# SPDX-License-Identifier: Apache-2.0
"""Command line interface (`droidkit ...`)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

from . import __version__, apps, audit, config, container, image, perf, sensors, stealth
from .adb import Adb


def _adb(args) -> Adb:
    return Adb(getattr(args, "serial", None) or config.SERIAL)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="droidkit", description="Android-in-Linux device platform")
    ap.add_argument("-V", "--version", action="version", version=f"droidkit {__version__}")
    ap.add_argument("-s", "--serial", default=None, help="adb serial (default 127.0.0.1:5563)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check host prerequisites")

    p = sub.add_parser("image", help="build the Android image")
    p.add_argument("action", choices=["build", "info"])
    p.add_argument("--base", default=config.BASE_IMAGE)
    p.add_argument("--target", default=config.IMAGE)
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("up", help="start container")
    p.add_argument("--no-wait", action="store_true")
    p.add_argument("--no-tune", action="store_true")
    p.add_argument("--no-stealth", action="store_true")
    p.add_argument("--profile", default=None, help="profile name or path (e.g. pixel-7-hw)")
    sub.add_parser("down", help="stop container")
    sub.add_parser("restart", help="restart container")
    sub.add_parser("status", help="device status")

    p = sub.add_parser("shell", help="adb shell")
    p.add_argument("command")

    p = sub.add_parser("shot", help="screenshot")
    p.add_argument("path", nargs="?", default=None)

    p = sub.add_parser("tap", help="tap")
    p.add_argument("x", type=int); p.add_argument("y", type=int)
    p = sub.add_parser("swipe", help="swipe")
    for n in ("x1", "y1", "x2", "y2"):
        p.add_argument(n, type=int)
    p.add_argument("--ms", type=int, default=300)
    p = sub.add_parser("text", help="type text")
    p.add_argument("text")
    p = sub.add_parser("key", help="key event")
    p.add_argument("key")
    sub.add_parser("ui", help="dump UI hierarchy")

    p = sub.add_parser("install", help="install APK")
    p.add_argument("apk"); p.add_argument("--abi", default=None)
    p = sub.add_parser("launch", help="launch app")
    p.add_argument("package"); p.add_argument("--activity", default=None)
    p = sub.add_parser("stop", help="force-stop app")
    p.add_argument("package")
    sub.add_parser("ls", help="list third-party packages")

    p = sub.add_parser("perf", help="performance")
    p.add_argument("action", choices=["tune", "bench", "renderer", "compile"])
    p.add_argument("package", nargs="?", default=None)
    p.add_argument("--runs", type=int, default=5)

    p = sub.add_parser("stealth", help="anti-virtualization hardening")
    p.add_argument("action", choices=["apply", "status"])
    p.add_argument("--no-masks", action="store_true")
    p.add_argument("--no-props", action="store_true")

    p = sub.add_parser("audit", help="anti-virtualization detector")
    p.add_argument("--only", default=None)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("sensor", help="virtual sensors / GPS")
    p.add_argument("action", choices=["config", "route", "cmd", "status", "log"])
    p.add_argument("--lat", type=float, default=None)
    p.add_argument("--lng", type=float, default=None)
    p.add_argument("--radius", type=float, default=60.0)
    p.add_argument("--speed", type=float, default=2.8)
    p.add_argument("--cadence", type=float, default=3.34)
    p.add_argument("--targets", nargs="*", default=None)
    p.add_argument("--route-file", default=None)
    p.add_argument("cmd", nargs="?", default=None)

    p = sub.add_parser("module", help="Xposed sensor module")
    p.add_argument("action", choices=["build", "install", "status"])
    p.add_argument("--scope", nargs="*", default=None)

    sub.add_parser("mcp", help="run the MCP stdio server")

    args = ap.parse_args(argv)

    if args.cmd == "doctor":
        notes = container.Container.ensure_host_prereqs()
        print(json.dumps({"binderfs": notes or "ok",
                          "adb": os.path.exists(config.HOME / "android-sdk/platform-tools/adb"),
                          "image": image.image_exists(config.IMAGE),
                          "data_dir": os.path.isdir(config.DATA_DIR)}, indent=2))
        return 0

    if args.cmd == "image":
        if args.action == "build":
            print(json.dumps(image.build(args.base, args.target, force=args.force), indent=2))
        else:
            print(json.dumps({"exists": image.image_exists(config.IMAGE), "image": config.IMAGE}, indent=2))
        return 0

    if args.cmd == "up":
        c = container.Container()
        prof = config.load_profile(args.profile) if args.profile else None
        res = c.up(profile=prof, wait=not args.no_wait)
        if not args.no_wait and res.get("booted"):
            if not args.no_tune:
                res["perf"] = {"host": perf.host_tune(c.name), "android": perf.android_tune(_adb(args))}
            if not args.no_stealth:
                res["stealth"] = stealth.apply(_adb(args))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "down":
        container.Container().down(); print("stopped"); return 0
    if args.cmd == "restart":
        container.Container().restart(); print("restarted"); return 0
    if args.cmd == "status":
        print(json.dumps(container.Container().status(), ensure_ascii=False, indent=2)); return 0

    adb = _adb(args)

    if args.cmd == "shell":
        print(adb.sh(args.command), end=""); return 0
    if args.cmd == "shot":
        path = args.path or os.path.join(tempfile.gettempdir(), "droidkit.png")
        adb.screenshot(path); print(path); return 0
    if args.cmd == "tap":
        adb.tap(args.x, args.y); print("ok"); return 0
    if args.cmd == "swipe":
        adb.swipe(args.x1, args.y1, args.x2, args.y2, args.ms); print("ok"); return 0
    if args.cmd == "text":
        adb.text(args.text); print("ok"); return 0
    if args.cmd == "key":
        adb.key(args.key); print("ok"); return 0
    if args.cmd == "ui":
        print(adb.ui_dump()); return 0

    if args.cmd == "install":
        print(json.dumps(apps.install(adb, args.apk, args.abi), indent=2)); return 0
    if args.cmd == "launch":
        print(apps.launch(adb, args.package, args.activity)); return 0
    if args.cmd == "stop":
        print(apps.stop(adb, args.package)); return 0
    if args.cmd == "ls":
        print("\n".join(apps.packages(adb))); return 0

    if args.cmd == "perf":
        if args.action == "tune":
            print(json.dumps({"host": perf.host_tune(), "android": perf.android_tune(adb)}, indent=2))
        elif args.action == "bench":
            if not args.package:
                ap.error("perf bench needs a package")
            print(json.dumps(perf.bench_start(adb, args.package, runs=args.runs), indent=2))
        elif args.action == "compile":
            print(perf.compile_app(adb, args.package))
        else:
            print(json.dumps(perf.renderer(adb), indent=2))
        return 0

    if args.cmd == "stealth":
        if args.action == "apply":
            print(json.dumps(stealth.apply(adb, masks=not args.no_masks,
                                           props=not args.no_props), ensure_ascii=False, indent=2))
        else:
            print(json.dumps(stealth.status(adb), indent=2))
        return 0

    if args.cmd == "audit":
        rep = audit.run(adb, args.only)
        print(json.dumps(rep, ensure_ascii=False, indent=2) if args.json else audit.format_table(rep))
        return 0

    if args.cmd == "sensor":
        if args.action == "config":
            route = None
            if args.route_file:
                route = json.load(open(args.route_file))["points"]
            print(json.dumps(sensors.set_config(adb, route=route, speed=args.speed,
                                                cadence_hz=args.cadence,
                                                targets=args.targets), indent=2))
        elif args.action == "route":
            if args.lat is None or args.lng is None:
                ap.error("sensor route needs --lat/--lng")
            route = sensors.circle((args.lat, args.lng), args.radius)
            sensors.set_config(adb, route=route, speed=args.speed, cadence_hz=args.cadence,
                               targets=args.targets)
            print(json.dumps({"points": len(route), "speed": args.speed,
                              "cadence_hz": args.cadence}, indent=2))
        elif args.action == "cmd":
            print(sensors.command(adb, args.cmd or "status"))
        elif args.action == "log":
            print(sensors.tail_log(adb))
        else:
            print(json.dumps(sensors.status(adb), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "module":
        if args.action == "build":
            subprocess.run(["bash", str(config.ROOT / "android/module/build.sh")], check=True)
        elif args.action == "install":
            print(json.dumps(sensors.install_module(adb, args.scope), indent=2))
        else:
            print(json.dumps(sensors.status(adb), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "mcp":
        from .mcp_server import serve
        serve()
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
