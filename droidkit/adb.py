"""Thin, retrying adb wrapper bound to one device serial."""
from __future__ import annotations

import os
import shlex
import subprocess
import time

from . import config


class AdbError(RuntimeError):
    pass


class Adb:
    def __init__(self, serial: str = config.SERIAL, adb: str | None = None):
        self.serial = serial
        self.adb = adb or os.environ.get("ADB", str(config.HOME / "android-sdk/platform-tools/adb"))
        if not os.path.exists(self.adb):
            self.adb = "adb"

    # ------------------------------------------------------------------ basic
    def run(self, *args: str, timeout: int = 60, check: bool = True) -> str:
        cmd = [self.adb, "-s", self.serial, *args]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if check and p.returncode != 0:
            raise AdbError(f"{' '.join(shlex.quote(c) for c in cmd)}\n{p.stderr.strip()}")
        return p.stdout

    def shell(self, cmd: str, timeout: int = 60) -> str:
        return self.run("shell", cmd, timeout=timeout)

    def sh(self, cmd: str, timeout: int = 60) -> str:
        """Shell command, non-fatal (returns stderr text on failure)."""
        try:
            return self.shell(cmd, timeout=timeout)
        except (AdbError, subprocess.TimeoutExpired) as e:
            return f"__ERROR__ {e}"

    def root(self) -> bool:
        try:
            self.run("root", check=False)
        except subprocess.TimeoutExpired:
            pass
        for _ in range(10):
            time.sleep(0.5)
            if self.shell("id").strip().startswith("uid=0"):
                return True
        return False

    # --------------------------------------------------------------- lifecycle
    def connect(self, retries: int = 20) -> bool:
        for _ in range(retries):
            try:
                self.run("connect", self.serial, check=False)
                if "device" in self.run("devices").split():
                    if self.shell("getprop sys.boot_completed", check=False).strip() == "1":
                        return True
            except (AdbError, subprocess.TimeoutExpired):
                pass
            time.sleep(2)
        return False

    def wait_boot(self, timeout: int = 180) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.shell("getprop sys.boot_completed").strip() == "1":
                    return True
            except (AdbError, subprocess.TimeoutExpired):
                pass
            time.sleep(2)
        return False

    # ----------------------------------------------------------------- helpers
    def prop(self, name: str) -> str:
        return self.shell(f"getprop {shlex.quote(name)}").strip()

    def push(self, local: str, remote: str) -> str:
        return self.run("push", str(local), remote, timeout=180)

    def pull(self, remote: str, local: str) -> str:
        return self.run("pull", remote, str(local), timeout=300)

    def install(self, apk: str, abi: str | None = None, grant: bool = True) -> str:
        args = ["install", "-r"]
        if grant:
            args.append("-g")
        if abi:
            args += ["--abi", abi]
        args.append(str(apk))
        return self.run(*args, timeout=300)

    def screenshot(self, path: str) -> str:
        with open(path, "wb") as fh:
            p = subprocess.run([self.adb, "-s", self.serial, "exec-out", "screencap", "-p"],
                               stdout=fh, stderr=subprocess.PIPE, timeout=60)
        if p.returncode != 0:
            raise AdbError(p.stderr.decode(errors="replace"))
        return path

    def tap(self, x: int, y: int):
        self.shell(f"input tap {int(x)} {int(y)}")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300):
        self.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(ms)}")

    def text(self, s: str):
        self.shell("input text " + shlex.quote(s.replace(" ", "%s")))

    def key(self, code: str):
        self.shell(f"input keyevent {shlex.quote(code)}")

    def ui_dump(self) -> str:
        self.shell("uiautomator dump /sdcard/dk_ui.xml >/dev/null 2>&1")
        return self.shell("cat /sdcard/dk_ui.xml")

    def current_focus(self) -> str:
        out = self.sh("dumpsys window | grep -m1 mCurrentFocus")
        return out.strip()

    def pidof(self, pkg: str) -> list[int]:
        out = self.shell(f"pidof {shlex.quote(pkg)}").split()
        return [int(x) for x in out if x.isdigit()]
