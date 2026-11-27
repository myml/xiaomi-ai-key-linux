# Security

This is a small daemon that reads one input device and runs shell commands you
configure yourself. Two things are worth knowing:

- The udev rule grants the active local session read access to WMI hotkey
  devices (`TAG+="uaccess"`). It does not add anyone to the `input` group, so
  it does not grant keylogging on keyboards or touchpads. Review
  `etc/udev/rules.d/60-xiaomi-key.rules` before installing it.
- Actions run through `sh -c` with your full user privileges. Treat
  `action.conf` as code: do not paste configurations you have not read,
  especially not ones that read from the network.

To report a vulnerability, open a
[private security advisory](https://github.com/myml/xiaomi-ai-key-linux/security/advisories/new)
rather than a public issue.
