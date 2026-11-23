# galaxy — terminal remote for a Galaxy S26 Ultra

A single-file Python 3.9+ CLI (no dependencies) that drives the phone through `adb`.

## Setup
1. Install [Android platform-tools](https://developer.android.com/tools/releases/platform-tools) so `adb` is on your PATH.
   Optional: [scrcpy](https://github.com/Genymobile/scrcpy) for `galaxy mirror`.
2. On the phone: **Settings → About phone → Software information → tap "Build number" 7×**,
   then **Settings → Developer options → USB debugging** (and/or **Wireless debugging**).
3. Plug in via USB, accept the "Allow USB debugging?" prompt, then run `./galaxy.py devices`.
4. Optional: `ln -s "$PWD/galaxy.py" ~/.local/bin/galaxy`

### Wireless
- USB once, then: `galaxy wifi-adb` (switches to Wi-Fi, prints the ip:port), or
- No cable: Developer options → Wireless debugging → *Pair device with pairing code*, then
  `galaxy pair 192.168.1.20:37099 123456` and `galaxy connect 192.168.1.20:<port shown>`.

With several devices, pick one with `-s SERIAL` or `export ANDROID_SERIAL=...`.

## Commands
| Area | Commands |
|---|---|
| Connection | `devices`, `pair`, `connect`, `disconnect`, `wifi-adb` |
| Info | `info`, `battery` (`bat`), `notifications` (`notif`) |
| Screen | `screenshot` (`ss`), `record -t 30`, `mirror` |
| Files | `push FILE... [DEST]` (default `/sdcard/Download/`), `pull SRC [DEST]`, `ls [PATH]` |
| Apps | `apps [filter] [-a]`, `install APK...`, `uninstall PKG`, `launch PKG`, `stop PKG`, `open URL` |
| Input | `key home back vol-up …`, `type TEXT`, `tap X Y`, `swipe X1 Y1 X2 Y2 [ms]`, `unlock [--pin]` |
| Phone | `call NUMBER`, `hangup`, `sms NUMBER TEXT [--send]` |
| Settings | `wifi [on\|off]`, `bluetooth [on\|off]`, `data [on\|off]`, `brightness [0-255]`, `volume [N] --stream media`, `clipboard [TEXT]` |
| System | `shell [CMD]`, `logcat [--tag T] [-d] [-c]`, `reboot [recovery\|bootloader\|download]` |

`galaxy <command> --help` shows details; `-v` prints each adb call.

Notes: some toggles (`data`, `clipboard set`, `sms --send`) depend on One UI permissions and may
be blocked without root. `unlock --pin` sends your PIN over adb — avoid on untrusted machines.
