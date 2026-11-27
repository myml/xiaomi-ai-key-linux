# 排错

> **English TL;DR.** Start with `bin/xiaomi-key-daemon.py --check`; it reports
> permission problems, a wrong key code, a stopped service and the daemon/hwdb
> remap conflict. Then `--test` to see whether the kernel delivers the event at
> all, and `journalctl --user -u xiaomi-key -b` for the daemon's view.

---

## 0. 先跑自检

```bash
cd xiaomi-ai-key-linux
./bin/xiaomi-key-daemon.py --check
```

它会一条条列出：Python 版本、配置文件与告警、找到的设备、权限、keybit、
udev 规则、systemd 单元、通知程序、每个动作的命令是否存在、以及
**"装着重映射却又监听 583"** 这类冲突。退出码非 0 表示有硬失败。

再看守护进程自己的日志：

```bash
journalctl --user -u xiaomi-key -b --no-pager | tail -50
```

正常启动应该能看到类似：

```
xiaomi-key: config: /home/you/.config/xiaomi-key/action.conf
xiaomi-key: key codes: 583 (KEY_ASSISTANT)
xiaomi-key: short: gdbus call ...
xiaomi-key: listening on /dev/input/event8 (Redmibook WMI keys)
```

---

## 1. 按下去什么反应都没有

按顺序排除：

**(a) 事件到底有没有到内核？**

```bash
sudo libinput debug-events --show-keycodes
```

按下小爱键，如果这里都**没有任何输出**，说明事件没到 evdev：可能是 BIOS
关掉了这个键、WMI GUID 变了、或者固件把它映射成了别的东西。
本项目无能为力，先查 BIOS / 固件更新。

如果有输出但显示的不是 `KEY_ASSISTANT`，记下实际键码，写进配置：

```ini
KEY_CODES=227        # 举例：实际看到的 code
```

**(b) 守护进程看到的是不是同一台设备？**

```bash
./bin/xiaomi-key-daemon.py --list
```

看哪个设备带 `->` 标记、`reports:` 是不是你期望的键码。如果目标设备没被标记，
把它名字写进 `DEVICE_NAME`（Python 正则），或者直接改 `KEY_CODES`。

**(c) 权限够不够？**

```bash
getfacl -p /dev/input/xiaomi-key 2>/dev/null | grep '^user:'
ls -l /dev/input/event8
```

没有 ACL 的 `user:` 行 → udev 规则没装或没生效。装好规则后**重新登录**
（`uaccess` 的 ACL 在会话切换时才刷新），或者临时用
`sudo chmod a+r /dev/input/event8` 验证一下再撤回。

**(d) 服务在跑吗？**

```bash
systemctl --user status xiaomi-key
systemctl --user restart xiaomi-key
```

**(e) 配置里的动作命令存在吗？**

动作是在登录会话的环境里跑的，PATH 可能和你的交互 shell 不同。
`--check` 会用 `shutil.which()` 检查每个动作的第一个词。找不到就写绝对路径。

---

## 2. 一次按键触发两次

三个原因，按概率排序：

1. **做过 hwdb 重映射但没丢掉释放 scancode**。检查
   `/etc/udev/hwdb.d/70-xiaomi-key-remap.hwdb` 是否有
   `KEYBOARD_KEY_11901=reserved`，且写的是 `reserved` 不是 `0`。
   用 `scripts/remap-key.sh` 重新装一次最省事。
2. **`PRESS` 和 `SHORT_PRESS` 都填了**：快按时 `PRESS` 立即触发，
   松手时不应该再有 `SHORT_PRESS` —— 所以这不是它的症状；但如果你把同一个
   命令同时填进 `PRESS` 和 `LONG_PRESS`，按住时会执行两次（这是设计如此）。
3. **两个设备都匹配**：例如同时装了重映射和守护进程。`--list` 看有几个 `->`。

---

## 3. 长按没反应

- 配置里 `LONG_PRESS` 是空的 → 没有长按。
- 只填了 `PRESS` → 长按阈值根本没被使用（`deadline()` 返回 None）。
  要"按下 A、长按 B"，必须 `PRESS` + `LONG_PRESS` 同时填。
- 做过 hwdb 重映射 → 释放事件被丢弃，**长按物理上不可能**。先
  `scripts/remap-key.sh --remove` 再重登。
- `LONG_PRESS_MS` 太大（比如 3000）→ 你以为没触发，其实还没到。

验证长按判定阈值：

```bash
./bin/xiaomi-key-daemon.py --test    # 按一下，看 press/release 是否成对出现
```

`--test` 里只看到 `press` 没有 `release`，说明设备（或重映射）丢了释放事件，
长按一定不工作。

---

## 4. 短按不触发

`PRESS` 一旦配置，按下时就已经把这次按键"消费"了，`SHORT_PRESS` 永远不会
触发。配置加载时会直接告警（`PRESS and SHORT_PRESS are both set...`）。
要区分短按/长按，只填 `SHORT_PRESS` + `LONG_PRESS`。

---

## 5. 服务启动失败 / 反复重启

```bash
systemctl --user status xiaomi-key
journalctl --user -u xiaomi-key -b --no-pager
```

常见原因：

- `ExecStart` 路径不对（用了 `--prefix` 但单位文件没跟着改）：
  `scripts/install.sh --prefix ...` 会重写 `ExecStart`，手动拷贝时容易忘。
- 设备还没出现：日志会是 `no input device reporting 583 found; retrying in Ns`，
  这是正常的退避重试（1s → 2s → ... → 30s），设备出现后自动连上。
- `StartLimitBurst` 触发后服务进入 `failed`：

  ```bash
  systemctl --user reset-failed xiaomi-key
  systemctl --user restart xiaomi-key
  ```

- Python 太老（< 3.9）：`--check` 第一行就会报 `[FAIL]`。

---

## 6. 内核升级之后

`redmi_wmi` 是内核内置模块，升级重启后设备会重新枚举：`eventN` 可能变号，
udev 规则会重新打 ACL。守护进程会自己重连，不用管。
如果日志一直 `no input device ... found`，先 `--list` 看设备名是不是变了。

---

## 7. 动作执行了，但窗口/菜单没出现

守护进程通过 systemd `--user` 启动，环境变量（`WAYLAND_DISPLAY`、
`DISPLAY`、`DBUS_SESSION_BUS_ADDRESS`）来自会话。如果某个程序必须读到
特定的变量：

```bash
systemctl --user show-environment | grep -E 'WAYLAND|DISPLAY|DBUS'
```

缺了就补：

```bash
systemctl --user import-environment WAYLAND_DISPLAY DISPLAY DBUS_SESSION_BUS_ADDRESS
```

另外，动作是 `sh -c` 跑的，**不要**在配置里写 `qdbus`（Fedora 上常常没装），
用 `gdbus`。

---

## 8. 通知不弹

`FEEDBACK` 非空时才会调用 `notify-send`；确认它在：

```bash
command -v notify-send
```

没有就装 `libnotify`（Fedora），或把 `FEEDBACK` 留空。

---

## 9. 其他桌面环境

守护进程本身与桌面无关，任何支持 `systemd --user` 的发行版都能用。
区别只在"偶发的会话环境"和"怎么绑定"：

- **GNOME**：`--check` 正常的话直接用；若要绑到桌面快捷键，用 hwdb 重映射 +
  GNOME 设置 → 键盘 → 自定义快捷键（GNOME 也是 GTK，但同样看不到
  `XF86Assistant`，所以重映射同样适用）。
- **Sway / Hyprland**：守护进程可用；也可以直接用它们的 `bind` 绑定键码
  （`bindsym --to-code` / `bind = MOD, code:583`），不一定需要本项目。
- **X11**：`xmodmap`/`xbindkeys` 可行，但本项目走 evdev，同样适用。

---

## 10. 彻底回滚

```bash
./scripts/uninstall.sh --purge     # 删服务、程序、udev 规则、配置
# 如果装过重映射：
./scripts/uninstall.sh             # 不带 --purge 会保留 action.conf
# 然后注销重登，键恢复成 KEY_ASSISTANT
```

回滚后 `--list` 里那个设备的 `codes:` 应该重新出现 583、消失 189。
