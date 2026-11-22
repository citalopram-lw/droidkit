# SPDX-License-Identifier: Apache-2.0
"""Performance tuning + measurement for the container and the Android runtime."""
from __future__ import annotations

import statistics
import subprocess
import time

from .adb import Adb


def _nproc() -> int:
    try:
        return len(__import__("os").sched_getaffinity(0))
    except Exception:  # noqa: BLE001
        return 8


def host_tune(name: str = "dk15", cpus: str | None = None) -> dict:
    """Give the container a fixed CPU slice and realtime-ish priority."""
    cpus = cpus or f"0-{max(3, min(7, _nproc() - 1))}"
    out = {}
    for args in (
        ["docker", "update", "--cpuset-cpus", cpus, name],
        ["docker", "update", "--cpu-shares", "2048", name],
    ):
        p = subprocess.run(args, capture_output=True, text=True)
        out[args[-1]] = p.returncode == 0
    return {"cpuset": cpus, **out}


ANDROID_SETTINGS = {
    "window_animation_scale": "0.0",
    "transition_animation_scale": "0.0",
    "animator_duration_scale": "0.0",
    "verifier_verify_adb_installs": "0",
    "package_verifier_enable": "0",
}


def android_tune(adb: Adb) -> list[str]:
    """Disable animations/verifier and raise runtime limits; all reversible."""
    done = []
    for key, val in ANDROID_SETTINGS.items():
        adb.sh(f"settings put global {key} {val}")
        done.append(f"{key}={val}")
    for prop, val in {
        "debug.hwui.renderer": "skiagl",
        "dalvik.vm.dex2oat-filter": "speed",
        "dalvik.vm.image-dex2oat-filter": "speed",
        "persist.sys.dalvik.vm.lib.2": "libart.so",
    }.items():
        adb.sh(f"setprop {prop} {val}")
    adb.sh("cmd package bg-dexopt-job")
    done.append("dexopt-job scheduled")
    return done


def compile_app(adb: Adb, pkg: str, mode: str = "speed") -> str:
    """AOT-compile an app with the requested compiler filter."""
    return adb.sh(f"cmd package compile -m {mode} -f {pkg}")


def bench_start(adb: Adb, pkg: str, activity: str | None = None, runs: int = 5,
                cold: bool = True) -> dict:
    """Measure cold/warm start with `am start -W`; returns median milliseconds."""
    comp = f"{pkg}/{activity}" if activity else None
    if not comp:
        out = adb.sh(f"cmd package resolve-activity --brief {pkg}").strip().splitlines()
        comp = out[-1] if out else pkg
    totals, waits = [], []
    for _ in range(runs):
        if cold:
            adb.sh(f"am force-stop {pkg}")
            adb.sh("echo 3 > /proc/sys/vm/drop_caches")
            time.sleep(0.5)
        out = adb.sh(f"am start -W -S -n {shlex_quote(comp)}" if cold
                     else f"am start -W -n {shlex_quote(comp)}")
        total = _grab(out, "TotalTime")
        wait = _grab(out, "WaitTime")
        if total is not None:
            totals.append(total)
        if wait is not None:
            waits.append(wait)
    return {
        "component": comp,
        "runs": runs,
        "total_ms": {"median": statistics.median(totals) if totals else None, "samples": totals},
        "wait_ms": {"median": statistics.median(waits) if waits else None, "samples": waits},
    }


def shlex_quote(s: str) -> str:
    import shlex
    return shlex.quote(s)


def _grab(text: str, key: str) -> int | None:
    for line in text.splitlines():
        if line.strip().startswith(key):
            try:
                return int(line.split(":", 1)[1].strip())
            except (IndexError, ValueError):
                return None
    return None


def frame_stats(adb: Adb, pkg: str) -> dict:
    adb.sh(f"dumpsys gfxinfo {pkg} reset")
    time.sleep(2)
    out = adb.sh(f"dumpsys gfxinfo {pkg}")
    res = {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Total frames rendered"):
            res["total_frames"] = line.split(":", 1)[1].strip()
        elif line.startswith("Janky frames"):
            res["janky_frames"] = line.split(":", 1)[1].strip()
        elif line.startswith("50th percentile"):
            res["p50"] = line.split(":", 1)[1].strip()
        elif line.startswith("90th percentile"):
            res["p90"] = line.split(":", 1)[1].strip()
        elif line.startswith("95th percentile"):
            res["p95"] = line.split(":", 1)[1].strip()
        elif line.startswith("99th percentile"):
            res["p99"] = line.split(":", 1)[1].strip()
    return res


def renderer(adb: Adb) -> dict:
    out = adb.sh("dumpsys SurfaceFlinger | grep -iE 'GLES|renderengine|Vulkan' | head -6")
    cpu = adb.sh("cat /proc/cpuinfo | grep -m1 'model name'")
    mem = adb.sh("cat /proc/meminfo | head -3")
    load = adb.sh("cat /proc/loadavg")
    return {"surfaceflinger": out.strip(), "cpu": cpu.strip(), "mem": mem.strip(), "load": load.strip()}
