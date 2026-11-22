"""App install / launch helpers with ABI awareness."""
from __future__ import annotations

import json
import os
import re
import subprocess

from . import config
from .adb import Adb

AAPT = str(config.HOME / "android-sdk/build-tools/35.0.0/aapt2")


def apk_info(apk: str) -> dict:
    """Read package name + native ABIs straight out of the APK."""
    p = subprocess.run([AAPT, "dump", "badging", apk], capture_output=True, text=True)
    text = p.stdout
    pkg = re.search(r"package: name='([^']+)'", text)
    abis = re.findall(r"native-code: '([^']*)'", text)
    abi_list = abis[0].split("' '") if abis else []
    return {
        "package": pkg.group(1) if pkg else None,
        "abis": abi_list,
        "launchable": "launchable-activity" in text,
    }


def install(adb: Adb, apk: str, abi: str | None = None) -> dict:
    info = apk_info(apk)
    if abi is None and info["abis"]:
        # Android 15 + libndk: install arm64 APKs as arm64 so the translator is used
        abi = "arm64-v8a" if "arm64-v8a" in info["abis"] else info["abis"][0]
    out = adb.install(apk, abi=abi)
    return {"apk": apk, "package": info["package"], "abi": abi, "output": out.strip().splitlines()[-1]}


def launch(adb: Adb, pkg: str, activity: str | None = None) -> str:
    comp = f"{pkg}/{activity}" if activity else None
    if not comp:
        out = adb.sh(f"cmd package resolve-activity --brief {pkg}").strip().splitlines()
        comp = out[-1] if out else None
    if not comp or "/" not in comp:
        out = adb.sh(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
        return out.strip().splitlines()[-1] if out.strip() else "launch failed"
    return adb.sh(f"am start -n {comp}").strip()


def stop(adb: Adb, pkg: str) -> str:
    return adb.sh(f"am force-stop {pkg}").strip()


def packages(adb: Adb, third_party_only: bool = True) -> list[str]:
    flag = "-3" if third_party_only else ""
    out = adb.sh(f"pm list packages {flag}")
    return sorted(line.split(":", 1)[1] for line in out.splitlines() if line.startswith("package:"))


def app_abi(adb: Adb, pkg: str) -> dict:
    out = adb.sh(f"dumpsys package {pkg} | grep -m2 -E 'primaryCpuAbi|secondaryCpuAbi'")
    res = {}
    for line in out.splitlines():
        m = re.match(r"\s*(\w+)=(\S+)", line)
        if m:
            res[m.group(1)] = m.group(2)
    return res
