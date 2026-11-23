#!/usr/bin/env python3
"""galaxy - a command-line remote for a Samsung Galaxy (S26 Ultra) phone over ADB.

Requires Android platform-tools (`adb`) on PATH and USB debugging (or Wireless
debugging) enabled on the phone. Optional: `scrcpy` for screen mirroring.

Run `galaxy.py --help` or `galaxy.py <command> --help` for usage.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import shlex
import shutil
import subprocess
import sys

ADB = os.environ.get("GALAXY_ADB", "adb")

KEYS = {
    "home": "KEYCODE_HOME", "back": "KEYCODE_BACK", "recents": "KEYCODE_APP_SWITCH",
    "power": "KEYCODE_POWER", "vol-up": "KEYCODE_VOLUME_UP",
    "vol-down": "KEYCODE_VOLUME_DOWN", "mute": "KEYCODE_VOLUME_MUTE",
    "play": "KEYCODE_MEDIA_PLAY_PAUSE", "next": "KEYCODE_MEDIA_NEXT",
    "prev": "KEYCODE_MEDIA_PREVIOUS", "enter": "KEYCODE_ENTER",
    "wake": "KEYCODE_WAKEUP", "sleep": "KEYCODE_SLEEP", "camera": "KEYCODE_CAMERA",
    "notifications": "KEYCODE_NOTIFICATION", "search": "KEYCODE_SEARCH",
}


class CliError(Exception):
    pass


# --------------------------------------------------------------------------- adb

def _base(args) -> list[str]:
    cmd = [ADB]
    serial = getattr(args, "serial", None) or os.environ.get("ANDROID_SERIAL")
    if serial:
        cmd += ["-s", serial]
    return cmd


def adb(args, *parts: str, capture: bool = True, check: bool = True) -> str:
    if shutil.which(ADB) is None and not os.path.exists(ADB):
        raise CliError(
            f"'{ADB}' not found. Install Android platform-tools: "
            "https://developer.android.com/tools/releases/platform-tools")
    cmd = _base(args) + list(parts)
    if getattr(args, "verbose", False):
        print("+ " + shlex.join(cmd), file=sys.stderr)
    if not capture:
        rc = subprocess.call(cmd)
        if check and rc != 0:
            raise CliError(f"adb exited with {rc}")
        return ""
    res = subprocess.run(cmd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise CliError((res.stderr or res.stdout).strip() or f"adb exited with {res.returncode}")
    return res.stdout


def sh(args, command: str, **kw) -> str:
    return adb(args, "shell", command, **kw)


def prop(args, name: str) -> str:
    return sh(args, f"getprop {name}").strip()


# ---------------------------------------------------------------------- commands

def cmd_devices(args):
    print(adb(args, "devices", "-l").rstrip())


def cmd_pair(args):
    print(adb(args, "pair", args.address, args.code).strip())


def cmd_connect(args):
    addr = args.address if ":" in args.address else f"{args.address}:5555"
    print(adb(args, "connect", addr).strip())


def cmd_disconnect(args):
    print(adb(args, "disconnect", *( [args.address] if args.address else [])).strip())


def cmd_wifi(args):
    """Switch a USB-connected phone to TCP/IP mode and connect over Wi-Fi."""
    out = sh(args, "ip -f inet addr show wlan0")
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
    if not m:
        raise CliError("Could not find phone's Wi-Fi IP (is Wi-Fi on?)")
    ip = m.group(1)
    adb(args, "tcpip", str(args.port))
    print(adb(args, "connect", f"{ip}:{args.port}").strip())
    print(f"You can now unplug USB. Use: galaxy -s {ip}:{args.port} <command>")


def cmd_info(args):
    fields = [
        ("Model", "ro.product.model"), ("Device", "ro.product.device"),
        ("Brand", "ro.product.brand"), ("Android", "ro.build.version.release"),
        ("SDK", "ro.build.version.sdk"), ("One UI", "ro.build.version.oneui"),
        ("Build", "ro.build.display.id"), ("Security patch", "ro.build.version.security_patch"),
        ("Serial", "ro.serialno"),
    ]
    for label, key in fields:
        val = prop(args, key)
        if key == "ro.build.version.oneui" and val.isdigit():
            n = int(val)  # e.g. 80000 -> 8.0
            val = f"{n // 10000}.{(n // 100) % 100}"
        print(f"{label:<15} {val or '-'}")
    size = sh(args, "wm size", check=False).strip().split(":")[-1].strip()
    print(f"{'Screen':<15} {size or '-'}")
    df = sh(args, "df -h /data", check=False).strip().splitlines()
    if len(df) > 1:
        cols = df[-1].split()
        if len(cols) >= 4:
            print(f"{'Storage':<15} {cols[2]} used / {cols[1]} ({cols[3]} free)")


def cmd_battery(args):
    out = sh(args, "dumpsys battery")
    d = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            d[k.strip()] = v.strip()
    status = {"1": "unknown", "2": "charging", "3": "discharging",
              "4": "not charging", "5": "full"}.get(d.get("status", ""), d.get("status", "?"))
    plugged = [s for s in ("AC", "USB", "Wireless") if d.get(f"{s} powered") == "true"]
    temp = d.get("temperature")
    print(f"Level        {d.get('level', '?')}%")
    print(f"Status       {status}")
    print(f"Plugged      {', '.join(plugged) or 'no'}")
    if temp and temp.lstrip('-').isdigit():
        print(f"Temperature  {int(temp) / 10:.1f} °C")
    if d.get("voltage"):
        print(f"Voltage      {d['voltage']} mV")
    if d.get("health"):
        health = {"2": "good", "3": "overheat", "4": "dead", "5": "over voltage",
                  "7": "cold"}.get(d["health"], d["health"])
        print(f"Health       {health}")


def _stamp(prefix: str, ext: str) -> str:
    return f"{prefix}_{_dt.datetime.now():%Y%m%d_%H%M%S}.{ext}"


def cmd_screenshot(args):
    out = args.output or _stamp("screenshot", "png")
    cmd = _base(args) + ["exec-out", "screencap", "-p"]
    with open(out, "wb") as f:
        res = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE)
    if res.returncode != 0:
        raise CliError(res.stderr.decode(errors="replace").strip())
    print(f"Saved {out}")


def cmd_record(args):
    remote = "/sdcard/galaxy_cli_record.mp4"
    out = args.output or _stamp("screenrecord", "mp4")
    print(f"Recording for up to {args.seconds}s (Ctrl+C to stop early)...")
    try:
        sh(args, f"screenrecord --time-limit {args.seconds} {remote}", capture=False, check=False)
    except KeyboardInterrupt:
        sh(args, "pkill -INT screenrecord", check=False)
    import time; time.sleep(1)
    adb(args, "pull", remote, out)
    sh(args, f"rm -f {remote}", check=False)
    print(f"Saved {out}")


def cmd_push(args):
    print(adb(args, "push", *args.local, args.remote).strip())


def cmd_pull(args):
    print(adb(args, "pull", args.remote, *( [args.local] if args.local else [])).strip())


def cmd_ls(args):
    print(sh(args, f"ls -la {shlex.quote(args.path)}").rstrip())


def cmd_apps(args):
    flag = "-3" if not args.all else ""
    out = sh(args, f"pm list packages {flag}".strip())
    pkgs = sorted(l.removeprefix("package:").strip() for l in out.splitlines() if l.strip())
    if args.filter:
        pkgs = [p for p in pkgs if args.filter.lower() in p.lower()]
    print("\n".join(pkgs))


def cmd_install(args):
    for apk in args.apk:
        print(f"Installing {apk}...")
        print(adb(args, "install", "-r", apk).strip())


def cmd_uninstall(args):
    print(adb(args, "uninstall", args.package).strip())


def cmd_launch(args):
    print(sh(args, f"monkey -p {shlex.quote(args.package)} -c android.intent.category.LAUNCHER 1").strip().splitlines()[-1])


def cmd_stop(args):
    sh(args, f"am force-stop {shlex.quote(args.package)}")
    print(f"Stopped {args.package}")


def cmd_open(args):
    sh(args, f"am start -a android.intent.action.VIEW -d {shlex.quote(args.url)}")
    print(f"Opened {args.url}")


def cmd_key(args):
    for k in args.keys:
        code = KEYS.get(k.lower(), k if k.upper().startswith("KEYCODE_") or k.isdigit() else None)
        if code is None:
            raise CliError(f"Unknown key '{k}'. Known: {', '.join(KEYS)} (or any KEYCODE_*)")
        sh(args, f"input keyevent {code}")


def cmd_type(args):
    # `input text` needs spaces encoded as %s and shell metacharacters escaped
    text = " ".join(args.text).replace(" ", "%s")
    sh(args, f"input text {shlex.quote(text)}")


def cmd_tap(args):
    sh(args, f"input tap {args.x} {args.y}")


def cmd_swipe(args):
    sh(args, f"input swipe {args.x1} {args.y1} {args.x2} {args.y2} {args.ms}")


def cmd_unlock(args):
    sh(args, "input keyevent KEYCODE_WAKEUP")
    sh(args, "wm dismiss-keyguard", check=False)
    if args.pin:
        sh(args, f"input text {shlex.quote(args.pin)}")
        sh(args, "input keyevent KEYCODE_ENTER")


def cmd_call(args):
    sh(args, f"am start -a android.intent.action.CALL -d tel:{shlex.quote(args.number)}")
    print(f"Calling {args.number}...")


def cmd_hangup(args):
    sh(args, "input keyevent KEYCODE_ENDCALL")


def cmd_sms(args):
    """Opens the Messages composer pre-filled; press send on phone (or use --send)."""
    body = " ".join(args.message)
    sh(args, "am start -a android.intent.action.SENDTO -d "
             f"{shlex.quote('sms:' + args.number)} --es sms_body {shlex.quote(body)}")
    if args.send:
        import time; time.sleep(1.5)
        sh(args, "input keyevent KEYCODE_DPAD_RIGHT", check=False)
        sh(args, "input keyevent KEYCODE_ENTER")
    print("Message composed" + (" and send pressed" if args.send else " - tap send on the phone"))


def cmd_notifications(args):
    out = sh(args, "dumpsys notification --noredact")
    items, cur = [], None
    for line in out.splitlines():
        line = line.strip()
        m = re.match(r"NotificationRecord\(.*?pkg=(\S+)", line)
        if m:
            cur = {"pkg": m.group(1)}
            items.append(cur)
        elif cur is not None:
            for key in ("android.title", "android.text"):
                if line.startswith(key + "="):
                    val = line.split("=", 1)[1]
                    val = re.sub(r"^\w+ \((.*)\)$", r"\1", val)  # String (xyz) -> xyz
                    cur.setdefault(key.split(".")[1], val)
    seen = set()
    for n in items:
        sig = (n["pkg"], n.get("title"), n.get("text"))
        if sig in seen or not (n.get("title") or n.get("text")):
            continue
        seen.add(sig)
        print(f"[{n['pkg']}] {n.get('title', '')}: {n.get('text', '')}")
    if not seen:
        print("No notifications.")


def _toggle(args, name, on_cmd, off_cmd):
    if args.state is None:
        return False
    sh(args, on_cmd if args.state == "on" else off_cmd)
    print(f"{name} {args.state}")
    return True


def cmd_wifi_toggle(args):
    if not _toggle(args, "Wi-Fi", "svc wifi enable", "svc wifi disable"):
        print(sh(args, "settings get global wifi_on").strip() == "1" and "on" or "off")


def cmd_bluetooth(args):
    if not _toggle(args, "Bluetooth", "svc bluetooth enable", "svc bluetooth disable"):
        print(sh(args, "settings get global bluetooth_on").strip() == "1" and "on" or "off")


def cmd_data(args):
    if not _toggle(args, "Mobile data", "svc data enable", "svc data disable"):
        print(sh(args, "settings get global mobile_data").strip() == "1" and "on" or "off")


def cmd_brightness(args):
    if args.level is None:
        print(sh(args, "settings get system screen_brightness").strip())
        return
    sh(args, "settings put system screen_brightness_mode 0")
    sh(args, f"settings put system screen_brightness {max(0, min(255, args.level))}")
    print(f"Brightness set to {args.level}")


def cmd_volume(args):
    streams = {"media": 3, "ring": 2, "alarm": 4, "notification": 5, "call": 0}
    sid = streams[args.stream]
    if args.level is None:
        print(sh(args, f"cmd media_session volume --stream {sid} --get").strip())
    else:
        sh(args, f"cmd media_session volume --stream {sid} --set {args.level}")
        print(f"{args.stream} volume set to {args.level}")


def cmd_clipboard(args):
    if args.text:
        # Android 10+ blocks background clipboard writes; use input as fallback hint
        sh(args, f"cmd clipboard set-text {shlex.quote(' '.join(args.text))}", check=False)
        print("Clipboard set (if supported by your One UI build)")
    else:
        print(sh(args, "cmd clipboard get-text", check=False).strip() or "(unavailable)")


def cmd_mirror(args):
    if not shutil.which("scrcpy"):
        raise CliError("scrcpy not installed. Get it from https://github.com/Genymobile/scrcpy")
    cmd = ["scrcpy"]
    serial = args.serial or os.environ.get("ANDROID_SERIAL")
    if serial:
        cmd += ["-s", serial]
    cmd += args.scrcpy_args
    os.execvp("scrcpy", cmd)


def cmd_shell(args):
    if args.command:
        adb(args, "shell", *args.command, capture=False, check=False)
    else:
        adb(args, "shell", capture=False, check=False)


def cmd_reboot(args):
    target = [] if args.mode == "system" else [args.mode]
    adb(args, "reboot", *target)
    print("Rebooting" + (f" into {args.mode}" if target else ""))


def cmd_logcat(args):
    extra = ["-d"] if args.dump else []
    if args.clear:
        adb(args, "logcat", "-c")
        print("Log cleared"); return
    filt = [f"{args.tag}:V", "*:S"] if args.tag else []
    adb(args, "logcat", *extra, *filt, capture=False, check=False)


# ---------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="galaxy",
                                description="Control your Galaxy phone from the terminal (via adb).")
    p.add_argument("-s", "--serial", help="device serial or ip:port (default: $ANDROID_SERIAL)")
    p.add_argument("-v", "--verbose", action="store_true", help="print adb commands")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")

    def add(name, func, help_, aliases=()):
        sp = sub.add_parser(name, help=help_, aliases=list(aliases), description=help_)
        sp.set_defaults(func=func)
        return sp

    # connection
    add("devices", cmd_devices, "list connected devices")
    sp = add("pair", cmd_pair, "pair with Wireless debugging (Settings > Developer options)")
    sp.add_argument("address", help="ip:port shown under 'Pair device with pairing code'")
    sp.add_argument("code", help="6-digit pairing code")
    sp = add("connect", cmd_connect, "connect over Wi-Fi")
    sp.add_argument("address", help="ip[:port]")
    sp = add("disconnect", cmd_disconnect, "disconnect Wi-Fi device(s)")
    sp.add_argument("address", nargs="?")
    sp = add("wifi-adb", cmd_wifi, "switch a USB-connected phone to Wi-Fi adb")
    sp.add_argument("--port", type=int, default=5555)

    # info
    add("info", cmd_info, "show model, Android/One UI version, storage")
    add("battery", cmd_battery, "show battery status", aliases=["bat"])
    add("notifications", cmd_notifications, "list current notifications", aliases=["notif"])

    # screen
    sp = add("screenshot", cmd_screenshot, "save a screenshot to this computer", aliases=["ss"])
    sp.add_argument("-o", "--output")
    sp = add("record", cmd_record, "record the screen to an mp4")
    sp.add_argument("-t", "--seconds", type=int, default=30, help="max 180")
    sp.add_argument("-o", "--output")
    sp = add("mirror", cmd_mirror, "mirror & control screen with scrcpy")
    sp.add_argument("scrcpy_args", nargs=argparse.REMAINDER)

    # files
    sp = add("push", cmd_push, "copy files to the phone")
    sp.add_argument("local", nargs="+")
    sp.add_argument("remote", nargs="?", default="/sdcard/Download/")
    sp = add("pull", cmd_pull, "copy a file/folder from the phone")
    sp.add_argument("remote"); sp.add_argument("local", nargs="?")
    sp = add("ls", cmd_ls, "list a folder on the phone")
    sp.add_argument("path", nargs="?", default="/sdcard/")

    # apps
    sp = add("apps", cmd_apps, "list installed apps (user apps by default)")
    sp.add_argument("filter", nargs="?"); sp.add_argument("-a", "--all", action="store_true")
    sp = add("install", cmd_install, "install APK(s)")
    sp.add_argument("apk", nargs="+")
    sp = add("uninstall", cmd_uninstall, "uninstall a package"); sp.add_argument("package")
    sp = add("launch", cmd_launch, "launch an app by package name"); sp.add_argument("package")
    sp = add("stop", cmd_stop, "force-stop an app"); sp.add_argument("package")
    sp = add("open", cmd_open, "open a URL on the phone"); sp.add_argument("url")

    # input
    sp = add("key", cmd_key, f"press keys: {', '.join(KEYS)}")
    sp.add_argument("keys", nargs="+")
    sp = add("type", cmd_type, "type text into the focused field"); sp.add_argument("text", nargs="+")
    sp = add("tap", cmd_tap, "tap at x,y"); sp.add_argument("x", type=int); sp.add_argument("y", type=int)
    sp = add("swipe", cmd_swipe, "swipe from x1,y1 to x2,y2")
    for a in ("x1", "y1", "x2", "y2"):
        sp.add_argument(a, type=int)
    sp.add_argument("ms", type=int, nargs="?", default=300)
    sp = add("unlock", cmd_unlock, "wake and unlock (optionally enter PIN)")
    sp.add_argument("--pin")

    # phone
    sp = add("call", cmd_call, "start a phone call"); sp.add_argument("number")
    add("hangup", cmd_hangup, "end the current call")
    sp = add("sms", cmd_sms, "compose an SMS"); sp.add_argument("number"); sp.add_argument("message", nargs="+")
    sp.add_argument("--send", action="store_true", help="try to press send automatically")

    # settings
    for name, fn in (("wifi", cmd_wifi_toggle), ("bluetooth", cmd_bluetooth), ("data", cmd_data)):
        sp = add(name, fn, f"get or set {name} (on/off)")
        sp.add_argument("state", nargs="?", choices=["on", "off"])
    sp = add("brightness", cmd_brightness, "get or set brightness 0-255")
    sp.add_argument("level", type=int, nargs="?")
    sp = add("volume", cmd_volume, "get or set volume")
    sp.add_argument("level", type=int, nargs="?")
    sp.add_argument("--stream", choices=["media", "ring", "alarm", "notification", "call"], default="media")
    sp = add("clipboard", cmd_clipboard, "get or set clipboard text"); sp.add_argument("text", nargs="*")

    # system
    sp = add("shell", cmd_shell, "open an adb shell or run a command")
    sp.add_argument("command", nargs=argparse.REMAINDER)
    sp = add("logcat", cmd_logcat, "stream device logs")
    sp.add_argument("--tag"); sp.add_argument("-d", "--dump", action="store_true")
    sp.add_argument("-c", "--clear", action="store_true")
    sp = add("reboot", cmd_reboot, "reboot the phone")
    sp.add_argument("mode", nargs="?", default="system", choices=["system", "recovery", "bootloader", "download"])
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    try:
        args.func(args)
    except CliError as e:
        print(f"galaxy: error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
