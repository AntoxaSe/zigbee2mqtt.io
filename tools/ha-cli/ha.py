#!/usr/bin/env python3
"""ha - a small command-line client for the Home Assistant REST API.

No third-party dependencies; requires Python 3.8+.

Configuration (first match wins):
  --url / --token flags
  HA_URL / HA_TOKEN environment variables
  ~/.config/ha-cli/config.json  ({"url": "...", "token": "..."}), written by `ha login`
  default URL: http://192.168.1.21:8123
"""

import argparse
import fnmatch
import getpass
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

DEFAULT_URL = "http://192.168.1.21:8123"
CONFIG_PATH = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "ha-cli", "config.json"
)


class HAError(Exception):
    pass


# --------------------------------------------------------------------------- config

def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# --------------------------------------------------------------------------- client

class Client:
    def __init__(self, url, token, insecure=False, timeout=15):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.ctx = ssl._create_unverified_context() if insecure else None

    def request(self, method, path, body=None, params=None, raw=False):
        if not self.token:
            raise HAError("No token configured. Run `ha login` or set HA_TOKEN.")
        url = self.url + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + self.token)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as resp:
                text = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace").strip()
            hint = {401: " (token invalid or expired)", 404: " (not found)"}.get(e.code, "")
            raise HAError(f"HTTP {e.code}{hint}: {detail or e.reason}")
        except urllib.error.URLError as e:
            raise HAError(f"Cannot reach {self.url}: {e.reason}")
        except TimeoutError:
            raise HAError(f"Timed out talking to {self.url}")
        if raw:
            return text
        try:
            return json.loads(text) if text else None
        except ValueError:
            return text

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body=body if body is not None else {}, **kw)


# --------------------------------------------------------------------------- output helpers

def out_json(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def table(rows, headers):
    if not rows:
        print("(none)")
        return
    rows = [[str(c) for c in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    widths[-1] = 0  # don't pad last column
    fmt = "  ".join("{:<%d}" % w for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * max(len(h), 3) for h in headers)))
    for r in rows:
        print(fmt.format(*r))


def friendly_state(s):
    unit = s.get("attributes", {}).get("unit_of_measurement")
    return f"{s['state']} {unit}" if unit else s["state"]


def parse_kv(pairs):
    """Turn ['brightness=120', 'color_name=red', 'rgb=[255,0,0]'] into a dict (values JSON-parsed if possible)."""
    data = {}
    for p in pairs or []:
        if "=" not in p:
            raise HAError(f"Expected key=value, got: {p}")
        k, v = p.split("=", 1)
        try:
            data[k] = json.loads(v)
        except ValueError:
            data[k] = v
    return data


def match(entity_id, pattern):
    if not pattern:
        return True
    if any(c in pattern for c in "*?["):
        return fnmatch.fnmatch(entity_id, pattern)
    return pattern.lower() in entity_id.lower()


def ensure_entity(client, entity_id):
    """Allow 'kitchen' as shorthand when it uniquely matches one entity."""
    if "." in entity_id:
        return entity_id
    hits = [s["entity_id"] for s in client.get("/api/states") if entity_id.lower() in s["entity_id"].lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise HAError(f"No entity matches '{entity_id}'")
    raise HAError(f"'{entity_id}' is ambiguous: " + ", ".join(hits[:10]) + (" ..." if len(hits) > 10 else ""))


# --------------------------------------------------------------------------- commands

def cmd_login(args, _client):
    url = args.url or input(f"Home Assistant URL [{DEFAULT_URL}]: ").strip() or DEFAULT_URL
    print("Create a token in HA: Profile -> Security -> Long-lived access tokens")
    token = args.token or getpass.getpass("Long-lived access token: ").strip()
    c = Client(url, token, insecure=args.insecure)
    msg = c.get("/api/")
    save_config({"url": url, "token": token, "insecure": bool(args.insecure)})
    print(f"OK: {msg.get('message', msg) if isinstance(msg, dict) else msg}. Saved to {CONFIG_PATH}")


def cmd_status(args, c):
    cfg = c.get("/api/config")
    if args.json:
        return out_json(cfg)
    states = c.get("/api/states")
    print(f"Server:     {c.url}")
    print(f"Name:       {cfg.get('location_name')}")
    print(f"Version:    {cfg.get('version')}")
    print(f"State:      {cfg.get('state', 'RUNNING')}")
    print(f"Time zone:  {cfg.get('time_zone')}")
    print(f"Entities:   {len(states)}")
    print(f"Components: {len(cfg.get('components', []))}")


def cmd_states(args, c):
    states = c.get("/api/states")
    states = [s for s in states if match(s["entity_id"], args.filter)]
    if args.domain:
        states = [s for s in states if s["entity_id"].split(".")[0] == args.domain]
    if args.state:
        states = [s for s in states if s["state"] == args.state]
    states.sort(key=lambda s: s["entity_id"])
    if args.json:
        return out_json(states)
    table(
        [(s["entity_id"], friendly_state(s), s["attributes"].get("friendly_name", "")) for s in states],
        ["ENTITY", "STATE", "NAME"],
    )


def cmd_get(args, c):
    eid = ensure_entity(c, args.entity_id)
    s = c.get(f"/api/states/{eid}")
    if args.json:
        return out_json(s)
    print(f"{s['entity_id']}: {friendly_state(s)}")
    print(f"  last_changed: {s.get('last_changed')}")
    for k, v in sorted(s.get("attributes", {}).items()):
        print(f"  {k}: {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}")


def _service_on_entities(c, service, entity_ids, extra, as_json):
    results = []
    for raw in entity_ids:
        eid = ensure_entity(c, raw)
        domain = eid.split(".")[0]
        # Domain-specific services accept extra data (brightness, etc.); groups go via 'homeassistant'.
        svc_domain = "homeassistant" if domain == "group" else domain
        svc = service
        if domain == "cover":
            svc = {"turn_on": "open_cover", "turn_off": "close_cover"}.get(service, service)
        if domain == "lock":
            svc = {"turn_on": "unlock", "turn_off": "lock"}.get(service, service)
        if domain in ("scene",) and service == "turn_off":
            raise HAError(f"{eid}: scenes cannot be turned off")
        body = {"entity_id": eid, **extra}
        res = c.post(f"/api/services/{svc_domain}/{svc}", body)
        results.append(res)
        if not as_json:
            print(f"{svc_domain}.{svc} -> {eid}")
    if as_json:
        out_json(results)


def cmd_on(args, c):
    _service_on_entities(c, "turn_on", args.entity_ids, parse_kv(args.data), args.json)


def cmd_off(args, c):
    _service_on_entities(c, "turn_off", args.entity_ids, parse_kv(args.data), args.json)


def cmd_toggle(args, c):
    _service_on_entities(c, "toggle", args.entity_ids, parse_kv(args.data), args.json)


def cmd_call(args, c):
    if "." not in args.service:
        raise HAError("Service must be domain.service, e.g. light.turn_on")
    domain, service = args.service.split(".", 1)
    body = {}
    if args.json_data:
        body.update(json.loads(args.json_data))
    body.update(parse_kv(args.data))
    if args.entity:
        body["entity_id"] = [ensure_entity(c, e) for e in args.entity]
        if len(body["entity_id"]) == 1:
            body["entity_id"] = body["entity_id"][0]
    params = {"return_response": ""} if args.response else None
    res = c.post(f"/api/services/{domain}/{service}", body, params=params)
    if args.json or args.response:
        return out_json(res)
    changed = res if isinstance(res, list) else []
    print(f"Called {args.service}; {len(changed)} state(s) changed")
    for s in changed:
        print(f"  {s['entity_id']}: {friendly_state(s)}")


def cmd_services(args, c):
    data = c.get("/api/services")
    if args.domain:
        data = [d for d in data if d["domain"] == args.domain]
    if args.json:
        return out_json(data)
    rows = []
    for d in sorted(data, key=lambda d: d["domain"]):
        for name, info in sorted(d["services"].items()):
            rows.append((f"{d['domain']}.{name}", (info.get("description") or info.get("name") or "")[:70]))
    table(rows, ["SERVICE", "DESCRIPTION"])


def _since(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def cmd_history(args, c):
    eid = ensure_entity(c, args.entity_id)
    data = c.get(f"/api/history/period/{urllib.parse.quote(_since(args.hours))}",
                 params={"filter_entity_id": eid, "minimal_response": "", "no_attributes": ""})
    if args.json:
        return out_json(data)
    rows = [(e.get("last_changed", ""), e.get("state", "")) for series in data for e in series]
    table(rows, ["TIME", "STATE"])


def cmd_logbook(args, c):
    params = {"entity": ensure_entity(c, args.entity)} if args.entity else None
    data = c.get(f"/api/logbook/{urllib.parse.quote(_since(args.hours))}", params=params)
    if args.json:
        return out_json(data)
    table([(e.get("when", "")[:19], e.get("entity_id") or e.get("domain", ""),
            e.get("message") or e.get("state", "")) for e in data], ["WHEN", "ENTITY", "MESSAGE"])


def cmd_template(args, c):
    tpl = args.template if args.template != "-" else sys.stdin.read()
    print(c.post("/api/template", {"template": tpl}, raw=True))


def cmd_fire(args, c):
    body = json.loads(args.json_data) if args.json_data else {}
    body.update(parse_kv(args.data))
    res = c.post(f"/api/events/{args.event_type}", body)
    print(res.get("message", res) if isinstance(res, dict) else res)


def cmd_events(args, c):
    data = c.get("/api/events")
    if args.json:
        return out_json(data)
    table([(e["event"], e["listener_count"]) for e in sorted(data, key=lambda e: e["event"])],
          ["EVENT", "LISTENERS"])


def cmd_log(args, c):
    text = c.get("/api/error_log", raw=True)
    lines = text.splitlines()
    print("\n".join(lines[-args.lines:] if args.lines else lines))


def cmd_check(args, c):
    res = c.post("/api/config/core/check_config")
    if args.json:
        return out_json(res)
    print(f"Result: {res.get('result')}")
    if res.get("errors"):
        print(res["errors"])


def cmd_restart(args, c):
    if not args.yes and input(f"Restart Home Assistant at {c.url}? [y/N] ").lower() != "y":
        return print("Aborted")
    try:
        c.post("/api/services/homeassistant/restart")
    except HAError as e:  # connection often drops while restarting
        if "Cannot reach" not in str(e) and "502" not in str(e):
            raise
    print("Restart requested")


def cmd_raw(args, c):
    body = json.loads(args.body) if args.body else None
    res = c.request(args.method.upper(), args.path if args.path.startswith("/") else "/" + args.path, body=body)
    out_json(res) if not isinstance(res, str) else print(res)


# --------------------------------------------------------------------------- parser

def build_parser():
    p = argparse.ArgumentParser(prog="ha", description="Command-line client for Home Assistant.")
    p.add_argument("--url", help=f"Home Assistant base URL (default {DEFAULT_URL})")
    p.add_argument("--token", help="Long-lived access token")
    p.add_argument("-k", "--insecure", action="store_true", help="Skip TLS certificate verification")
    p.add_argument("--timeout", type=float, default=15)
    sub = p.add_subparsers(dest="cmd", metavar="COMMAND")
    sub.required = True

    def add(name, func, help_, json_flag=True, **kw):
        sp = sub.add_parser(name, help=help_, description=help_, **kw)
        sp.set_defaults(func=func)
        if json_flag:
            sp.add_argument("-j", "--json", action="store_true", help="Raw JSON output")
        return sp

    add("login", cmd_login, "Save URL and token to the config file", json_flag=False)
    add("status", cmd_status, "Show server info")

    sp = add("states", cmd_states, "List entities and their states", aliases=["ls"])
    sp.add_argument("filter", nargs="?", help="Substring or glob, e.g. 'kitchen' or 'sensor.*temp*'")
    sp.add_argument("-d", "--domain", help="Only this domain (light, sensor, ...)")
    sp.add_argument("-s", "--state", help="Only entities in this state (on, off, unavailable, ...)")

    sp = add("get", cmd_get, "Show one entity with attributes")
    sp.add_argument("entity_id")

    for name, func, h in (("on", cmd_on, "Turn entities on"), ("off", cmd_off, "Turn entities off"),
                          ("toggle", cmd_toggle, "Toggle entities")):
        sp = add(name, func, h)
        sp.add_argument("entity_ids", nargs="+", metavar="ENTITY")
        sp.add_argument("-D", "--data", action="append", metavar="KEY=VALUE",
                        help="Extra service data, e.g. -D brightness_pct=50")

    sp = add("call", cmd_call, "Call any service, e.g. `ha call light.turn_on -e light.kitchen -D brightness=100`")
    sp.add_argument("service", help="domain.service")
    sp.add_argument("-e", "--entity", action="append", help="Target entity (repeatable)")
    sp.add_argument("-D", "--data", action="append", metavar="KEY=VALUE", help="Service data (repeatable)")
    sp.add_argument("--json-data", help="Service data as a JSON object")
    sp.add_argument("-r", "--response", action="store_true", help="Request and print the service response")

    sp = add("services", cmd_services, "List available services")
    sp.add_argument("domain", nargs="?")

    sp = add("history", cmd_history, "Show state history of an entity")
    sp.add_argument("entity_id")
    sp.add_argument("-H", "--hours", type=float, default=24)

    sp = add("logbook", cmd_logbook, "Show logbook entries")
    sp.add_argument("entity", nargs="?")
    sp.add_argument("-H", "--hours", type=float, default=24)

    sp = add("template", cmd_template, "Render a Jinja template ('-' reads stdin)", json_flag=False)
    sp.add_argument("template")

    sp = add("fire", cmd_fire, "Fire an event", json_flag=False)
    sp.add_argument("event_type")
    sp.add_argument("-D", "--data", action="append", metavar="KEY=VALUE")
    sp.add_argument("--json-data")

    add("events", cmd_events, "List event types and listener counts")

    sp = add("log", cmd_log, "Show the error log", json_flag=False)
    sp.add_argument("-n", "--lines", type=int, default=50, help="Last N lines (0 = all)")

    add("check", cmd_check, "Validate configuration.yaml")

    sp = add("restart", cmd_restart, "Restart Home Assistant", json_flag=False)
    sp.add_argument("-y", "--yes", action="store_true")

    sp = add("raw", cmd_raw, "Send a raw API request, e.g. `ha raw GET /api/config`", json_flag=False)
    sp.add_argument("method")
    sp.add_argument("path")
    sp.add_argument("body", nargs="?", help="JSON body")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = load_config()
    url = args.url or os.environ.get("HA_URL") or cfg.get("url") or DEFAULT_URL
    token = args.token or os.environ.get("HA_TOKEN") or cfg.get("token")
    insecure = args.insecure or cfg.get("insecure", False)
    client = Client(url, token, insecure=insecure, timeout=args.timeout)
    try:
        args.func(args, client)
    except HAError as e:
        print(f"ha: error: {e}", file=sys.stderr)
        return 1
    except (ValueError, json.JSONDecodeError) as e:
        print(f"ha: error: bad JSON: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
