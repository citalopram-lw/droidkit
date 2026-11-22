# SPDX-License-Identifier: Apache-2.0
"""Anti-virtualization detector.

Runs the checks a hardened Android app (packer anti-emulator, banking SDK, game
anti-cheat) would run against this device and reports which ones still reveal
that it is a redroid container on a Linux host.  Status semantics:

    clean  - a detector looking for this tell finds nothing
    tell   - the tell is visible (detection succeeds)
    skip   - could not probe (permissions / command missing)

`droidkit stealth apply` turns most tells into "clean"; the report is the
ground truth for what is still exposed.
"""
from __future__ import annotations

import re

from .adb import Adb

TELL_FILES = [
    "/dev/qemu_pipe", "/dev/goldfish_pipe", "/dev/socket/qemud", "/system/bin/qemud",
    "/init.goldfish.rc", "/system/lib/libc_malloc_debug_qemu.so",
    "/system/lib64/libc_malloc_debug_qemu.so",
    "/system/bin/su", "/system/xbin/su", "/sbin/.magisk", "/data/adb/magisk",
    "/system/etc/init/magisk", "/system/lib64/libnb.so", "/system/lib/libnb.so",
    "/system/bin/frida-server", "/data/local/tmp/frida-server",
]


class Probes:
    def __init__(self, adb: Adb):
        self.adb = adb
        self._cache: dict[str, str] = {}

    def sh(self, cmd: str) -> str:
        if cmd not in self._cache:
            self._cache[cmd] = self.adb.sh(cmd)
        return self._cache[cmd]

    def prop(self, name: str) -> str:
        return self.sh(f"getprop {name}").strip()

    def exists(self, path: str) -> bool:
        return self.sh(f"test -e {path} && echo yes || echo no").strip() == "yes"


def _check(cid, title, category, severity):
    def deco(fn):
        fn._meta = (cid, title, category, severity)
        return fn
    return deco


CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


@check
@_check("build.debuggable", "ro.debuggable=1 (userdebug build)", "build", "high")
def _(p: Probes):
    v = p.prop("ro.debuggable")
    return ("tell", f"ro.debuggable={v!r}") if v == "1" else ("clean", f"ro.debuggable={v!r}")


@check
@_check("build.tags", "ro.build.tags=test-keys", "build", "high")
def _(p: Probes):
    v = p.prop("ro.build.tags")
    return ("tell", v) if "test-keys" in v else ("clean", v)


@check
@_check("build.type", "ro.build.type=userdebug/eng", "build", "high")
def _(p: Probes):
    v = p.prop("ro.build.type")
    return ("tell", v) if v in ("userdebug", "eng") else ("clean", v)


@check
@_check("build.secure", "ro.secure=0", "build", "medium")
def _(p: Probes):
    v = p.prop("ro.secure")
    return ("tell", v) if v == "0" else ("clean", v)


@check
@_check("build.fingerprint.redroid", "fingerprint/brand contains redroid/generic", "build", "critical")
def _(p: Probes):
    fp = p.prop("ro.build.fingerprint")
    bad = [w for w in ("redroid", "generic", "emulator", "sdk_gphone") if w in fp.lower()]
    return ("tell", fp) if bad else ("clean", fp)


@check
@_check("build.props.redroid", "any system property mentions redroid", "build", "critical")
def _(p: Probes):
    hits = [ln for ln in p.sh("getprop").splitlines()
            if re.search(r"redroid|goldfish|ranchu|qemu", ln, re.I)]
    return ("tell", "; ".join(hits[:4])) if hits else ("clean", "no redroid/goldfish props")


@check
@_check("build.hardware", "ro.hardware=redroid", "build", "high")
def _(p: Probes):
    v = p.prop("ro.hardware")
    return ("tell", v) if "redroid" in v or "goldfish" in v else ("clean", v)


@check
@_check("build.abilist.x86", "abilist advertises x86_64", "build", "high")
def _(p: Probes):
    v = p.prop("ro.product.cpu.abilist")
    return ("tell", v) if "x86" in v else ("clean", v)


@check
@_check("bridge.prop", "ro.dalvik.vm.native.bridge set (ARM translation)", "build", "critical")
def _(p: Probes):
    v = p.prop("ro.dalvik.vm.native.bridge")
    return ("tell", v) if v not in ("", "0") else ("clean", v or "0")


@check
@_check("bridge.lib", "libnb/libndk_translation present in /system", "files", "high")
def _(p: Probes):
    found = [f for f in ("/system/lib64/libnb.so", "/system/lib64/libndk_translation.so")
             if p.exists(f)]
    return ("tell", ", ".join(found)) if found else ("clean", "no bridge lib")


@check
@_check("proc.cpuinfo.x86", "/proc/cpuinfo shows Intel/AMD/hypervisor", "kernel", "critical")
def _(p: Probes):
    v = p.sh("head -25 /proc/cpuinfo")
    bad = [w for w in ("GenuineIntel", "AuthenticAMD", "vendor_id", "hypervisor") if w in v]
    return ("tell", v.splitlines()[1] if len(v.splitlines()) > 1 else v) if bad else ("clean", "ARM-like cpuinfo")


@check
@_check("proc.version.host", "/proc/version leaks the host kernel", "kernel", "critical")
def _(p: Probes):
    v = p.sh("head -1 /proc/version").strip()
    bad = any(w in v for w in ("generic", "Ubuntu", "Debian", "x86_64-linux-gnu-gcc"))
    return ("tell", v) if bad else ("clean", v)


@check
@_check("proc.cmdline", "/proc/cmdline leaks redroid/console", "kernel", "high")
def _(p: Probes):
    v = p.sh("head -1 /proc/cmdline").strip()
    bad = [w for w in ("redroid", "console=ttyS", "androidboot.hardware=redroid") if w in v]
    return ("tell", v) if bad else ("clean", v)


@check
@_check("uname.host", "uname -r is a Linux host kernel", "kernel", "critical")
def _(p: Probes):
    v = p.sh("uname -a").strip()
    bad = any(w in v for w in ("generic", "Ubuntu", "SMP PREEMPT_DYNAMIC", "x86_64"))
    return ("tell", v) if bad else ("clean", v)


@check
@_check("container.dockerenv", "/.dockerenv exists", "container", "critical")
def _(p: Probes):
    return ("tell", "/.dockerenv present") if p.exists("/.dockerenv") else ("clean", "absent")


@check
@_check("container.cgroup", "cgroup path contains a container id", "container", "high")
def _(p: Probes):
    v = p.sh("cat /proc/1/cgroup").strip()
    bad = any(w in v for w in ("docker", "kubepods", "containerd", "lxc"))
    return ("tell", v) if bad else ("clean", v)


@check
@_check("container.mountinfo", "mount table exposes overlay/docker paths", "container", "high")
def _(p: Probes):
    v = p.sh("grep -m3 -E 'overlay|docker' /proc/self/mountinfo")
    return ("tell", v.strip()) if v.strip() else ("clean", "no overlay/docker mounts visible")


@check
@_check("container.hostname", "hostname is a 12-hex container id", "container", "medium")
def _(p: Probes):
    v = p.sh("cat /proc/sys/kernel/hostname").strip()
    bad = bool(re.fullmatch(r"[0-9a-f]{12}", v))
    return ("tell", v) if bad else ("clean", v)


@check
@_check("sysfs.dmi", "/sys/class/dmi/id leaks the host mainboard", "container", "high")
def _(p: Probes):
    v = p.sh("cat /sys/class/dmi/id/product_name 2>/dev/null").strip()
    bad = bool(v) and not any(w in v.lower() for w in ("sm-", "pixel", "vivo"))
    return ("tell", v) if bad else ("clean", v or "unreadable")


@check
@_check("proc.modules", "/proc/modules lists host drivers", "container", "medium")
def _(p: Probes):
    v = p.sh("head -6 /proc/modules").strip()
    bad = any(w in v for w in ("nvidia", "amdgpu", "kvm", "vbox"))
    return ("tell", v.splitlines()[0] if v else "") if bad else ("clean", "no host modules")


@check
@_check("files.emulator", "classic emulator/root artifacts on disk", "files", "high")
def _(p: Probes):
    hits = [f for f in TELL_FILES if p.exists(f)]
    return ("tell", ", ".join(hits)) if hits else ("clean", "none of %d paths" % len(TELL_FILES))


@check
@_check("root.magiskd", "magiskd/zygisk process running", "root", "high")
def _(p: Probes):
    v = p.sh("ps -A | grep -E 'magiskd|zygisk|frida|gdbserver' | grep -v grep")
    return ("tell", v.strip().replace("\n", " | ")) if v.strip() else ("clean", "no root daemons in ps")


@check
@_check("debug.adb_tcp", "adb over TCP is enabled", "debug", "medium")
def _(p: Probes):
    v = p.prop("service.adb.tcp.port")
    return ("tell", f"service.adb.tcp.port={v}") if v not in ("", "0") else ("clean", v or "0")


@check
@_check("debug.developer_options", "developer options / adb enabled", "debug", "low")
def _(p: Probes):
    dev = p.sh("settings get global development_settings_enabled").strip()
    adb = p.sh("settings get global adb_enabled").strip()
    return ("tell", f"dev={dev} adb={adb}") if dev == "1" or adb == "1" else ("clean", f"dev={dev} adb={adb}")


@check
@_check("sensors.none", "no sensors registered (sensorservice empty)", "sensors", "critical")
def _(p: Probes):
    v = p.sh("dumpsys sensorservice 2>/dev/null")
    if "No Sensors on the device" in v or "devInitCheck : -19" in v:
        return ("tell", "No Sensors on the device")
    n = len(re.findall(r"0x[0-9a-f]{8}\)", v))
    return ("clean", f"{n} sensors") if n else ("tell", "sensor list empty")


@check
@_check("sensors.hal", "sensors HAL shared library missing", "sensors", "high")
def _(p: Probes):
    v = p.sh("ls /vendor/lib64/hw/sensors* /system/lib64/hw/sensors* 2>/dev/null").strip()
    return ("clean", v) if v else ("tell", "no sensors.<board>.so in /vendor or /system")


@check
@_check("input.virtio", "only virtual input devices", "hardware", "medium")
def _(p: Probes):
    v = p.sh("ls /dev/input 2>/dev/null | tr '\\n' ' '").strip()
    return ("clean", v) if v else ("tell", "no /dev/input devices")


@check
@_check("battery.fake", "battery reports AC/100%/no temperature", "hardware", "high")
def _(p: Probes):
    v = p.sh("dumpsys battery 2>/dev/null")
    ac = "AC powered: true" in v
    lvl = re.search(r"level: (\d+)", v)
    temp = re.search(r"temperature: (-?\d+)", v)
    if ac and lvl and lvl.group(1) == "100":
        return ("tell", f"AC powered, level={lvl.group(1)}, temp={temp.group(1) if temp else 'n/a'}")
    return ("clean", v.strip().splitlines()[0] if v.strip() else "no battery service")


@check
@_check("telephony.no_sim", "no SIM / no telephony stack", "hardware", "high")
def _(p: Probes):
    sim = p.prop("gsm.sim.state")
    op = p.prop("gsm.operator.alpha")
    if not sim:
        return ("tell", "gsm.sim.state empty")
    return ("clean", f"sim={sim} op={op}")


@check
@_check("network.docker_mac", "NIC is a docker veth (02:42:ac:*)", "network", "high")
def _(p: Probes):
    v = p.sh("ip -o link 2>/dev/null | grep -v lo").strip()
    bad = "02:42:ac" in v or "eth0" in v and "wlan0" not in v
    return ("tell", v.splitlines()[0] if v else "no interfaces") if bad else ("clean", v[:100])


@check
@_check("network.no_wifi", "no wlan interface / wifi service", "network", "medium")
def _(p: Probes):
    v = p.sh("ls /sys/class/net").split()
    return ("clean", " ".join(v)) if "wlan0" in v else ("tell", f"interfaces: {' '.join(v)}")


@check
@_check("gpu.software", "SurfaceFlinger uses a software/emulator GPU", "hardware", "medium")
def _(p: Probes):
    v = p.sh("dumpsys SurfaceFlinger 2>/dev/null | grep -iE 'GLES|SwiftShader|llvmpipe|Emulator' | head -3")
    return ("tell", v.strip()) if v.strip() else ("clean", "no software renderer string")


@check
@_check("camera.none", "no camera HAL", "hardware", "medium")
def _(p: Probes):
    v = p.sh("dumpsys media.camera 2>/dev/null | grep -c 'Camera ID'")
    try:
        n = int(v.strip())
    except ValueError:
        return ("skip", v.strip()[:60])
    return ("clean", f"{n} cameras") if n else ("tell", "0 cameras")


@check
@_check("nfc.none", "no NFC service", "hardware", "low")
def _(p: Probes):
    v = p.sh("dumpsys nfc 2>/dev/null | head -2")
    return ("tell", "nfc service absent") if not v.strip() or "Can't find service" in v else ("clean", v.strip()[:80])


@check
@_check("vibrator.none", "no vibrator HAL", "hardware", "low")
def _(p: Probes):
    v = p.sh("ls /sys/class/leds 2>/dev/null | tr '\\n' ' '").strip()
    return ("skip", v or "no leds") if not v else ("clean", v)


@check
@_check("fingerprint.no_hal", "no fingerprint HAL", "hardware", "medium")
def _(p: Probes):
    v = p.sh("getprop | grep -i fingerprint | head -3")
    bad = "fpc" in v.lower() or "goodix" in v.lower()
    return ("clean", "fingerprint props present") if bad else ("tell", "no fingerprint HAL props")


@check
@_check("serial.empty", "ro.serialno empty", "build", "low")
def _(p: Probes):
    v = p.prop("ro.serialno")
    return ("tell", "ro.serialno empty") if not v else ("clean", v)


@check
@_check("packages.root", "Magisk/LSPosed/Frida packages installed", "root", "high")
def _(p: Probes):
    v = p.sh("pm list packages 2>/dev/null | grep -iE 'magisk|lsposed|xposed|frida|vector'")
    return ("tell", v.strip().replace("\n", ", ")) if v.strip() else ("clean", "no root-manager packages")


@check
@_check("ports.frida", "frida default port 27042 listening", "root", "medium")
def _(p: Probes):
    v = p.sh("cat /proc/net/tcp /proc/net/tcp6 2>/dev/null | grep -i ':69A2'")
    return ("tell", "port 27042 open") if v.strip() else ("clean", "27042 closed")


@check
@_check("tracer.pid", "process is being ptraced", "runtime", "medium")
def _(p: Probes):
    v = p.sh("grep TracerPid /proc/self/status").strip()
    return ("tell", v) if not v.endswith("0") else ("clean", v)


@check
@_check("boot.qemu", "ro.kernel.qemu / ro.boot.qemu set", "build", "high")
def _(p: Probes):
    vals = {k: p.prop(k) for k in ("ro.kernel.qemu", "ro.boot.qemu")}
    bad = {k: v for k, v in vals.items() if v not in ("", "0")}
    return ("tell", str(bad)) if bad else ("clean", str(vals))


def run(adb: Adb, only: str | None = None) -> dict:
    probes = Probes(adb)
    results = []
    for fn in CHECKS:
        cid, title, category, severity = fn._meta
        if only and only not in cid and only != category:
            continue
        try:
            status, detail = fn(probes)
        except Exception as e:  # noqa: BLE001
            status, detail = "skip", f"probe error: {e}"
        results.append({
            "id": cid, "title": title, "category": category,
            "severity": severity, "status": status, "detail": str(detail)[:300],
        })
    tells = [r for r in results if r["status"] == "tell"]
    clean = [r for r in results if r["status"] == "clean"]
    score = round(100 * len(clean) / max(1, len(clean) + len(tells)))
    return {
        "total": len(results),
        "clean": len(clean),
        "tells": len(tells),
        "skipped": len(results) - len(clean) - len(tells),
        "score": score,
        "results": results,
    }


def format_table(report: dict) -> str:
    icon = {"clean": "ok  ", "tell": "TELL", "skip": "--  "}
    lines = [f"anti-virtualization score: {report['score']}/100 "
             f"({report['clean']} clean, {report['tells']} tells, {report['skipped']} skipped)", ""]
    cat = None
    for r in report["results"]:
        if r["category"] != cat:
            cat = r["category"]
            lines.append(f"[{cat}]")
        lines.append(f"  {icon.get(r['status'], '?   ')} {r['id']:<26} {r['title']}")
        if r["status"] == "tell":
            lines.append(f"         -> {r['detail']}")
    return "\n".join(lines)
