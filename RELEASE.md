# Release notes

## v0.1.0-soft — software rendering (default)

Redroid 15 device platform with Magisk 31.1 + Zygisk + Vector, built so that
ARM-translated apps and injected modules coexist.

Included:
- container lifecycle + perf tuning (`droidkit up/status/perf`)
- virtual sensors (11 types), accelerometer waveform → real cadence, synthetic GPS
- anti-virtualization audit (40 checks) + hardening (`stealth apply`)
- MCP server, 26 tools
- module + probe sources, reproducible image scripts

Measured on the reference host (Xeon E5-2666 v3, 20 threads):
- probe cold start: **1071 ms**
- packed ARM app cold start: **2461 ms**
- container CPU idle: 5.75 %, RAM 1.3 GiB
- audit score: 32 → **62** after hardening; translation-library signatures
  (`libnb.so`, `libndk_translation_proxy_*`) removed from `/proc/self/maps` and from disk.

## v0.1.0-hw — host GPU

Same tree, profile `pixel-7-hw` (`androidboot.redroid_gpu_mode=host`, `--device /dev/dri`).

- renderer: AMD FirePro W5100 / radeonsi, Mesa 24.0.8, OpenGL ES 3.2
- probe cold start: **254 ms** (4.2× vs software)
- packed ARM app cold start: **1982 ms**
- trade-off: `ro.hardware.egl=mesa` and `ro.hardware.gralloc=gbm` are themselves
  emulator/container tells, so this profile is for performance, not for anti-detection.

## Known limitations (both)

- `uname(2)` still reports the host kernel; `/proc/self/mountinfo` still shows overlay paths.
- `/sbin/.magisk` is visible (Magisk's runtime mount point cannot be shadowed without
  breaking `su`).
- No telephony/camera/NFC HAL; `dumpsys sensorservice` is empty unless the module is
  scoped into the app.
- ARM command-line binaries do not run after the bridge rename (binfmt runner links the
  old `libndk_translation.so`); apps are unaffected.
