"""Static configuration: paths, defaults, device profiles."""
from __future__ import annotations

import json
import os
from pathlib import Path

HOME = Path(os.environ.get("HOME", "/home/iu"))
ROOT = HOME / "droidkit"

# Container / device defaults
CONTAINER = os.environ.get("DROIDKIT_CONTAINER", "dk31")
IMAGE = os.environ.get("DROIDKIT_IMAGE", "droidkit/redroid:15-magisk31-stealth")
BASE_IMAGE = os.environ.get("DROIDKIT_BASE_IMAGE", "erstt/redroid:15.0.0_ndk_magisk_AVD")
ADB_PORT = int(os.environ.get("DROIDKIT_PORT", "5564"))
SERIAL = f"127.0.0.1:{ADB_PORT}"
DATA_DIR = os.environ.get("DROIDKIT_DATA", "/mnt/vms/redroid/dk31-data")

# Where the injected module reads its configuration inside Android
ANDROID_DIR = "/data/local/tmp/droidkit"

# Sensor injection module
MODULE_PKG = "com.droidkit.hooks"
MODULE_APK = ROOT / "android" / "module" / "droidkit-hooks.apk"

PROFILES_DIR = ROOT / "profiles"
DEFAULT_PROFILE = "pixel-7"


def load_profile(name: str | None = None) -> dict:
    """Load a device profile JSON (build props + screen)."""
    name = name or DEFAULT_PROFILE
    path = Path(name)
    if not path.exists():
        path = PROFILES_DIR / f"{name}.json"
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def profile_cmdline(profile: dict) -> list[str]:
    """Translate a profile into redroid kernel-cmdline property args."""
    out = []
    b = profile.get("build", {})
    mapping = {
        "model": "ro.product.model",
        "brand": "ro.product.brand",
        "manufacturer": "ro.product.manufacturer",
        "device": "ro.product.device",
        "name": "ro.product.name",
        "fingerprint": "ro.build.fingerprint",
    }
    for key, prop in mapping.items():
        if b.get(key):
            out.append(f"{prop}={b[key]}")
    abi = profile.get("abilist", "x86_64,arm64-v8a,x86")
    out.append(f"ro.product.cpu.abilist={abi}")
    out.append("ro.product.cpu.abilist64=x86_64,arm64-v8a")
    out.append("ro.product.cpu.abilist32=x86")
    d = profile.get("display", {})
    for key in ("width", "height", "dpi"):
        if d.get(key):
            out.append(f"androidboot.redroid_{key}={d[key]}")
    return out
