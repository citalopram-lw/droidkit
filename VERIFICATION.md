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

## 12. 小步点 GPS 两处坑（2026-11-23 实测，已在模块里修）

跑通登录态后，容器里踩到两个「明明在喂定位却报 GPS 错」的问题，都只有实测能发现：

1. **静止 >20–25 s 判「无法获取GPS定位」**。即使 1 Hz 持续推 fix（`pushes` 在涨、`age≈1000 ms`、
   `listeners=4~8`），小步点仍会弹红屏「无法获取GPS定位」——它看的是位置有没有在动。
   之前 `hold` 会停掉 step、只保留 push，仍会被判死。修法：模块新增 `shuffle [r]`
   （默认 4 m 半径、0.6 m/s 原地绕小圈），到点等待改成 `shuffle 4`；实测静止 30 s
   仍是黄播放键、地图正常。
2. **不能用 `am start` 直接拉起跑动页**。`am start -n ...sport.run.RunAdvancedActivity`
   进去后定位客户端没初始化，必然报「无法获取GPS定位」；必须走 App 自己的
   主页 → 跑步 键的流程。

旁证（`status` 里新加的计数）：`listeners / pushes / age / gnss` —— 用来区分
「模块没在推」和「App 不认」，排查先看这四个数。

## 13. 容器重启后要恢复的东西（`live/ensure_env.sh` 一键）

`adb root`（shell uid 会被 Magisk 拒）、docker 桥默认路由、`net.dns1/2`、
`/system/etc/hosts` 反广告 bind mount、`mttouch_pinch` 二进制、模块 scope。
`/dev/input` 是 tmpfs，uinput 设备节点由 `mttouch_pinch` 每次自建（minor 必须读
`/sys/class/input/eventN/dev`，不能按 `64+N` 算）。

## 14. 学分跑有效性的硬约束（2026-11-23 实测，dk31 容器）

App：run.xbud.android 2.6.8，规则页原文「依次经过系统分配的点位完成跑步 / 里程至少 1 公里 /
配速 3'30"–10'00" / 步频 50–300 / 超出 4 公里以外部分不计入成绩」。

**结束前的四项判定**（长按「结束」6 s 才弹出）：
| 项 | 要求 | 教训 |
|---|---|---|
| 步频 | 50–300 步/分 | **必须显式 `cadence 3.34`**；不注入则整趟不计成绩（实测 1.99 km 作废） |
| 配速 | 3'30"–10'00" | App 显示配速 ≈ 注入速度 + 约 2.5 m/s 的 GPS 抖动底噪 |
| 里程 | ≥1 km | — |
| 点位 | 依次经过 | **不跑点即使 4.17 km 也不计入**（实测首页总里程不变） |

**模块指令通道的四个坑**：
1. `cmd` 文件 1 Hz 单次消费 —— 连发两条会互相覆盖（`nav` 被 `cadence` 吃掉）；
   写完要等文件消失再发下一条。
2. 新进程里 `pos=null`，直接 `nav` 会瞬移到目标点 —— 先 `start` 初始化 pos。
3. `shuffle` 是粘住的 —— 不先 `stop`，之后所有 `nav` 都被忽略。
4. 静止 >20–25 s → App 弹「无法获取GPS定位」遮罩，**吞掉所有点击**（结束按钮点不动就是这个）。

**UI 操作**：结束流程 = ← 进简化视图 → 暂停 → **长按「结束」6 s** → 弹判定清单 →「结束运动」。
锁定态只有长按 5 s 才能解锁；气泡「下一个点位」常盖住针，检测不到针时用气泡位置 +55 px 近似。

**有效区域**：出校园边界会弹「你已脱离有效区域，脱离期间自动暂停」，里程与计时双停。
中心取 29.4488,119.2644，半径 110 m 绕圈可长期稳定。

## 15. 可跑通的自动化配方（2026-11-24 实测，一次计入 4.00 km）

**结果**：总里程 16.30 → 20.30 KM；单趟 App 记 4.44 km（超 4 km 部分不计），配速 8'47"–9'27"，
点位 2 个打勾 + 2 次「点位已切换」，结束判定四过。日志 `/tmp/rp_fast.log`。

**顺序**（每一步都有坑，别换顺序）：
1. `python start_run.py` —— 自动处理「放弃未完成」「自动结束」弹窗 + GPS 门禁 + `cadence 3.34` + nav 预热。
2. `python run_points.py --minutes N --collect --speed-max 3.2` —— 分割模型选向 + 找针。
3. 到点后如果「点位没变」→ **网格搜索**：估计点周围 ±30/45/60 m、15 m 步长，每格停 3 s，
   让 App 自己判「到达」（地图定位有 ±40 m 噪声，绕圈碰不到判定圈）。
4. 配速被停等拖高时把 `--speed-max` 提到 3.0–3.2 拉回来（累计配速必须 < 10'00"）。
5. `python finish.py` —— ← 进简化视图 → 暂停 → 长按「结束」6 s → 判定弹窗 → 「结束运动」。
6. 记录页会弹激励视频广告，关闭按钮 `content-desc=inter-close-button_closeBtn`，按 **uiautomator 查 bounds** 再点，
   写死坐标会点在视频上（实测 (183,1415) 有效）。

**开机后必做**（主机重启会让容器变砖，症状：servicemanager 僵尸、zygote restarting、adb offline）：
```bash
docker run --rm --privileged --pid=host -v /:/host alpine chroot /host \
  sh -c "modprobe binder_linux; mkdir -p /dev/binderfs; mount -t binder binder /dev/binderfs"
docker restart dk31 && bash live/ensure_env.sh
```
不做这一步，Magisk 会半应用（magiskpolicy SIGABRT），**hook 的 native 部分会把 App 打崩**（runtime.cc 回溯），
表现是 Splash 一闪就回桌面。
