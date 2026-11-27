# 原理：从固件到桌面，这个键到底经过了什么

> **English TL;DR.** The firmware reports `KEY_ASSISTANT` (583) through the
> `redmi_wmi` WMI driver. libinput accepts it, but KWin translates the keysym
> with `QXkbCommon::keysymToQtKey()`, and Qt has no mapping for
> `XF86Assistant` — it returns `Qt::Key_unknown` (0), so KDE's shortcut
> recorder shows nothing. The key is fine; Qt's table is incomplete. Two ways
> out: read `/dev/input/eventN` directly (this daemon), or remap the key to F19
> with hwdb so Qt understands it.

本文记录的是查这个问题时一步步量出来的结论，不是猜测。所有命令都可以复现。

---

## 1. 硬件与内核：键本身是好的

| 项目 | 值 |
|---|---|
| ACPI/WMI 设备 | `46C93E13-EE9B-4262-8488-563BCA757FEF` |
| 驱动 | `redmi_wmi`（内核内置，`drivers/platform/x86/redmi-wmi.c`） |
| 输入设备名 | `Redmibook WMI keys` |
| 设备节点 | `/dev/input/eventN`（**N 不稳定**，不同启动可能是 7 或 8） |
| 稳定别名 | `/dev/input/xiaomi-key`（本项目的 udev 规则创建） |
| 按键码 | `KEY_ASSISTANT` = **583**，即 XKB 的 `XF86Assistant` |
| 事件特点 | 按下与释放分别上报（`value=1` / `value=0`），**支持长按** |

查询：

```bash
# 找设备（名字随固件而定）
grep -l . /sys/class/input/event*/device/name | while read -r f; do
    echo "$(basename "$(dirname "$(dirname "$f")")")  $(cat "$f")"
done

# 这个设备能上报哪些键？这是本项目识别设备的核心依据
cat /sys/class/input/event8/device/capabilities/key
```

参考机器（Redmi Book 16 2024，Fedora 44，kernel 7.2.6）上的位图是：

```
2000000000000000 400000000000080 4000000000000 20000 0 10000000000 0 1001800001000 f80080000000000 0 0
```

解出来是 16 个键码：`171, 183-187, 204, 227, 228, 240, 360, 465, 562, 583, 634, 701`。
内核把位图按 **大端 64 位字** 打印，所以解析时要**倒序**取字、再按位展开
（`bin/xiaomi-key-daemon.py` 里的 `decode_keybit()`，有单元测试覆盖）。

**结论：不需要写驱动。** 这个键已经是一个标准"助手键"，问题全在用户空间。

---

## 2. 为什么"系统设置 → 快捷键"录不到它

实测证据（Qt 6.11.2）：

```
evdev 键名           code   xkb码  keysym          Qt::Key      能否绑定
KEY_ASSISTANT        583    591    XF86Assistant   0            ❌
KEY_F13              183    191    XF86Tools       0x010000f1   ✅
KEY_SWITCHVIDEOMODE  227    235    XF86Display     0x010000d1   ✅
```

直接调用 Qt 自己的转换函数就能复现（不需要装任何东西）：

```bash
python3 -c "
import ctypes
g = ctypes.CDLL('/usr/lib64/libQt6Gui.so.6')
f = g._ZN10QXkbCommon13keysymToQtKeyEj6QFlagsIN2Qt16KeyboardModifierEE
f.restype = ctypes.c_int
f.argtypes = [ctypes.c_uint, ctypes.c_int]
print(hex(f(0x10081247, 0)))   # 0x10081247 = XF86Assistant -> 0x0
print(hex(f(0x1008ff1b, 0)))   # 0x1008ff1b = XF86Search    -> 0x1000092
"
```

事件链：

1. 内核 `redmi_wmi` 上报 `KEY_ASSISTANT`（583）—— 内核侧完全正常；
2. libinput 把设备标成键盘（`ID_INPUT_KEY=1`），KWin 打开并监听它；
3. KWin 用 `QXkbCommon::keysymToQtKey()` 把 `XF86Assistant` 翻成 Qt 的键；
4. **Qt 的映射表里没有这一项**，`Qt::Key` 枚举里也没有 `Key_Assistant`，返回 0；
5. KDE 的快捷键系统以 Qt 键为基础，`0` == `Qt::Key_unknown` → 录制框一片空白。

这是 Qt 的缺失，不是配置问题：`src/gui/platform/unix/qxkbcommon.cpp` 的 `KeyTbl`
里有一百多条 `XF86*` 映射，唯独没有 Assistant（Qt `dev` 分支至今没有）。
同样录不到的还有 `KEY_VENDOR`、`KEY_REFRESH_RATE_TOGGLE`、`KEY_SELECTIVE_SCREENSHOT`。

所以只有两条路：**让键变成 Qt 认识的键**（hwdb 重映射），或**绕过 Qt**（直接读设备）。

---

## 3. 两条路线

| | 守护进程（`bin/xiaomi-key-daemon.py`） | hwdb 重映射（`scripts/remap-key.sh`） |
|---|---|---|
| 原理 | 直接读 `/dev/input/eventN`，不经过 KWin/Qt | 把 583 改成 F19，Qt 就认识了 |
| 长按 | ✅ 支持 | ❌ 释放事件被丢弃 |
| 按下 / 短按 / 长按 | ✅ 三个独立槽位 | ❌ 只有"按下" |
| 绑定方式 | 改 `action.conf` | 系统设置 → 快捷键 |
| 需要重登 | 不需要 | 需要（KWin 缓存了 keybit） |
| 与其他快捷键统一管理 | 不统一 | ✅ 统一在 KCM 里 |
| 推荐场景 | 想要长按 / 脚本 / 多动作 | 只想要一个"像快捷键一样"的键 |

**两者互斥**：重映射后设备上报 189，守护进程默认监听 583 就会什么都收不到。
`scripts/install.sh` 和 `--check` 都会检测这个冲突并提示。

---

## 4. 守护进程怎么工作

### 4.1 权限：udev `uaccess`

输入设备节点默认是 `root:input 0600`，普通用户读会 `EACCES`。
`etc/udev/rules.d/60-xiaomi-key.rules` 给匹配设备打 `TAG+="uaccess"`，
systemd-logind 就会给**当前登录的本地会话**加一条 ACL：

```
crw-rw----+ 1 root input 13, 72 /dev/input/event8
    user:wrj97:rw-
```

它只影响 WMI 热键设备，不会给键盘/触摸板开口子（那些走 libinput，不看 ACL）。
不推荐 `usermod -aG input`：那等于给用户完整的键盘记录权限。

### 4.2 设备发现：按能力，不按名字

写死 `event7` 或者写死 `Redmibook WMI keys` 都不可移植。所以先读
`/sys/class/input/event*/device/capabilities/key`，只有位图里包含目标键码
（默认 583）的设备才算候选；`DEVICE_NAME` 只是可选的额外正则过滤。
这样：

- 换机型、换启动顺序、`eventN` 变号都不影响；
- 做了 hwdb 重映射的机器，把 `KEY_CODES` 改成 189 依然能用。

### 4.3 事件读取

`struct input_event` 是 `timeval` + `u16 type` + `u16 code` + `s32 value`，
64 位 Linux 上是 24 字节。`struct.Struct("llHHi")` 的原生对齐正好匹配。

`read()` 可能把一条事件切成两半，所以 `EventReader` 带缓冲区，
凑满一条才解析（有"逐字节喂入"的单元测试）。

### 4.4 判断长按

按下后不轮询，而是把 `select()` 的超时设成"离长按阈值还差多久"：

```python
timeout = deadline - time.monotonic()
ready, _, _ = select.select([fd], [], [], timeout)
if not ready:            # 超时 = 按住够久了
    fire(long_press)
```

好处是空转零开销，且松手时立刻能算出短按。自动重复（`value=2`）被忽略，
所以按住不会连发 `PRESS`。

### 4.5 状态机

三个槽位的语义（完整真值表在 `tests/test_state_machine.py`）：

| 你填了 | 快按一下 | 按住不放 |
|---|---|---|
| `PRESS` | 按下即执行 | 按下即执行 |
| `SHORT_PRESS` | 松手才执行 | 不执行 |
| `PRESS` + `LONG_PRESS` | PRESS | PRESS，然后 LONG_PRESS |
| `SHORT_PRESS` + `LONG_PRESS` | SHORT_PRESS | LONG_PRESS |
| `PRESS` + `SHORT_PRESS` | 只有 PRESS（SHORT 永远不触发，启动时会告警） | — |

`PRESS` 用独立标志记录"按下时已经处理过"，所以它不会吞掉 `LONG_PRESS`，
但会让 `SHORT_PRESS` 失效 —— 这就是"短按 A、长按 B"必须**只填**
`SHORT_PRESS` + `LONG_PRESS` 的原因。

---

## 5. hwdb 重映射的几个坑（都踩过）

### 5.1 两个 scancode，一个是"释放"

`redmi_wmi` 用两个 scancode 表示同一个键：

- `0x11801` = 按下
- `0x11901` = 释放（payload bit 8 置位）

驱动里有个 "AI key quirk"：**仅当键码还是 `KEY_ASSISTANT`** 时才用 bit 8 区分
按下/释放，并关闭内核的 autorelease。一旦重映射成 F19，这个 quirk 不再生效，
两个 scancode 各自产生一次"按下 + 自动释放"，**按一次会触发两次**。

所以规则必须两行，第二行把释放丢掉：

```
evdev:name:Redmi*book WMI keys:*
 KEYBOARD_KEY_11801=f19
 KEYBOARD_KEY_11901=reserved
```

### 5.2 `reserved` 不能写成 `0`

systemd 的键名表由 `linux/input.h` 生成。名字 `"0"` 对应的是 `KEY_0`
（**数字键 0，值 11**），不是 `KEY_RESERVED`（0）。写成 `=0` 会把"释放"
变成敲一个数字 0。官方的 `60-keyboard.hwdb` 里禁用按键一律写 `reserved`。

### 5.3 为什么选 F19

- `F19` → keysym `F19` → Qt 显示 **"F19"**，录制框里一眼能认；
- `F18` 的 keysym 是 `XF86Launch9`，Qt 里显示成 "Launch (9)"；
- `F20/F21/F22` 在 Qt 里分别是 Microphone Mute / Touchpad Toggle / Touchpad On；
- 驱动本身只用到 F13~F17。

### 5.4 glob 不是正则

udev 和 hwdb 的模式是 **glob**：`?` 表示"恰好一个字符"，`*` 才是任意串。
`Redmibook` 里 `Redmi` 与 `book` 之间没有字符，所以 `Redmi?book` **永远匹配不上**，
必须写 `Redmi*book`。（守护进程里 `DEVICE_NAME` 用的是 Python 正则，
`(Redmi ?book|Redmi)` 里的 `?` 表示"可选出"，语义不同 —— 两者都对，但别混。）

### 5.5 必须重新登录

KWin/libinput 在打开设备时缓存了 keybit。189 不在原始位图里，
不重新打开设备的话事件会被直接丢弃，所以改完 hwdb 必须注销重登
（`kwin_wayland --replace &` 有时行，但不保证）。

---

## 6. 参考

- 驱动：`drivers/platform/x86/redmi-wmi.c`（内核源码树）
- 键码：`include/uapi/linux/input-event-codes.h`（`KEY_ASSISTANT = 583`）
- Qt 映射表：`src/gui/platform/unix/qxkbcommon.cpp`（`KeyTbl`）
- hwdb 格式：`systemd-hwdb(8)`、`/usr/lib/udev/hwdb.d/60-keyboard.hwdb`
