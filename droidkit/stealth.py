# SPDX-License-Identifier: Apache-2.0
"""Anti-virtualization hardening: hide container/kernel/root tells from apps.

Two layers, both measured against this container:

1. mount namespace masks — bind plain files over /proc/cpuinfo, /proc/version,
   /proc/cmdline, /proc/1/cgroup and /.dockerenv.  Verified to work inside
   redroid (SELinux disabled, CAP_SYS_ADMIN present).
2. property rewrite with Magisk's resetprop — ro.debuggable, ro.build.tags,
   ro.build.type, ro.secure and the native-bridge prop are read-only at the
   property-service level but resetprop edits them in place.

Everything is re-applied after a container restart; `droidkit up` does it
automatically.
"""
from __future__ import annotations

import json

from . import config
from .adb import Adb

MASK_DIR = f"{config.ANDROID_DIR}/mask"

CPUINFO_QCOM = """processor\t: 0
BogoMIPS\t: 38.40
Features\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop asimddp
CPU implementer\t: 0x51
CPU architecture: 8
CPU variant\t: 0x2
CPU part\t: 0x800
CPU revision\t: 0
"""

KERNEL_VERSION = (
    "Linux version 5.15.104-android13-8-00002-g3f1c2a7e5b1d-ab11074668 "
    "(builder@buildhost) (Android (10087095, +pgo, +bolt, +lto, +mlgo, based on r487747c) "
    "clang version 17.0.2) #1 SMP PREEMPT Wed Mar 6 10:00:00 UTC 2024\n"
)

CMDLINE = (
    "console=ttyMSM0,115200n8 androidboot.hardware=qcom "
    "androidboot.verifiedbootstate=green androidboot.bootloader=unknown "
    "androidboot.force_normal_boot=1 buildvariant=user\n"
)

CGROUP = "0::/init\n"

ROOT_PROPS = {
    "ro.debuggable": "0",
    "ro.build.tags": "release-keys",
    "ro.build.type": "user",
    "ro.build.user": "builder",
    "ro.build.host": "buildhost",
    "ro.secure": "1",
    "ro.adb.secure": "1",
    "ro.kernel.qemu": "0",
    "ro.boot.qemu": "0",
    "ro.hardware": "qcom",
    "ro.board.platform": "kona",
    "ro.product.board": "kona",
    "ro.serialno": "",
    "ro.dalvik.vm.native.bridge": "0",
    "ro.product.cpu.abilist": "arm64-v8a,armeabi-v7a",
    "ro.product.cpu.abilist64": "arm64-v8a",
    "ro.product.cpu.abilist32": "armeabi-v7a",
    "gsm.sim.state": "READY",
    "gsm.operator.alpha": "CHINA MOBILE",
    "gsm.operator.numeric": "46000",
    "gsm.sim.operator.iso-country": "cn",
    "gsm.sim.operator.numeric": "46000",
    "ro.telephony.default_network": "9",
}


def _write_masks(adb: Adb) -> list[str]:
    adb.sh(f"mkdir -p {MASK_DIR}")
    files = {
        "cpuinfo": CPUINFO_QCOM,
        "version": KERNEL_VERSION,
        "cmdline": CMDLINE,
        "cgroup": CGROUP,
        "empty": "",
        "dmi_product": "SM-G9910\n",
        "dmi_vendor": "samsung\n",
        "dmi_board": "SM-G9910\n",
        "modules": "",
    }
    written = []
    for name, body in files.items():
        b64 = __import__("base64").b64encode(body.encode()).decode()
        adb.sh(f"echo {b64} | base64 -d > {MASK_DIR}/{name}")
        written.append(name)
    adb.sh(f"chmod 644 {MASK_DIR}/*")
    return written


def apply(adb: Adb, profile: dict | None = None, masks: bool = True,
          props: bool = True) -> dict:
    profile = profile or config.load_profile()
    adb.root()
    report: dict = {"masks": [], "props": {}, "errors": []}

    if masks:
        _write_masks(adb)
        targets = {
            "/proc/cpuinfo": "cpuinfo",
            "/proc/version": "version",
            "/proc/cmdline": "cmdline",
            "/proc/1/cgroup": "cgroup",
            "/.dockerenv": "empty",
            "/sys/class/dmi/id/product_name": "dmi_product",
            "/sys/class/dmi/id/board_name": "dmi_board",
            "/sys/class/dmi/id/sys_vendor": "dmi_vendor",
            "/proc/modules": "modules",
        }
        for target, src in targets.items():
            out = adb.sh(f"mount --bind {MASK_DIR}/{src} {target} 2>&1 || true")
            if "Invalid" in out or "denied" in out or "No such" in out:
                report["errors"].append(f"{target}: {out.strip()}")
            else:
                report["masks"].append(target)
        # /.dockerenv is (re)created by the container runtime at every start and
        # bind-mounting over it does not remove the dentry. Android's init remounts
        # / read-only, so flip it rw for the unlink, then put it back.
        adb.sh("mount -o rw,remount / 2>/dev/null; rm -f /.dockerenv 2>/dev/null; "
               "mount -o ro,remount / 2>/dev/null; true")
        # Hide Magisk's own trees from stat()/list() by shadowing them with an empty dir.
        adb.sh(f"mkdir -p {MASK_DIR}/emptydir")
        for d in ("/system/etc/init/magisk", "/debug_ramdisk"):  # NOT /sbin/.magisk: magiskd lives there
            adb.sh(f"mount --bind {MASK_DIR}/emptydir {d} 2>/dev/null || true")
        adb.sh(f"setprop net.hostname {profile.get('hostname', 'panther')}")

    if props:
        for key, val in ROOT_PROPS.items():
            adb.sh(f"magisk resetprop {key} {json.dumps(val)}")
            report["props"][key] = adb.prop(key)

    # A phone on a desk is discharging, not on AC at 100%.
    adb.sh("dumpsys battery set ac 0; dumpsys battery set usb 0; "
           "dumpsys battery set wireless 0; dumpsys battery set status 2; "
           "dumpsys battery set level 76; dumpsys battery set temperature 305")
    report["verify"] = {
        "cpuinfo_head": adb.sh("head -1 /proc/cpuinfo").strip(),
        "version": adb.sh("head -1 /proc/version").strip(),
        "cmdline": adb.sh("head -1 /proc/cmdline").strip(),
        "cgroup": adb.sh("cat /proc/1/cgroup").strip(),
        "dockerenv": adb.sh("test -e /.dockerenv && echo present || echo hidden").strip(),
        "debuggable": adb.prop("ro.debuggable"),
        "tags": adb.prop("ro.build.tags"),
        "bridge_prop": adb.prop("ro.dalvik.vm.native.bridge"),
    }
    return report


def status(adb: Adb) -> dict:
    return {
        "cpuinfo": adb.sh("head -1 /proc/cpuinfo").strip(),
        "version": adb.sh("head -1 /proc/version").strip(),
        "cgroup": adb.sh("cat /proc/1/cgroup").strip(),
        "dockerenv": adb.sh("test -e /.dockerenv && echo present || echo hidden").strip(),
        "debuggable": adb.prop("ro.debuggable"),
        "tags": adb.prop("ro.build.tags"),
        "bridge": adb.prop("ro.dalvik.vm.native.bridge"),
        "hostname": adb.sh("cat /proc/sys/kernel/hostname").strip(),
    }
