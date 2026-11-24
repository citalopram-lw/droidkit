# SPDX-License-Identifier: Apache-2.0
"""Human-like touch injection through a uinput virtual touchscreen.

Why not ``adb shell input tap``: those events reach the app with
``deviceId=-1`` and ``toolType=UNKNOWN``, which any anti-automation check reads
as "injected". This module registers a kernel input device the way a phone's
touch controller would (Focaltech ``fts_ts``, BUS_I2C, INPUT_PROP_DIRECT), so
InputReader hands the app a MotionEvent that carries a real device id, real
pressure/contact size and real timestamps.

Two pieces have to line up or nothing is delivered:

1. the ``dk_touchd`` daemon inside the container creates the uinput device and
   services a command file;
2. the ``/dev/input/eventN`` node must appear with group ``input`` *before*
   EventHub opens it — EventHub opens on inotify and never retries, so the node
   is created with mode 0666 and tightened afterwards.
"""
from __future__ import annotations

import math
import os
import re
import random
import shutil
import subprocess
import tempfile
import time

from . import ui
from .adb import Adb, AdbError

CMD_PATH = "/data/local/tmp/droidkit/touch.cmd"
DAEMON_PATH = "/data/local/tmp/dk_touchd"
DEVICE_NAME = "fts_ts"

# Physical realism knobs. Values are what a thumb on glass actually produces,
# measured against recorded taps on a real device: hold 55-130 ms, contact
# 45-75 px^2 in the touch_major units this driver reports.
HOLD_MS = (58, 128)
DOUBLE_GAP_MS = (180, 350)
STEP_HZ = 60
JITTER_PX = 1.5
LONG_PRESS_MS = (550, 900)


class TouchError(RuntimeError):
    pass


class Touch:
    """Gesture injection bound to one container/adb serial."""

    def __init__(self, adb: Adb | None = None, human: bool = True):
        self.adb = adb or Adb()
        self.human = human

    # ------------------------------------------------------------- daemon side
    def _repo_binary(self) -> str:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "android", "uinput", "prebuilt", "dk_touchd")

    def _build(self) -> str:
        """Compile the daemon for the host arch if we don't have a binary yet."""
        src_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "android", "uinput")
        out = os.path.join(src_dir, "prebuilt", "dk_touchd")
        if os.path.exists(out):
            return out
        if not shutil.which("gcc"):
            raise TouchError("gcc missing: build android/uinput/dk_touchd.c first")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        subprocess.run(["gcc", "-static", "-O2", "-o", out,
                        os.path.join(src_dir, "dk_touchd.c"), "-lm"], check=True)
        return out

    def _daemon_running(self) -> bool:
        return bool(self.adb.sh("pgrep -x dk_touchd").strip())

    def _start_daemon(self) -> None:
        binary = self._build()
        self.adb.shell(f"mkdir -p /data/local/tmp/droidkit; : > {CMD_PATH}")
        self.adb.run("push", binary, DAEMON_PATH)
        self.adb.shell(f"chmod 755 {DAEMON_PATH}")
        self.adb.shell(f"setsid nohup {DAEMON_PATH} > /data/local/tmp/touchd.log 2>&1 < /dev/null &")
        for _ in range(20):
            time.sleep(0.15)
            if self._daemon_running():
                return
        raise TouchError("dk_touchd did not start: " + self.adb.sh("cat /data/local/tmp/touchd.log"))

    def _event_node(self) -> tuple[str, str, str] | None:
        """Return (event_name, major, minor) for our device, or None."""
        out = self.adb.sh("cat /proc/bus/input/devices")
        for block in out.split("\n\n"):
            if f'Name="{DEVICE_NAME}"' not in block:
                continue
            m = re.search(r"H: Handlers=([^\n]*)", block)
            if not m:
                continue
            events = [h for h in m.group(1).split() if h.startswith("event")]
            if not events:
                continue
            name = events[0]
            dev = self.adb.sh(f"cat /sys/class/input/{name}/dev").strip()
            if ":" not in dev:
                return None
            major, minor = dev.split(":", 1)
            return name, major, minor
        return None

    def _link_node(self) -> str:
        info = self._event_node()
        if not info:
            raise TouchError("uinput device not present (UI_DEV_CREATE failed?)")
        name, major, minor = info
        path = f"/dev/input/{name}"
        # EventHub opens on inotify (IN_CREATE) and never retries, so the node
        # must be world-writable at creation time; permissions are tightened
        # right after, and the already-open fd keeps working.
        self.adb.shell(f"rm -f {path}; mknod -m 0666 {path} c {major} {minor}")
        time.sleep(0.4)
        self.adb.shell(f"chown root:input {path}; chmod 660 {path}")
        return path

    def ensure(self, restart: bool = False) -> dict:
        """Make sure the device exists and InputReader has bound it.

        ``restart=True`` re-pushes the binary and restarts the daemon, which is
        how an updated dk_touchd reaches a container that is already running.
        """
        if restart and self._daemon_running():
            self.adb.sh("echo quit > " + CMD_PATH)
            time.sleep(0.4)
            self.adb.sh("pkill -x dk_touchd || true")
            time.sleep(0.2)
        if not self._daemon_running():
            self._start_daemon()
        if not self._event_node():
            self._start_daemon()
        node = self._link_node()

        for _ in range(25):
            dump = self.adb.sh("dumpsys input")
            if f": {DEVICE_NAME}" in dump:
                return {"node": node, "device": DEVICE_NAME, "bound": True}
            time.sleep(0.2)
        return {"node": node, "device": DEVICE_NAME, "bound": False,
                "hint": "EventHub did not bind; re-run ensure() to re-create the node"}

    def stop(self) -> None:
        self.adb.sh(f"echo quit > {CMD_PATH}")
        time.sleep(0.3)
        self.adb.sh("pkill -x dk_touchd || true")

    # --------------------------------------------------------------- gesture IO
    def _send(self, lines: list[str]) -> None:
        """Hand a batch to the daemon in one write so timing stays contiguous."""
        payload = "\n".join(lines) + "\n"
        tmp = os.path.join(tempfile.gettempdir(), "droidkit-touch.batch")
        with open(tmp, "w") as fh:
            fh.write(payload)
        self.adb.sh("mkdir -p /data/local/tmp/droidkit")
        self.adb.run("push", tmp, CMD_PATH + ".tmp")
        # Atomic publish: the daemon unlinks CMD_PATH when it consumes a batch,
        # so appending in place would let it eat half a gesture.
        self.adb.shell(f"mv {CMD_PATH}.tmp {CMD_PATH}")

    def _jitter(self, x: int, y: int, sigma: float | None = None) -> tuple[int, int]:
        if not self.human:
            return x, y
        s = JITTER_PX if sigma is None else sigma
        return int(round(random.gauss(x, s))), int(round(random.gauss(y, s)))

    def _hold(self, ms: int | None) -> int:
        if ms:
            return ms
        return random.randint(*HOLD_MS) if self.human else 80

    def tap(self, x: int, y: int, hold_ms: int | None = None) -> None:
        x, y = self._jitter(x, y)
        hold = self._hold(hold_ms)
        self._send([f"down {x} {y}", f"sleep {hold}", "up"])

    def long_press(self, x: int, y: int, ms: int | None = None) -> None:
        x, y = self._jitter(x, y, sigma=1.0)
        hold = ms or (random.randint(*LONG_PRESS_MS) if self.human else 700)
        self._send([f"down {x} {y}", f"sleep {hold}", "up"])

    def path(self, x1: int, y1: int, x2: int, y2: int, ms: int) -> list[tuple[int, int]]:
        """Bezier-ish path with tremor: a finger does not travel in a straight line."""
        steps = max(4, int(ms / 1000 * STEP_HZ))
        # control point pulled off the midline, like a thumb pivoting on the wrist
        cx = (x1 + x2) / 2 + random.uniform(-0.12, 0.12) * (y2 - y1)
        cy = (y1 + y2) / 2 + random.uniform(-0.12, 0.12) * (x1 - x2)
        pts = []
        phase = random.uniform(0, math.tau)
        for i in range(1, steps + 1):
            t = i / steps
            # ease-in-out so it accelerates then settles, like a real swipe
            e = 2 * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 2) / 2
            bx = (1 - e) ** 2 * x1 + 2 * (1 - e) * e * cx + e * e * x2
            by = (1 - e) ** 2 * y1 + 2 * (1 - e) * e * cy + e * e * y2
            if self.human:
                tremor = math.sin(phase + t * math.tau * 1.5) * 1.2
                bx += tremor * random.uniform(0.4, 1.0)
                by += tremor * random.uniform(0.4, 1.0)
            pts.append((int(round(bx)), int(round(by))))
        return pts

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int | None = None) -> None:
        if ms is None:
            ms = random.randint(180, 320) if self.human else 250
        x1, y1 = self._jitter(x1, y1, sigma=1.0)
        x2, y2 = self._jitter(x2, y2, sigma=1.5)
        step_ms = max(8, int(1000 / STEP_HZ))
        lines = [f"down {x1} {y1}"]
        for px, py in self.path(x1, y1, x2, y2, ms):
            lines += [f"move {px} {py}", f"sleep {step_ms}"]
        lines.append("up")
        self._send(lines)

    def scroll(self, direction: str, distance: int = 600, ms: int | None = None) -> None:
        """One-finger fling — how a phone user scrolls; no wheel events exist."""
        w, h = self._screen()
        cx, cy = w // 2, h // 2
        d = max(80, min(distance, h // 2 - 40))
        vec = {"up": (0, d), "down": (0, -d), "left": (d, 0), "right": (-d, 0)}
        if direction not in vec:
            raise TouchError(f"scroll direction must be one of {list(vec)}")
        dx, dy = vec[direction]
        self.swipe(cx - dx // 2, cy - dy // 2, cx + dx // 2, cy + dy // 2,
                   ms or (random.randint(150, 240) if self.human else 200))

    # ------------------------------------------------------------------ helpers
    def _screen(self) -> tuple[int, int]:
        out = self.adb.sh("wm size")
        for token in out.replace(":", " ").split():
            if "x" in token and token[0].isdigit():
                w, h = token.split("x")
                return int(w), int(h)
        return 1080, 1920

    # ------------------------------------------------------- element targeting
    def nodes(self) -> list[ui.Node]:
        return ui.parse(self.adb.ui_dump())

    def locate(self, selector: str, timeout: float = 0.0) -> ui.Node:
        deadline = time.time() + timeout
        while True:
            found = ui.resolve(self.nodes(), selector)
            if found:
                return found[0]
            if time.time() >= deadline:
                raise TouchError(f"element not found: {selector}")
            time.sleep(0.35)

    def tap_element(self, selector: str, timeout: float = 0.0) -> ui.Node:
        node = self.locate(selector, timeout)
        x1, y1, x2, y2 = node.bounds
        # keep the strike inside the element: inset 15% of each side, then jitter
        ix, iy = max(4, int(node.width * 0.15)), max(4, int(node.height * 0.15))
        x = random.randint(x1 + ix, max(x1 + ix, x2 - ix))
        y = random.randint(y1 + iy, max(y1 + iy, y2 - iy))
        self.tap(x, y)
        return node

    def status(self) -> dict:
        return {
            "daemon": self._daemon_running(),
            "device": self._event_node(),
            "bound": f": {DEVICE_NAME}" in self.adb.sh("dumpsys input"),
            "cmd": self.adb.sh(f"wc -c < {CMD_PATH}").strip(),
        }
