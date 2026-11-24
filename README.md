# DroidKit — 在 Linux 上跑安卓应用（redroid 15）

[![ci](https://github.com/citalopram-lw/droidkit/actions/workflows/ci.yml/badge.svg)](https://github.com/citalopram-lw/droidkit/actions/workflows/ci.yml) [![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

> Android-in-Linux device platform: container lifecycle, performance tuning, virtual
> sensors/GPS injection, anti-virtualization audit & hardening, and an MCP server.
> Two profiles ship: `pixel-7` (software rendering) and `pixel-7-hw` (host GPU).

一个可复用的 Android-in-Linux 设备平台：容器编排、性能调优、**虚拟传感器/GPS 注入**、
**反虚拟化检测与加固**、**MCP 接入**。

```
droidkit/
├── droidkit/            Python 控制面（CLI + MCP + 审计 + 加固）
├── android/module/      Xposed 模块：虚拟传感器 / 合成 GPS / Build 指纹 / 文件隐藏
├── android/probe/       x86_64 探针 app（验证传感器链路）
├── docker/magisk31.sh   构建 Magisk 31.1 bootless 镜像（必须，见下）
├── profiles/            设备指纹档案（Pixel 7 / Pixel 7 + GPU）
└── scripts/droidkit     命令行入口
```

## 快速开始

> 不想自己编译：Releases 页有已签名的 `droidkit-hooks.apk` 与 `droidkit-probe.apk`。
> 第一个容器仍然需要按下面的步骤构建镜像。


```bash
cd ~/droidkit
bash scripts/droidkit doctor                 # 宿主机前提（binderfs / adb / 数据目录）
bash scripts/droidkit image build            # droidkit/redroid:15-magisk（libnb 修复）
bash docker/magisk31.sh                      # + Magisk 31.1（Zygisk 才能用于 A15）
bash docker/hide_bridge.sh                   # 翻译库改名 + 旧文件 whiteout（stealth 镜像）
bash scripts/droidkit up                     # 起容器 → 等开机 → 性能调优 → 加固
bash scripts/droidkit status
```

默认容器 `dk31`（端口 5564，镜像 `15-magisk31-stealth`）。

以上默认值即 `dk31` / `5564` / `15-magisk31-stealth`；要改实例用环境变量覆盖
（`DROIDKIT_CONTAINER`、`DROIDKIT_PORT`、`DROIDKIT_DATA`、`DROIDKIT_IMAGE`）。

## 为什么必须 Magisk 31.1

| 版本 | 现象 |
|---|---|
| 25.2（上游 erstt 镜像） | Zygisk 不认识 A15 的 `Zygote#nativeForkAndSpecialize` 签名 → 模块进不了 app；且 `native bridge has been reset` → ARM 翻译被拆，目标应用启动即 SIGSEGV |
| 31.1（本项目的 bootless 布局） | 模块注入正常，ARM 翻译保留：目标应用在 `lib/arm64` 翻译进程里跑通登录页，四个 hook 组全部安装 |

`docker/magisk31.sh` 复刻 redroid-script 的 bootless 配方（`magisk --setup-sbin` + `/sbin` 临时目录）。
注意：`bootanim.rc` 必须是 `0644 root:root`，否则 init 以 `Skipping insecure file` 静默跳过。

## 传感器接口模拟

redroid 没有 sensors HAL（`dumpsys sensorservice` → `No Sensors on the device`，`devInitCheck: -19`）。
本项目的做法是**进程内虚拟传感器**，不碰 HAL：

- `SensorManager.getSensorList / getDefaultSensor` → 返回 11 个合成传感器
  （加速度计/陀螺/磁力/光感/距离/气压/重力/线性加速度/旋转矢量/计步器/步伐检测）
- `registerListener` → 接住监听者，50 Hz 灌合成采样；**加速度计波形（≈3.34 Hz）让 app 自己的
  计步算法数步**，因此步频/步数与配速天然自洽
- `LocationManager` → 按折线路线 + 固定速度插值，1 Hz 回调（accuracy/speed/bearing/time 齐全）
- `Build.*` 字段 + `java.io.File.exists` → 指纹伪装与 root 痕迹隐藏

控制面（宿主机写文件，模块轮询）：

```bash
bash scripts/droidkit sensor route --lat 31.2304 --lng 121.4737 --radius 60 --speed 2.8 --cadence 3.34
bash scripts/droidkit sensor cmd start|stop|hold|status|speed\ 3.0|seek\ 29.44,119.26
bash scripts/droidkit sensor status
bash scripts/droidkit module install --scope com.example.app
```

模块配置文件在 `/data/local/tmp/droidkit/config.json`，注入目标在 `targets.txt`。

**已验证**（x86_64 探针 + 目标应用）：

```
SensorProbe: sensor_count=11 ... accel=LSM6DSO Accelerometer
SensorProbe: EVENT type=1 values=0.106 0.219 11.194   ← 加速度波形
SensorProbe: EVENT type=18 values=1.000               ← 步伐检测
SensorProbe: gps=31.2304,121.4737 acc=3.0 speed=2.8 bearing=41.0
DroidKit: injected pkg=com.example.target ... library_path=/lib/arm64
```

## 反虚拟化检测（audit）与加固（stealth）

```bash
bash scripts/droidkit audit            # 40 项，按 build/kernel/container/root/files/sensors/hardware/network/debug 分类
bash scripts/droidkit audit --json     # 给 agent / CI 用
bash scripts/droidkit stealth apply    # /proc 遮蔽 + resetprop + 电池 + 隐藏 Magisk 树
bash scripts/droidkit stealth status
```

加固实测（dk31，同一容器内前后对比）：

| 项 | 加固前 | 加固后 |
|---|---|---|
| anti-virtualization score | 32/100 | **52/100** |
| /proc/cpuinfo | GenuineIntel Xeon | `processor : 0` + ARM 特征 |
| /proc/version | 7.0.0-43-generic | 5.15.104-android13 |
| /proc/cmdline | redroid 参数 | qcom 启动参数 |
| /proc/1/cgroup | — | `0::/init` |
| ro.debuggable / tags | 1 / test-keys | 0 / release-keys |
| ro.dalvik.vm.native.bridge | libnb.so | 0 |

**能力边界（不要当成"过所有检测"）**：`uname(2)` 仍是宿主内核、`/proc/self/mountinfo` 仍有
overlay 路径、无 telephony/NFC/相机 HAL——这些需要内核层或 HAL 层工作，当前项目不含。
市面检测器若只读 Build/props/文件/常见 /proc，加固后可过；做 mountinfo/uname 深检的仍能识破。

## 性能

```bash
bash scripts/droidkit perf tune                 # 关动画/校验器、dex2oat speed、cpuset+cpu-shares
bash scripts/droidkit perf compile <pkg>        # AOT 编译
bash scripts/droidkit perf bench <pkg> --runs 5 # am start -W 冷启动中位数
bash scripts/droidkit perf renderer
```

容器本身是原生内核上的 chroot（无 QEMU 指令翻译），CPU 性能接近裸机；瓶颈在软渲染
（`gpu_mode=guest`，SwiftShader）。有可用 GPU 时改 profile 的 `gpu_mode=host` 可上硬件 GL。

## MCP 接入

```bash
bash scripts/droidkit mcp        # stdio JSON-RPC（MCP 2024-11-05）
```

Hermes / Claude Desktop 配置：

```json
{
  "mcpServers": {
    "droidkit": {
      "command": "bash",
      "args": ["/home/iu/droidkit/scripts/droidkit", "mcp"]
    }
  }
}
```

工具面（26 个）：`device_status/up/down/restart`、`shell`、`app_list/install/launch/stop`、
`screen_shot`、`input_tap/swipe/text/key`、`ui_dump`、`logcat`、`sensor_config/route_circle/cmd/status`、
`module_install`、`stealth_apply/status`、`audit_run`、`perf_tune/bench`。

## 已知限制

1. **系统级传感器仍为空**：`dumpsys sensorservice` 看不到传感器；只有被模块注入的进程才看到虚拟传感器。
   若要对任意检测器 app 伪装，把该 app 加进 `targets.txt` / scope 即可。
2. **加固不覆盖内核层**：`uname`、`/proc/self/mountinfo`、`/sys/class/dmi` 仍可能暴露容器。
3. **ADB 是明文 TCP**：生产用请只绑 127.0.0.1（默认如此）。
4. 每个容器重启后 `/proc` 遮蔽与 resetprop 会丢，`droidkit up` / `stealth apply` 重新施加。

## 参考（本次实测得出的坑）

- 上游镜像 `ro.dalvik.vm.native.bridge=libnb.so` 但文件不存在 → 必须 `cp libndk_translation.so libnb.so`。
- ARM APK 必须 `adb install --abi arm64-v8a`，否则按 x86 原生跑，`EM_AARCH64`。
- LSPosed/Vector 拒绝**把 Xposed API 类打进 APK** 的模块（`Unsupported class loader` +
  `The Xposed API classes are compiled into the module's APK`）。本项目 `build.sh` 用 stub jar 只做编译期依赖。
- Vector 3119 的 `hookAllMethods` 返回 `Set<Unhook>`（不是单个 `Unhook`），stub 签名必须一致。
- `wrap.<pkg>` + LD_PRELOAD 可用，但会丢掉 `primaryCpuAbi`，翻译应用不能走这条路。

## 两个可并行运行的版本

| | `dk31`（软件渲染） | `dk31-hw`（硬件直通） |
|---|---|---|
| profile | `pixel-7`（`gpu_mode=guest`） | `pixel-7-hw`（`gpu_mode=host`） |
| GPU | SwiftShader（ANGLE→Vulkan→pastel） | **AMD FirePro W5100 / radeonsi, Mesa 24.0.8** |
| EGL / gralloc | angle / redroid | mesa / gbm（容器需 `--device /dev/dri`） |
| 探针冷启动 | 1071 ms | **254 ms（4.2×）** |
| 目标应用冷启动 | 2461 ms | **1982 ms（1.24×）** |
| 反检测 | 全量隐身口径 | 弱一档：`ro.hardware.egl=mesa`、`gralloc=gbm` 本身是模拟器/容器味 |
| 端口 / 数据 | 5564 / `dk31-data` | 5566 / `dk31-hw-data` |

起硬件版：

```bash
DROIDKIT_CONTAINER=dk31-hw DROIDKIT_PORT=5566 \
DROIDKIT_DATA=/mnt/vms/redroid/dk31-hw-data \
bash scripts/droidkit up --profile profiles/pixel-7-hw.json   # profile 里 gpu_mode=host 会自动带 --device /dev/dri
```

踩坑：**hw 容器必须带齐 `ro.product.cpu.abilist64/32`**，否则 zygote 直接
`Abort message: app_process: Unable to determine ABI list from property ro.product.cpu.abilist64` 崩循环。

## 版本

| tag | 内容 |
|---|---|
| `v0.1.0-soft` | 软件渲染（SwiftShader）实例，反检测口径完整，默认 profile `pixel-7` |
| `v0.1.0-hw` | 同一代码 + `pixel-7-hw`（`gpu_mode=host`，`--device /dev/dri`），探针冷启动 1071→254 ms |

两个 tag 指向同一棵树，差异只在 profile 与启动参数，见 `RELEASE.md`。

## 屏幕与触控

`droidkit touch` 通过容器内自建的 uinput 触摸屏注入手势，事件带真实
`deviceId`、压力与接触面积，而不是 `adb shell input` 的注入痕迹：

| 字段 | `adb shell input` | DroidKit |
|---|---|---|
| deviceId / 设备名 | `-1` / `Virtual` | `6` / `fts_ts` |
| pressure / size / major | `1.0` / `1.0` / `0` | `0.35–0.46` / `0.20–0.24` / `52–61` |
| 事件序列 | DOWN, UP | DOWN, MOVE…, UP |

```bash
droidkit touch ensure                      # 起注入守护进程 + 建 /dev/input 节点
droidkit touch tap --text 登录              # 按文本点（也可 --id / --desc / 坐标）
droidkit touch swipe 540 1400 540 600 --ms 250
droidkit touch scroll down 700
droidkit touch screen                      # scrcpy 窗口，鼠标/触摸直接操作
```

参数、拟人化模型、宿主机 udev 隔离和已知限制见 [TOUCH.md](TOUCH.md)。

## 许可

Apache License 2.0，全文见 `LICENSE`，版权与归属见 `NOTICE`。

**用途声明**：本项目仅用于自有设备、授权测试与安全研究。使用者需自行确认其行为符合当地法律与
所涉服务条款；作者不对任何滥用、账号封禁或由此产生的损失承担责任。软件按 "AS IS" 提供，无任何担保。

## 支持这个项目

业余时间维护，无商业支持、不卖任何东西。如果它帮你省了时间，可以请我喝杯咖啡——完全自愿，
不影响任何功能。

| 网络 | 地址 |
|---|---|
| Base (ETH / USDC) | `0x3dAC56CfFf3314DAF8aA146f3b811f4aa0ADd0C0` |
| BNB Chain (BNB / USDT-BEP20) | `0x3dAC56CfFf3314DAF8aA146f3b811f4aa0ADd0C0` |
| Tron (USDT-TRC20) | `TVH3DKjhd7CwD3qhEPaSkBMLTJezGaXRAV` |

EVM 链（Base / BNB Chain / Ethereum / Arbitrum）共用同一地址，选对网络即可；Tron 独立。

转账前核对地址首 6 位与末 6 位、确认网络一致（跨链无法找回）；打赏是赠与，不构成服务购买，
也不提供优先支持。详见 [`DONATE.md`](DONATE.md)。

## 免责声明

本项目按 "AS IS" 提供，不附带任何担保。作者不对设备损坏、数据丢失、账号封禁或任何间接损失
负责。仅供自有设备、授权测试与安全研究使用；使用者自行确保合规。详见 [`DONATE.md`](DONATE.md#免责声明--disclaimer)。
