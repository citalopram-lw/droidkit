"""Build the DroidKit Android image from the upstream Magisk-enabled redroid base.

The stock image ships libndk_translation.so but points ro.dalvik.vm.native.bridge
at libnb.so, which does not exist: ARM apps then load as x86 and every ARM .so
fails with EM_AARCH64. We fix the prop and add the bridge file, plus our own
build.prop hardening, using docker cp + commit (the Android image has no shell
usable by `docker build`).
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from . import config


def _run(cmd: list[str], check: bool = True, timeout: int = 900) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{p.stderr.strip()}")
    return p.stdout.strip()


def image_exists(image: str) -> bool:
    out = _run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"], check=False)
    return image in out.split()


def build(base: str = config.BASE_IMAGE, target: str = config.IMAGE,
          extra_props: dict[str, str] | None = None, force: bool = False) -> dict:
    if image_exists(target) and not force:
        return {"image": target, "built": False, "reason": "already exists"}

    cid = _run(["docker", "create", base])
    try:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            _run(["docker", "cp", f"{cid}:/system/build.prop", str(td / "build.prop")])
            props = (td / "build.prop").read_text()
            props = props.replace("ro.dalvik.vm.native.bridge=0",
                                  "ro.dalvik.vm.native.bridge=libnb.so")
            # The base is a userdebug build; keep it adb-rootable during setup but
            # publish release-looking values for apps that read them early.
            for key, val in (extra_props or {}).items():
                lines = [ln for ln in props.splitlines() if not ln.startswith(f"{key}=")]
                lines.append(f"{key}={val}")
                props = "\n".join(lines) + "\n"
            (td / "build.prop").write_text(props)
            _run(["docker", "cp", str(td / "build.prop"), f"{cid}:/system/build.prop"])

            _run(["docker", "cp", f"{cid}:/system/lib64/libndk_translation.so",
                  str(td / "libndk_translation.so")])
            _run(["docker", "cp", str(td / "libndk_translation.so"),
                  f"{cid}:/system/lib64/libnb.so"])
        _run(["docker", "commit", "-m", "droidkit: native bridge + props", cid, target])
    finally:
        _run(["docker", "rm", cid], check=False)
    return {"image": target, "built": True}
