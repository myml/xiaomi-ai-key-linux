# 适配其他机型

> **English TL;DR.** Run `--list` and `--test` to find out what your firmware
> actually reports, then set `KEY_CODES` and (optionally) `DEVICE_NAME`. If the
> device name does not match `*WMI keys`, adjust the udev rule. Report your
> model with the hardware issue template.

本项目默认假设：设备上报 `KEY_ASSISTANT`（583），设备名里含 `WMI keys`。
前者决定能不能用，后者只影响 udev 规则和自动发现。

## 兼容性

| 机型 | 输入设备名 | 键码 | 状态 |
|---|---|---|---|
| Redmi Book 16 2024 | `Redmibook WMI keys` | 583 `KEY_ASSISTANT` | ✅ 已验证（Fedora 44 / Plasma 6.7.5 / Wayland / kernel 7.2.6） |
| 其他小米/红米笔记本，WMI 块名含 `WMI keys` | 待填 | 待填 | ❓ 期待你的报告 |

> 表里的"已验证"只代表这 1 台机器实测。别人的同型号也可能因为固件版本、
> BIOS 设置不同而表现不同 —— 所以请用模板提交报告。

## 适配四步

### 1. 找出设备与键码

```bash
./bin/xiaomi-key-daemon.py --list      # 找设备，看 capabilities 位图
./bin/xiaomi-key-daemon.py --test      # 边按边看，包括未绑定的键码
```

`--test` 会把该设备的**所有**按键事件打印出来，未绑定的会标注
`not in KEY_CODES`。按下小爱键，看它实际报的是什么。

- 什么都不报 → 事件没到内核，与本项目无关（BIOS / 固件 / 驱动）。
- 报的是 583 → 默认配置就能用。
- 报的是别的码（例如某些固件报 `KEY_VENDOR` = 360、`KEY_HOMEPAGE` = 172）
  → 把那个数字写进 `KEY_CODES`。

### 2. 改配置

```ini
# ~/.config/xiaomi-key/action.conf
KEY_CODES=583
# 只有在同机有多个设备都报这个键码时才需要下面这行（Python 正则）
# DEVICE_NAME=MyLaptop WMI keys
```

改完 `systemctl --user restart xiaomi-key`（或 `reload`）。

### 3. 设备名不匹配时改 udev 规则

规则核心是一行 glob：

```
ATTRS{name}=="*WMI keys", TAG+="uaccess", ...
```

如果你的设备名不含 `WMI keys`，先确认 `--list` 里能读到它（能读就说明
sysfs 可访问），再把规则里的 glob 改成你的名字，例如：

```
ATTRS{name}=="Redmi Book Pro 16 WMI hotkeys",
```

改完：

```bash
sudo install -m644 etc/udev/rules.d/60-xiaomi-key.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=input --action=change
# 重新登录，然后
getfacl -p /dev/input/xiaomi-key
```

**不要**为了省事把 `TAG+="uaccess"` 加到 `SUBSYSTEM=="input"` 的整体规则上 ——
那会连键盘一起给 ACL。

### 4. 用重映射方案时注意

`scripts/remap-key.sh` 会自动探测设备名，把 hwdb 的 `evdev:name:` 行替换成
实际名字。如果你的机器上报的不是 583，重映射的 scancode 也可能不同，
需要自己改 `etc/udev/hwdb.d/70-xiaomi-key-remap.hwdb` 里的
`KEYBOARD_KEY_<scancode>`。拿到 scancode 的方法：

```bash
sudo evtest            # 选 WMI 设备，按键，看 "MSC_SCAN" 的值
sudo libinput debug-events --show-keycodes
```

## 报告模板要带什么

- 机型、发行版、内核、桌面版本
- `--check`、`--list`、`--test` 的完整输出
- `cat /sys/class/input/eventN/device/name` 和
  `cat /sys/class/input/eventN/device/capabilities/key`
- 如果事件根本没到内核，说明这一点（这同样是有价值的信息）

用 `.github/ISSUE_TEMPLATE/hardware-report.yml` 会提示你填这些。

## 已知的相邻问题

- **ThinkPad 的"星键"、Dell 的 AI 键**：大多是 `KEY_ASSISTANT` 或
  `KEY_VENDOR`，本项目大概率能用，但驱动名/设备名不同，需要按上面四步调整。
- **固件把它做成组合键**（例如 `Ctrl+Alt+X`）：那就完全不需要本项目，
  直接在桌面设置里绑组合键。
- **BIOS 更新后键彻底消失**：`--test` 无输出，检查 BIOS 里的相关选项；
  某些更新确实会改 WMI GUID，那需要另写驱动，超出本项目范围。
