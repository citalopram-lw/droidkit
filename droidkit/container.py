# SPDX-License-Identifier: Apache-2.0
"""Container lifecycle for the redroid Android 15 device."""
from __future__ import annotations

import json
import subprocess
import time

from . import config
from .adb import Adb


def _run(cmd: list[str], timeout: int = 600, check: bool = True) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{p.stderr.strip()}")
    return p.stdout.strip()


class Container:
    def __init__(self, name: str = config.CONTAINER, image: str = config.IMAGE,
                 port: int = config.ADB_PORT, data: str = config.DATA_DIR):
        self.name = name
        self.image = image
        self.port = port
        self.data = data

    # ------------------------------------------------------------------ host
    @staticmethod
    def ensure_host_prereqs() -> list[str]:
        """binder_linux + /dev/binderfs are required by redroid, they don't survive reboot."""
        notes = []
        if not subprocess.run(["bash", "-lc", "mountpoint -q /dev/binderfs"],
                              capture_output=True).returncode == 0:
            # privileged chroot avoids the interactive sudo password
            subprocess.run([
                "docker", "run", "--rm", "--privileged", "--pid=host", "-v", "/:/host",
                "alpine", "chroot", "/host", "sh", "-c",
                "modprobe binder_linux 2>/dev/null; mkdir -p /dev/binderfs; "
                "mount -t binder binder /dev/binderfs 2>/dev/null; true"], check=False)
            notes.append("mounted /dev/binderfs")
        for dev in ("binder", "hwbinder", "vndbinder"):
            if not __import__("os").path.exists(f"/dev/binderfs/{dev}"):
                notes.append(f"missing /dev/binderfs/{dev}")
        return notes

    # ------------------------------------------------------------- lifecycle
    def exists(self) -> bool:
        out = _run(["docker", "ps", "-a", "--format", "{{.Names}}"], check=False)
        return self.name in out.split()

    def running(self) -> bool:
        out = _run(["docker", "ps", "--format", "{{.Names}}"], check=False)
        return self.name in out.split()

    def rm(self):
        _run(["docker", "rm", "-f", self.name], check=False)

    def up(self, profile: dict | None = None, wait: bool = True) -> dict:
        profile = profile or config.load_profile()
        self.ensure_host_prereqs()
        self.rm()
        args = [
            "docker", "run", "-d", "--name", self.name, "--privileged",
            "--hostname", profile.get("hostname", "panther"),
            "-v", "/dev/binderfs:/dev/binderfs",
            "-p", f"{self.port}:5555",
            "-v", f"{self.data}:/data",
            self.image,
        ] + config.profile_cmdline(profile) + [
            "androidboot.redroid_gpu_mode=" + profile.get("gpu_mode", "guest"),
        ]
        # host GPU needs the DRM nodes; guest (SwiftShader) does not
        if profile.get("gpu_mode") == "host":
            args[args.index("--privileged") + 1:args.index("--privileged") + 1] = ["--device", "/dev/dri"]
        _run(args)
        result = {"container": self.name, "port": self.port}
        if wait:
            adb = Adb(f"127.0.0.1:{self.port}")
            ok = adb.connect() and adb.wait_boot()
            result["booted"] = ok
            if ok:
                adb.root()
        return result

    def down(self):
        _run(["docker", "stop", self.name], check=False)

    def restart(self):
        _run(["docker", "restart", self.name])
        adb = Adb(f"127.0.0.1:{self.port}")
        adb.connect()
        adb.root()

    def status(self) -> dict:
        info = {}
        p = subprocess.run(["docker", "inspect", self.name], capture_output=True, text=True)
        if p.returncode != 0:
            return {"exists": False}
        d = json.loads(p.stdout)[0]
        info["exists"] = True
        info["running"] = d["State"]["Running"]
        info["image"] = d["Config"]["Image"]
        info["started"] = d["State"].get("StartedAt")
        info["ports"] = d["HostConfig"].get("PortBindings")
        adb = Adb(f"127.0.0.1:{self.port}")
        try:
            info["booted"] = adb.shell("getprop sys.boot_completed").strip() == "1"
            info["android"] = adb.prop("ro.build.version.release")
            info["model"] = adb.prop("ro.product.model")
            info["focus"] = adb.current_focus()
        except Exception as e:  # noqa: BLE001
            info["adb_error"] = str(e)
        return info

    def wait_ready(self, timeout: int = 180) -> bool:
        adb = Adb(f"127.0.0.1:{self.port}")
        return adb.connect() and adb.wait_boot(timeout)
