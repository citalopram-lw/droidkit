# Human-like touch (uinput injector)

DroidKit injects touch through a **kernel input device it creates itself**, not
through `adb shell input`. The difference is what an app — or an anti-automation
SDK inside it — can read off the `MotionEvent`:

| field | `input tap` (adb) | DroidKit uinput |
|---|---|---|
| `deviceId` | `-1` | `6` (real id) |
| `InputDevice.getName()` | `Virtual` | `fts_ts` |
| `toolType` | `1` (finger) | `1` (finger) |
| `pressure` | `1.000` | `0.35 – 0.46` |
| `size` | `1.000` | `0.20 – 0.24` |
| `touchMajor` | `0.000` | `52 – 61` |
| `source` | `0x1002` | `0x1002` |
| path | DOWN, UP | DOWN, MOVE…, UP |

Values above are from the probe app (`logcat -s TouchProbe`) on the reference
container, not from documentation.

## How it is put together

```
droidkit touch tap --text 登录
        │
        ├─ ui_dump → parse XML → selector match → element centre ± jitter
        │
        └─ dk_touchd (root, in container)
               └─ /dev/uinput → virtual touchscreen "fts_ts" (BUS_I2C, INPUT_PROP_DIRECT)
                      └─ /dev/input/eventN  (created by us, see below)
                             └─ InputReader → app: MotionEvent(deviceId=6, …)
```

Two non-obvious requirements, both learned the hard way:

1. **The node has to exist before EventHub looks.** ueventd inside the container
   does not create `/dev/input/eventN` for a uinput device, and EventHub opens
   the node exactly once — on the inotify `IN_CREATE` — and never retries. The
   node is therefore created with mode `0666` (so `system` can open it
   immediately) and tightened to `root:input 0660` right after.
2. **Every frame is a complete contact, closed by exactly one SYN.** Frames with
   only `ABS_MT_POSITION_X/Y` left InputReader pinned to the press position: the
   app saw DOWN…UP at the starting point and no ACTION_MOVE at all.

## Usage

The package ships a console entry point, so `droidkit` works after
`pipx install .` (or `pip install --user .`); without installing, use
`python -m droidkit` or `scripts/droidkit`.

```bash
droidkit touch ensure                     # start daemon, create the node (idempotent)
droidkit touch status                     # daemon / device / InputReader binding
droidkit touch ui                         # list elements with coordinates

droidkit touch tap 540 960                # raw coordinates (jittered)
droidkit touch tap --text 登录             # by visible text
droidkit touch tap --id com.example:id/go  # by resource-id
droidkit touch tap --text~ 设置 --wait 5   # contains match, wait up to 5 s
droidkit touch long --desc 图标 --hold 800 # long press
droidkit touch swipe 540 1400 540 600 --ms 250
droidkit touch scroll down 700            # one-finger fling
droidkit touch screen                     # scrcpy window, mouse/touch control
droidkit touch screen --watch              # read-only window, drive it with `droidkit touch`
```

`--raw` disables jitter and humanised timing (for pixel-exact tests only).

MCP exposes the same surface: `touch_tap`, `touch_long_press`, `touch_swipe`,
`touch_scroll`, `touch_ui`, `touch_status`, `touch_ensure`.

## Humanisation model

| parameter | value | why |
|---|---|---|
| landing point | Gaussian σ = 1.5 px, then inset to 15 % of the element box | a thumb never hits the centre twice |
| press duration | 58–128 ms | measured taps; below ~50 ms reads as injection |
| swipe path | quadratic Bézier with an off-midline control point + sine tremor | fingers pivot, they do not draw lines |
| swipe speed | ease-in-out over 180–320 ms | accelerate, coast, stop |
| long press | 550–900 ms (or `--hold`) | matches system long-press timeout of 400 ms + margin |
| double tap gap | 180–350 ms | reserved for the two-tap helper |
| think time | 0.3–2 s before a tap when a workflow asks for it | humans hesitate; scripts do not |

Measured on the reference container: `--hold 700` produced a **700.087 ms**
press at the kernel level; a `--ms 250` swipe produced 15 kernel frames at
~62 Hz. InputReader coalesces some frames on the way to the app (a 1200 ms
swipe reached the app as 18 ACTION_MOVE samples), which is normal for a 60 Hz
injection loop and does not change the gesture's end point.

## Host isolation (required)

The container shares the host kernel, so the uinput device is visible to the
host desktop too — and GNOME would treat our touches as a second touchscreen
driving the real pointer. `docker/udev-ignore.rules` marks the device with
`LIBINPUT_IGNORE_DEVICE=1`; Android's InputReader does not use udev, so
injection is unaffected.

```bash
sudo install -m 644 docker/udev-ignore.rules /etc/udev/rules.d/99-droidkit-touch.rules
sudo udevadm control --reload-rules && sudo udevadm trigger --action=change --subsystem-match=input
udevadm info /sys/class/input/eventN | grep LIBINPUT_IGNORE_DEVICE   # => =1
```

## Known limitations

- **Single finger only.** Multi-touch, pinch and two-finger scroll are not
  implemented yet (`ABS_MT_SLOT` is declared, the gesture layer does not use it).
- **The device lives inside the container.** Restarting the container drops it;
  `droidkit touch ensure` re-creates it (the module's `up` path calls it).
- **`scrcpy` control is not the injector.** Mouse clicks in a normal scrcpy
  window go through scrcpy's control socket and arrive as `deviceId=-1`. Use
  `--watch` and drive the device with `droidkit touch` when the event's
  provenance matters.
- **In-app MotionEvent synthesis (the Xposed half) is not implemented.** The
  uinput device covers system UI and every app; the in-process path would only
  add value on devices where root is unavailable.
- Element selectors depend on the app exposing its view tree. Canvas/WebGL/
  Flutter surfaces with no accessibility nodes need coordinates or image
  matching instead.
