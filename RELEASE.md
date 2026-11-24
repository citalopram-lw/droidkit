# Release notes

## v0.2.1 — touch correctness fixes

三处修复，都是 v0.2.0 实测暴露出来的：

- **可执行入口**：新增 `droidkit/__main__.py` 与 `pyproject.toml` 的
  `[project.scripts]`，`pipx install .` 后直接敲 `droidkit touch tap ...`；
  不安装也可 `python -m droidkit`。
- **每帧都是完整接触**：新增 `ABS_MT_WIDTH_MAJOR`，MOVE 帧一律携带
  `pressure + touch_major + width_major`（此前可出现 `size=0.000 major=0.000` 的帧）。
- **按下帧单帧闭合**：`down` 以前发成两帧（第一帧没有 `BTN_TOUCH`），InputReader
  按 hover 处理导致整条手势静默消失；现在 `SLOT/ID/X/Y/PRESSURE/MAJOR/WIDTH/BTN_TOUCH/SYN`
  一帧发出。
- **首帧竞争**：`touch ensure` 结束后做一次状态栏角落的预热按压；同时清理已销毁设备的
  残留 `/dev/input/eventN`（EventHub 会一直抱着旧节点，导致新设备"已绑定但不收事件"）。

实测（探针 `logcat -s TouchProbe`）：`ensure` 后立刻 tap → 首次即落（`ACTION_DOWN` 1/1）；
300 ms 滑动 → `size=0` / `major=0` 帧数 **0**；单元测试 12 → **16**。


## v0.2.0 — human-like touch (uinput injector)

新增 `droidkit touch`：在容器内自建 uinput 触摸屏（`fts_ts` / BUS_I2C /
INPUT_PROP_DIRECT），事件带真实 `deviceId`、压力与接触面积。

- 手势：tap / long press / swipe（贝塞尔 + 抖动）/ scroll，按压 58–128 ms、
  落点高斯 σ=1.5 px、控件矩形内缩 15 %
- 定位：`ui_dump` → 选择器（resource-id / text / content-desc / 包含）
- MCP：新增 `touch_tap` / `touch_long_press` / `touch_swipe` / `touch_scroll` /
  `touch_ui` / `touch_status` / `touch_ensure`（33 个工具）
- 交互画面：`droidkit touch screen`（scrcpy，`--watch` 为只读）
- 宿主机隔离：`docker/udev-ignore.rules` 让 libinput 忽略该设备
- 验证：探针实测 `deviceId=6 / devName=fts_ts / toolType=1 / pressure 0.35–0.46 /
  size 0.20–0.24 / major 52–61`；`--hold 700` 实测 700.087 ms；12 个单元测试

已知限制：仅单指（多点未实现）；容器重启后需 `droidkit touch ensure`；
Xposed 应用内合成 MotionEvent 未实现（uinput 已覆盖系统 UI 与全部应用）。


## v0.1.1 — 首个带预编译产物的发布

代码无功能性变更，补齐了"能直接用"的三件事：

- **预编译 APK**：`droidkit-hooks.apk`（模块，25 KB）、`droidkit-probe.apk`（探针，12.7 KB），
  自签名，`adb install -r -g` 即可；签名证书指纹见下方，自行编译会得到不同指纹。
- **许可证改为 Apache-2.0**：全文 + `NOTICE` + 源文件 SPDX 头。
- **文档**：支持/免责声明、`DONATE.md`、`FUNDING.yml`；CI（byte-compile + CLI smoke）。

两个 profile（`pixel-7` 软件渲染 / `pixel-7-hw` 硬件直通）不变，仍随仓库提供。


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
