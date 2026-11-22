# DroidKit 验收证据（2026-11-23 实测）

全部来自本机真实命令输出，不是设计稿。环境：redroid 15 (x86_64) on Ubuntu, 内核 7.0.0-43,
容器 dk31 = `droidkit/redroid:15-magisk31`，adb `127.0.0.1:5564`。

## 1. 注入框架

```
$ adb shell /data/adb/modules/zygisk_vector/cli status
Framework Version: 2.2 / Version Code: 3119 / API Version: 102 / Enabled Modules: 1
$ adb shell /sbin/magisk -v
31.1:MAGISK:R
```
Magisk 25.2 时 Zygisk 报 `unknown signature of Zygote#nativeForkAndSpecialize` 且
`native bridge has been reset` → ARM 应用 SIGSEGV；31.1 无此问题。

## 2. 虚拟传感器（x86_64 探针 com.droidkit.probe）

```
SensorProbe: sensor_count=11
SensorProbe: SENSOR type=18 name=LSM6DSO Step Detector ...
SensorProbe: SENSOR type=19 name=LSM6DSO Step Counter  ...
SensorProbe: accel=LSM6DSO Accelerometer
SensorProbe: EVENT type=1  values=0.106 0.219 11.194
SensorProbe: EVENT type=18 values=1.000
SensorProbe: EVENT type=19 values=0.000..N
SensorProbe: gps=31.2304,121.4737 acc=3.0 speed=2.8 bearing=41.0
```
加速度波形 3.34 Hz 由模块生成，app 自己的计步算法数步 → 步频/步数/配速自洽。

## 3. ARM 翻译应用注入（目标应用 2.6.8）

```
DroidKit: route loaded: points=5 length=118m speed=2.8
DroidKit: injected pkg=com.example.target process=com.example.target pid=3504
          cls=...PathClassLoader[... lib/arm64, base.apk!/lib/arm64-v8a ...]
DroidKit: location hooks installed
DroidKit: sensor hooks installed
DroidKit: file hide hooks installed
mCurrentFocus=...com.example.target.mvp.ui.login.LoginActivity   (进程存活，未崩溃)
```
登录未做（按用户指示跳过），故未在跑步页取步频实拍值。

## 4. 反虚拟化

| 项 | 加固前 | 加固后 |
|---|---|---|
| audit score | 32/100 (13 clean / 27 tell) | 52/100 (21 clean / 19 tell) |
| /proc/cpuinfo | GenuineIntel Xeon E5-2666 v3 | `processor : 0` + ARM 特征 |
| /proc/version | 7.0.0-43-generic (Ubuntu) | 5.15.104-android13-8 |
| /proc/cmdline | redroid 参数 | console=ttyMSM0 + qcom |
| /proc/1/cgroup | 容器路径 | `0::/init` |
| ro.debuggable / ro.build.tags | 1 / test-keys | 0 / release-keys |
| ro.dalvik.vm.native.bridge | libnb.so | 0 |
| 电池 | AC powered 100% | discharging 76% 30.5°C |

仍可见（未解决，勿宣称"全过"）：`uname(2)` 宿主内核、`/proc/self/mountinfo` overlay 路径、
`/sys/class/dmi/id`、无 telephony/NFC/相机 HAL、`dumpsys sensorservice` 为空。

## 5. MCP

```
init: {'name': 'droidkit', 'version': '0.1.0'} 2024-11-05
tools: 26 [...]
device_status: {"exists": true, "running": true, "image": "droidkit/redroid:15-magisk31" ...}
shell: Pixel 7 | 1958
screen_shot: image bytes 1550113
sensor_config: {"route": [...], "speed": 2.8, "cadence_hz": 3.34 ...}
```
客户端脚本：`/tmp/mcp_test.py`（初始化 / tools.list / 4 个 tools.call 全通过）。

## 6. 踩过的坑（已在 README 与代码里固化）

1. `libnb.so` 缺失 → `cp libndk_translation.so libnb.so` + 改 build.prop。
2. `bootanim.rc` 权限 0664 → init `Skipping insecure file` 静默不执行。
3. Xposed API 类打进模块 APK → Vector `Unsupported class loader` 拒绝加载。
4. `hookAllMethods` 返回值是 `Set<Unhook>`，stub 写单个 `Unhook` → `NoSuchMethodError`。
5. 抽象方法（`SensorManager.getFullSensorList`）不能 hook → 抛异常会中断整组 hook，已逐组 try/catch。
6. `wrap.<pkg>`+LD_PRELOAD 会丢 `primaryCpuAbi`，翻译应用不能用。
7. stealth 里 bind 空目录到 `/sbin/.magisk` 会打断 magiskd/su，已移除。

## 7. maps / native stat 实测（q3 C 口径：黑名单 = high/critical）

在 `com.example.target` 进程内（模块自测，绕过 Java 层 hook，走 native stat）：

```
maps_scan hits=10
  /system/lib64/libndk_translation_proxy_libc.so   (proxy 库，20 个)
  /system/lib64/libnb.so
stat_scan
  /system/bin/su=gone          /data/adb/magisk=gone
  /system/lib64/libnb.so=visible
  /system/lib64/libndk_translation.so=visible
  /sbin/.magisk=visible
```

结论：黑名单签名（libnb / libndk_translation_proxy_*）**仍全部命中**，high/critical 未通过。
尝试过的改名（bridge → `libqc_platform.so` + 20 个 proxy 改名 + build.prop 改写）**运行时未生效**：
`ro.dalvik.vm.native.bridge` 的值来自别处（prop.default / 启动参数，getprop 前缀匹配一次返回两个值），
且旧文件仍在 /system 下。要真关掉这条，需要：删旧文件（镜像 export/import）+ 找到并改写 prop 的真正来源
+ 全量回归 ARM 翻译。按用户指示（半成品先收口）顺延到下一阶段。

## 8. maps / stat 收口结果（最终）

镜像 `droidkit/redroid:15-magisk31-stealth`（`docker/hide_bridge.sh` 可复现）：
bridge 改名 `libqc_platform.so`、20 个 proxy 同步改名、`/system` 与 `/vendor` 两份 build.prop 都指向新名、
旧 `libnb.so` / `libndk_translation.so` 用 overlayfs whiteout 抹掉。

在 `com.example.target`（arm64 翻译进程）内实测：

```
maps_scan external=0 self=7
         external = 黑名单签名(libnb/libndk_translation/libzygisk/lspd/magisk/frida/houdini/lspatch/npatch) 命中数
         self     = 我们自己改名后的 libqc_platform 映射数（必须存在，不是已知名）
stat_scan /system/bin/su=gone  /data/adb/magisk=gone
          /system/lib64/libnb.so=gone  /system/lib64/libndk_translation.so=gone
          /sbin/.magisk=visible        ← 唯一残留
```

ARM 翻译未受影响：进程正常到 `LoginActivity`，模块注入正常。

残留原因：`/sbin/.magisk` 是 Magisk 的运行时挂载点（bootless 布局把 MAGISKTMP 设为 /sbin），
bind 空目录遮蔽会让 magiskd/su 失去 socket（实测 su 报 `Cannot connect to daemon`）。
要彻底消掉需改 bootless 的 MAGISKTMP 到别处并全量回归，风险高于收益，按半成品口径保留并记录。

## 9. 最终状态（交付）

容器 `dk31`，镜像 `droidkit/redroid:15-magisk31-stealth`，端口 5564，数据 `/mnt/vms/redroid/dk31-data`。

| 指标 | 数值 |
|---|---|
| maps 外部签名命中（ARM 应用内） | **0**（`external=0`，自身改名库 `self=7`） |
| native stat 可见的翻译库/root 路径 | libnb.so / libndk_translation.so / /system/bin/su / /data/adb/magisk **全部 gone**；`/sbin/.magisk` 仍 visible |
| audit 分数 | 32（基线）→ **58**（加固后） |
| 传感器 | 探针 11 个传感器 + 波形 + 步频事件 + 合成 GPS，全部实测 |
| ARM 注入 | 目标应用到登录页，模块四组 hook 全装 |
| MCP | 26 工具，initialize/tools.list/device_status/shell/screen_shot/sensor_config 实测通过 |

已知残留（不在半成品范围内，下一阶段再处理）：
`/sbin/.magisk`（Magisk 运行时挂载点）、`/proc/self/mountinfo` 的 overlay 路径、`uname(2)` 宿主内核、
telephony/camera/NFC 无 HAL、SwiftShader 渲染器字符串、`/.dockerenv`（脚本已加 whiteout，重建镜像即消）。

## 10. /.dockerenv 收口（用户要求"搭进去"）

镜像里 whiteout `/.dockerenv` **无效**：容器运行时每次 start 都会重建该文件（0 字节 root:root）。
真正的解法：Android init 把 / 重挂为 ro，`droidkit stealth apply` 现在做
`mount -o rw,remount / && rm -f /.dockerenv && mount -o ro,remount /`，实测：

```
$ ls /.dockerenv   → No such file or directory
$ mount | grep " / " → overlay on / type overlay (ro,...)   # 已恢复只读
```

audit 分数：32（基线）→ **62**（25 clean / 15 tell / 1 skip）。

剩余 15 条 tell 的类别：`ro.boot.redroid_*`/构建 props、mountinfo overlay 路径、`/sbin/.magisk`、
magiskd 进程、无 sensors HAL（shell 视角）、docker veth 网卡、无 wlan/telephony/camera/NFC HAL、
SwiftShader 渲染串、uname 宿主内核。均在 README "已知限制" 与 §9 中列明。

## 11. 硬件直通版本（dk31-hw）

`--device /dev/dri` + `androidboot.redroid_gpu_mode=host`，同一镜像、独立数据目录、端口 5566。

```
RenderEngine: renderer : AMD FirePro W5100 (radeonsi, bonaire, ACO, DRM 3.64, 7.0.0-43-generic)
RenderEngine: version  : OpenGL ES 3.2 Mesa 24.0.8
ro.hardware.egl=mesa   ro.hardware.gralloc=gbm
```

| 指标 | dk31（软件） | dk31-hw（硬件） |
|---|---|---|
| 探针冷启动中位数 | 1071 ms | **254 ms** |
| 目标应用冷启动中位数 | 2461 ms | **1982 ms** |
| 应用注入 / 登录页 | 正常 | 正常（pid 2162 / 2807） |

硬件版代价：`ro.hardware.egl=mesa`、`gralloc=gbm` 这两个 prop 本身就是容器/模拟器特征，
反检测口径比软件版弱一档；软件版保持原样未动。
