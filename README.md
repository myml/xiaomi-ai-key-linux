# 小爱键（AI 键）的 Linux 完整方案

[![CI](https://github.com/myml/xiaomi-ai-key-linux/actions/workflows/ci.yml/badge.svg)](https://github.com/myml/xiaomi-ai-key-linux/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab.svg)](https://www.python.org/)
[![No dependencies](https://img.shields.io/badge/dependencies-none-success.svg)](#特性)

小米 / 红米笔记本键盘上那颗"小爱键"，在 Linux 下按了没反应。
**不是没驱动**：内核早就把它上报成了标准的 `KEY_ASSISTANT`（583）。
真正的原因是 **Qt 的按键映射表里没有 `XF86Assistant`**，于是 KDE 的快捷键
录制框把它当成 `Qt::Key_unknown`，你按什么都录不进去。

本项目绕开这个限制：直接读 `/dev/input/eventN`，把同一个键映射成
**按下 / 短按 / 长按** 三个独立的动作。

- 纯 Python 标准库，**单文件**，不需要 `python-evdev`、不需要编译、不需要常驻 root
- 按设备**能力**（keybit）发现设备，不绑死机型、不绑死 `event7`/`event8`
- 配置写错会告警，不会静默失效；`--check` 一条命令做完整自检
- 100+ 个单元测试 + GitHub Actions（Python 3.9 / 3.12 / 3.13 + shellcheck）

## 30 秒上手

```bash
git clone https://github.com/myml/xiaomi-ai-key-linux
cd xiaomi-ai-key-linux
./scripts/install.sh          # 中途要一次 sudo，用于装 udev ACL 规则
```

然后按一下小爱键：**短按打开 KRunner，长按打开终端**（默认配置）。

验证与排错：

```bash
./bin/xiaomi-key-daemon.py --check        # 一条命令检查权限、设备、服务、配置
journalctl --user -u xiaomi-key -f        # 实时日志
./bin/xiaomi-key-daemon.py --test         # 前台打印按键事件
```

## 为什么需要它

```
固件 → redmi_wmi 驱动 → 上报 KEY_ASSISTANT(583) → libinput → KWin
     → QXkbCommon::keysymToQtKey(XF86Assistant) → 0 = Qt::Key_unknown → 录制框空白
```

实测证据（Qt 6.11.2）：

| evdev 键名 | code | keysym | `Qt::Key` | 能绑定 |
|---|---|---|---|---|
| `KEY_ASSISTANT` | 583 | `XF86Assistant` | `0` | ❌ |
| `KEY_F13` | 183 | `XF86Tools` | `0x010000f1` | ✅ |
| `KEY_SWITCHVIDEOMODE` | 227 | `XF86Display` | `0x010000d1` | ✅ |

所以只有两条路：**让键变成 Qt 认识的键**（hwdb 重映射成 F19），
或**绕过 Qt**（本项目的守护进程）。完整链路、复现命令和内核事件结构见
[docs/how-it-works.md](docs/how-it-works.md)。

## 兼容性

| 机型 | 输入设备 | 键码 | 状态 |
|---|---|---|---|
| Redmi Book 16 2024 | `Redmibook WMI keys` | 583 `KEY_ASSISTANT` | ✅ 实测（Fedora 44 / Plasma 6.7.5 / Wayland / kernel 7.2.6） |
| 其他小米 / 红米机型 | 名称含 `WMI keys` | 待测 | 🧪 见 [docs/other-models.md](docs/other-models.md) |

守护进程本身与发行版、桌面、X11/Wayland 无关，只要能用 `systemd --user`。
换机型只需改 `KEY_CODES`，必要时改 `DEVICE_NAME` 或 udev 规则里的 glob。

## 配置

配置文件：`~/.config/xiaomi-key/action.conf`（可用 `--config` 或
`$XIAOMI_KEY_CONFIG` 覆盖）。改完：

```bash
systemctl --user reload xiaomi-key     # 只重读配置，不中断设备
systemctl --user restart xiaomi-key    # 改了 udev/程序本身时用这个
```

| 选项 | 默认 | 说明 |
|---|---|---|
| `DEVICE_NAME` | 空 | 设备名的 **Python 正则**。留空 = 任何上报目标键码的设备 |
| `KEY_CODES` | `583` | 监听的键码，可用逗号/空格分隔多个；做过重映射就填 `189` |
| `PRESS` | 空 | 按下瞬间执行 |
| `SHORT_PRESS` | KRunner | 松手时执行（未被 `PRESS`/`LONG_PRESS` 消费时） |
| `LONG_PRESS` | `konsole` | 按住超过阈值后执行 |
| `LONG_PRESS_MS` | `600` | 长按阈值，最小 50 |
| `FEEDBACK` | 空 | 每次触发弹一个 `notify-send` 通知 |
| `SHELL` | 空 | 执行动作的 shell，空 = `/bin/sh` |
| `DRY_RUN` | `0` | 只记日志不执行，适合试配置 |
| `LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error` |

三个槽位的组合规则（全部由 `tests/test_state_machine.py` 覆盖）：

| 你填了 | 快按一下 | 按住不放 |
|---|---|---|
| `PRESS` | 按下即执行 | 按下即执行 |
| `SHORT_PRESS` | 松手才执行 | 不执行 |
| `PRESS` + `LONG_PRESS` | PRESS | PRESS，然后 LONG_PRESS |
| `SHORT_PRESS` + `LONG_PRESS` | SHORT_PRESS | LONG_PRESS |
| `PRESS` + `SHORT_PRESS` | 只有 PRESS（SHORT 永远不触发，加载时告警） | — |

所以：**"短按 A、长按 B" 就填 `SHORT_PRESS` + `LONG_PRESS`，别填 `PRESS`**。
按住的自动重复事件（`value=2`）会被忽略，按住不会连发。

一个例子：

```ini
SHORT_PRESS=spectacle -r -b -c -n                    # 区域截图到剪贴板
PRESS=                                   # 留空
LONG_PRESS=espeak-ng "$(wl-paste)"       # 朗读剪贴板
LONG_PRESS_MS=600
```

更多现成命令（KRunner、锁屏、静音、剪贴板历史……）见
[`config/action.conf.example`](config/action.conf.example)。

## 命令速查

| 命令 | 作用 |
|---|---|
| `xiaomi-key-daemon.py` | 正常运行（一般由 systemd 拉起） |
| `--check` | 自检：Python、配置、设备、权限、udev、服务、命令是否存在、方案冲突 |
| `--list` | 列出所有输入设备、它们的 keybit、哪些匹配 |
| `--test` | 前台打印该设备的全部按键事件（含未绑定的键码） |
| `--dry-run` | 只记录动作，不执行 |
| `--device /dev/input/eventN` | 跳过自动发现，直连指定节点 |
| `--once` | 设备消失后退出（调试用） |
| `-v` / `-q` | 调试日志 / 只报错误 |
| `--version` | 版本 |

## 另一种方案：重映射成 F19

如果你只想要"一个像快捷键一样的键"，并且希望它和系统里其他快捷键一起管理，
可以改用 hwdb 把 583 重映射成 F19，然后在 **系统设置 → 快捷键** 里正常录制：

```bash
./scripts/remap-key.sh          # 自动探测设备名、写 hwdb、打印下一步
# 注销并重新登录（KWin 缓存了 keybit）
```

| | 守护进程（本项目主推） | hwdb 重映射 |
|---|---|---|
| 长按 | ✅ | ❌（释放事件被丢弃） |
| 按下 / 短按 / 长按 | ✅ 三个槽位 | ❌ 只有"按下" |
| 绑定位置 | `action.conf` | 系统设置 → 快捷键 |
| 需要重登 | 不需要 | 需要 |
| 和其他快捷键统一管理 | ❌ | ✅ |

**两者互斥**：重映射后设备上报 189，守护进程默认监听 583 就收不到事件。
`--check` 和 `install.sh` 都会检测并提醒。细节（为什么是 F19、为什么两行
scancode、`reserved` 为什么不能写 `0`）见
[docs/how-it-works.md](docs/how-it-works.md)。

## 目录结构

```
bin/xiaomi-key-daemon.py         守护进程（单文件，stdlib only）
config/action.conf.example       配置模板
etc/udev/rules.d/                 ACL 规则（uaccess，不需要 input 组）
etc/udev/hwdb.d/                  F19 重映射（备选方案）
etc/systemd/user/                 systemd --user 单元
scripts/install.sh               安装（--prefix/--dry-run/--no-udev/...）
scripts/uninstall.sh             卸载（--purge）
scripts/remap-key.sh             重映射（install/--verify/--remove）
tests/                           100+ 个单元测试，无需硬件
docs/                            原理、排错、机型适配
```

## 常见问题

**按了没反应？** 先 `--check`，再 `libinput debug-events --show-keycodes`
确认事件是否到了内核 —— 详见 [docs/troubleshooting.md](docs/troubleshooting.md)。

**按一次触发两次？** 多半是做过重映射却没丢掉释放 scancode（`0x11901`），
或者同时装了守护进程和重映射。

**长按没反应？** 重映射过就物理上不可能（释放事件被丢弃）；没重映射则检查
`LONG_PRESS` 是否为空、`PRESS` 是否把按键消费掉了。

**升级内核后？** 不用管，守护进程会自己重连设备；`eventN` 变号也不影响。

## 开发

```bash
make test     # python3 -m unittest discover -s tests -t . -v
make lint     # bash -n + shellcheck + byte-compile
make check    # 在本机做一次完整自检
```

测试不需要小米笔记本、不需要 root、不需要桌面会话；设备识别部分用假的 sysfs
树（`tests/test_devices.py`）验证。贡献前请读
[CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可

[MIT](LICENSE)。文档与代码都欢迎 PR；机型适配请用
[硬件报告模板](.github/ISSUE_TEMPLATE/hardware-report.yml)。
