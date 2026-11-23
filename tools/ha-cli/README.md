# ha — Home Assistant CLI

Single-file, dependency-free (Python 3.8+) client for the Home Assistant REST API.
Defaults to `http://192.168.1.21:8123`.

## Setup

1. In Home Assistant: **Profile → Security → Long-lived access tokens → Create token**.
2. Install and log in:

```sh
install -m 755 ha.py ~/.local/bin/ha     # or: ln -s "$PWD/ha.py" ~/.local/bin/ha
ha login                                  # prompts for URL (Enter = 192.168.1.21:8123) and token
```

The token is stored in `~/.config/ha-cli/config.json` (mode 600). Alternatively set
`HA_URL` / `HA_TOKEN` env vars or pass `--url` / `--token`. Use `-k` for self-signed HTTPS.

## Examples

```sh
ha status                                  # version, entity count
ha ls                                      # all entities
ha ls kitchen                              # substring filter
ha ls 'sensor.*temp*'                      # glob filter
ha ls -d light -s on                       # lights that are on
ha get sensor.living_temp                  # state + attributes
ha on kitchen -D brightness_pct=40         # short names work if unambiguous
ha off light.kitchen switch.fan
ha toggle light.hallway
ha call light.turn_on -e light.desk -D rgb_color=[255,0,0]
ha call weather.get_forecasts -e weather.home -D type=daily -r   # with service response
ha services light
ha history sensor.living_temp -H 6
ha logbook -H 2
ha template '{{ states("sun.sun") }}'
ha fire my_event -D foo=bar
ha log -n 100                              # error log
ha check                                   # validate config
ha restart -y
ha raw GET /api/config
```

Add `-j` to most commands for raw JSON (pipe into `jq`).
