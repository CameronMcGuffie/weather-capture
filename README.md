# Weather Capture

Just a small app that uses RTL 433 to capture from my weather station and store it locally on a dashboard. Just for running locally on unraid. It's nothing fancy, it's just made for me using AI to make it quick and simple.

---

Autonomous weather station appliance for a Fine Offset WHx080 sensor. A FastAPI
backend supervises a persistent `rtl_433` process, stores every reading in
SQLite, and serves a React dashboard for live metrics and historical charts.

## Features

- Manages `rtl_433` as a long-running subprocess: starts it, watches it, and
  restarts it with exponential backoff if it dies.
- Every decoded reading (plus the raw JSON line) is written to SQLite, indexed
  on `timestamp` for fast range queries.
- REST API: current conditions, aggregated history, CSV export, a
  Home Assistant-compatible feed, and agent-friendly endpoints for OpenClaw.
- Dashboard: live metric cards with trend arrows, feels-like and dew point, an
  animated wind compass, a today-vs-yesterday comparison, interactive charts
  (1h / 12h / 24h / 7d / 30d / custom with a min–max band, hour-by-hour
  navigation, a this-week-vs-last-week comparison, and the night shaded in from
  sunrise and sunset), rain per hour or day, a wind rose, all-time records, a
  station-health strip showing how reliably readings are arriving, and a
  status indicator tied to the ingestion process's actual health.
- Rain history repairs itself: on startup the app checks stored rain totals for
  bad readings and fixes them, after taking a backup first (see
  [Automatic rain repair](#automatic-rain-repair)).
- Single Docker image (multi-stage build) with `docker-compose.yml` for
  one-command deployment.

## Requirements

- An RTL-SDR dongle within range of a Fine Offset WHx080 (or compatible
  WH65/WH24-family) transmitter.
- Docker and Docker Compose, for the standard deployment path (including on
  Unraid via the Docker Compose / Compose Manager plugins).
- For local development without Docker: Python 3.12+, Node.js 22+, and
  `rtl_433` installed and on `PATH`.

## Quick start (Docker)

```bash
cp .env.example .env   # optional — defaults already match the WHx080 settings below
docker compose up --build -d
```

The dashboard is served at `http://<host>:8000/`. Readings persist in the
`weather-data` named volume (SQLite file at `/data/weather.db` inside the
container).

The container needs access to the RTL-SDR dongle. `docker-compose.yml` maps
`/dev/bus/usb` into the container. On some hosts (or inside a VM) the USB
device node's permissions still won't allow libusb access from the
container's default user; if `rtl_433` keeps restarting with a "no supported
devices found" or permission error, add `privileged: true` to the service in
`docker-compose.yml`.

## Deploying on Unraid from your own GitHub image

Pushing to `main` triggers [.github/workflows/docker-publish.yml](.github/workflows/docker-publish.yml),
which builds the image and publishes it to GitHub Container Registry at
`ghcr.io/cameronmcguffie/weather-capture:latest`. Unraid then just pulls that
image — it never needs the source or a build step.

**1. Make the package pullable.** The first push creates a package on your
GitHub account under *Packages*. By default GHCR packages linked to a repo
are private, and Unraid has no way to authenticate to GHCR out of the box, so
either:

- open the package's settings on GitHub and change its visibility to
  **Public** (simplest), or
- on the Unraid host, run `docker login ghcr.io -u CameronMcGuffie` with a
  GitHub [personal access token](https://github.com/settings/tokens) that has
  `read:packages` scope, so Unraid's Docker daemon can pull a private image.

**2. Add the container.** Two ways to do it, pick whichever you already use:

- *Native Docker UI* — Docker tab → **Add Container**, and fill in:

  | Field | Value |
  |---|---|
  | Repository | `ghcr.io/cameronmcguffie/weather-capture:latest` |
  | Network Type | `Bridge` |
  | Port | Container `8000` → Host `8000` (or whatever's free) |
  | Path | Container `/data` → Host `/mnt/user/appdata/weather-capture` |
  | Extra Parameters | `--device=/dev/bus/usb:/dev/bus/usb` (add `--privileged` too if the dongle isn't detected) |

  Add any of the environment variables from the Configuration table below as
  extra config fields if you need to override a default.

- *Compose Manager plugin* — point it at [docker-compose.unraid.yml](docker-compose.unraid.yml)
  in this repo, which is the same as `docker-compose.yml` but pulls the GHCR
  image instead of building locally, and maps `/data` to
  `/mnt/user/appdata/weather-capture`. Adjust the image tag or the appdata
  path if yours differs.

**3. Update later.** Re-pushing to `main` publishes a new `:latest`; on
Unraid just hit **Check for Updates** / **Force Update** on the container (or
`docker compose pull && docker compose up -d` if you used Compose Manager).

## Configuration

All settings can be overridden via a `.env` file (see `.env.example`) or by
editing the `environment` section of `docker-compose.yml`. Defaults already
match the verified WHx080 configuration.

| Variable                     | Default                        | Purpose                                             |
|-------------------------------|--------------------------------|------------------------------------------------------|
| `RTL_FREQUENCY`               | `433.925M`                     | `rtl_433 -f`                                          |
| `RTL_SAMPLE_RATE`             | `1000k`                        | `rtl_433 -s`                                          |
| `RTL_GAIN`                    | `40`                           | `rtl_433 -g`                                          |
| `RTL_EXTRA_FLAGS`             | `-Y autolevel -Y magest`       | Extra flags inserted before `-F json`                |
| `RTL_433_PATH`                | `rtl_433`                      | Path to the binary (only needed if not on `PATH`)    |
| `DATABASE_PATH`               | `/data/weather.db`             | SQLite file location                                  |
| `RESTART_BACKOFF_SECONDS`     | `5`                            | Initial delay before restarting a crashed `rtl_433`  |
| `MAX_RESTART_BACKOFF_SECONDS` | `60`                           | Cap for the exponential backoff                      |
| `STALE_READING_SECONDS`       | `180`                          | How long without a reading before status turns stale |
| `WATCHDOG_TIMEOUT_SECONDS`    | `90`                           | Kill and retry `rtl_433` if no reading arrives in this long, even if it's still "running" |
| `CORS_ORIGINS`                | `*`                            | Comma-separated allowed origins, or `*`               |
| `SENSOR_MODEL_FILTER`         | `Fineoffset`                   | Only readings whose model name contains this are kept (empty = accept any) |
| `SENSOR_ID_FILTER`            | *(unset)*                      | Optionally lock onto one physical sensor's id (see `sensor_id` in `/api/latest`) |
| `LOG_LEVEL`                   | `INFO`                         | Set to `DEBUG` to log every raw rtl_433 line          |
| `WEB_PORT`                    | `8000`                         | Host port published by `docker-compose.yml`          |
| `LATITUDE` / `LONGITUDE`      | *(unset)*                      | Where the station is, in decimal degrees (e.g. `-27.54` / `153.19`). Only used to shade night on the chart; leave blank and the shading is simply off. A suburb-level figure is plenty |

## API

| Endpoint       | Description                                                        |
|----------------|----------------------------------------------------------------------|
| `GET /api/latest`  | Most recent decoded reading                                        |
| `GET /api/history` | `?range=1h\|12h\|24h\|7d\|30d\|custom&start=&end=` — per-minute averages for spans ≤24h, hourly beyond that, each with min/max. Rain is relative to the start of the window |
| `GET /api/summary` | `?hours=24` — low, high and rain total over the last N hours (feeds the dashboard tiles) |
| `GET /api/export`  | `?start=&end=` — every stored reading in the range as a streamed CSV |
| `GET /api/ha`      | Flattened JSON for Home Assistant RESTful sensors                  |
| `GET /api/status`  | `rtl_433` subprocess health: status, PID, restart count, last error |
| `GET /api/now`     | Feels-like, dew point, 3-hour trends and whether it's raining      |
| `GET /api/rain-bars` | `?hours=24&bucket=hour\|day&utc_offset_minutes=` — rain that fell in each hour or day |
| `GET /api/wind-rose` | `?hours=720` — how often the wind came from each of 16 directions, split by strength |
| `GET /api/period`  | `?start=&end=` — high, low, peak gust and rain for a stretch of time (feeds "Today") |
| `GET /api/records` | `?utc_offset_minutes=` — hottest, coldest, strongest gust, wettest day and rain totals since recording began |
| `GET /api/station-health` | `?hours=48` — readings received per hour, longest gap, battery and glitch counts |
| `GET /api/sun`     | `?start=&end=` — sunrise and sunset times in a window (needs `LATITUDE`/`LONGITUDE`) |
| `GET /api/openclaw`        | Agent snapshot: current conditions, per-period stats, station health (below) |
| `GET /api/openclaw/series` | Agent time series: minute, hourly or daily buckets (below)  |

Timestamps you send can carry any UTC offset; a time with no offset is read as
UTC. Prefer a trailing `Z` (`2026-07-04T08:00:00Z`): in a URL a literal `+` turns
into a space, so an offset has to be written `%2B10:00`. Everything returned is UTC.

### OpenClaw

Two read-only endpoints for an AI agent. There's no API key: the service is
meant to be reachable only on the local network, so don't expose the port to the
internet. Responses carry their own units and conventions, and the full
parameter documentation is in the OpenAPI spec at `/openapi.json` (or `/docs`),
which an agent can read directly.

`GET /api/openclaw?windows=1h,12h,24h,7d,30d` answers most questions in one
call: the current reading, whether the station is alive (`is_stale`,
`reading_age_seconds`, battery), and for each window the min / max / average
temperature, humidity and wind, the strongest gust, the prevailing wind
direction, and the rain that fell. Windows are a whole number plus `h` or `d`
(up to 8 per request, 1h to 366d).

`GET /api/openclaw/series` gives a time series:

| Parameter | Meaning |
|---|---|
| `hours` | How far back to look (default 24) |
| `end` | Where the window ends (default now); set it to look at a past period |
| `resolution` | `minute`, `hourly`, `daily`, or `auto` (the default: minute up to 3h, hourly up to 14 days, daily beyond) |
| `utc_offset_minutes` | For `daily` only: the timezone that decides where a day starts (UTC+10 is `600`) |
| `fields` | Any of `temperature,humidity,wind,rain` to trim the response |

Rain here is the rain that fell in the period or bucket. Wind direction is the
direction the wind blows *from*, and over a window it's the prevailing direction
(averaged properly around north, not as a plain mean of degrees). Requests that
would return more than 5000 points are refused with a message saying how to
coarsen them. For every raw reading, use `/api/export`.

Home Assistant example (`configuration.yaml`):

```yaml
sensor:
  - platform: rest
    resource: http://weather-capture:8000/api/ha
    name: Weather Station
    value_template: "{{ value_json.temperature_c }}"
    json_attributes:
      - humidity
      - wind_dir_deg
      - wind_avg_km_h
      - wind_max_km_h
      - rain_mm
      - battery_ok
```

## Local development

Backend:

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate  # or source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend (proxies `/api` to `http://localhost:8000`):

```bash
cd frontend
npm install
npm run dev
```

## Data model

`weather_readings` stores one row per `rtl_433` JSON line:

- `id` — primary key
- `timestamp` — UTC, indexed
- `raw_payload` — the exact line emitted by `rtl_433`
- `decoded_data` — normalized JSON (adds `wind_avg_km_h`/`wind_max_km_h`
  alongside the original fields)

SQLite runs in WAL mode so the ingestion writer and API reads don't block
each other.

The sensor reports a lifetime rain counter. Each reading also stores
`rain_total_mm`, a running total that carries on through counter resets
(new batteries); every rain figure the API gives is a difference of that total.
The raw counter value is never overwritten: it stays in `raw_payload` and in
`rain_mm`.

### Automatic rain repair

Older versions could be fooled by a glitched rain reading (the counter briefly
reading 0 or a wild value), which counted as a battery change and inflated the
running total by hundreds of millimetres. When the app starts it looks back over
the stored history, works out which readings were glitches and which were genuine
resets, and rewrites only `rain_total_mm` where it was wrong. It's safe to leave
on:

- It runs once; a note in the `meta` table stops it running again.
- Before changing anything it makes a copy of the database next to it, named
  `weather.db.pre-rain-repair-<timestamp>` (in `/data`, so on Unraid in your
  appdata folder), after checking there's enough free disk space. The copy is
  verified before the repair starts, and if the repair can't proceed nothing is
  changed.
- The rewrite happens in a single transaction, so it either completes or leaves
  the data as it was.
- If an unexpectedly large share of readings looks like noise, it assumes its
  own judgement is the problem, changes nothing and says so in the log.

Look for `rain history repaired: …` in the container log; it lists each glitch
it found and how many millimetres of phantom rain were removed. Once you're
happy with the numbers you can delete the backup file. One known limit: a
glitch or counter reset that happens while the counter is below 50 mm can add
up to that much once.

## Ingestion resilience

433MHz is unlicensed and unauthenticated — anything transmitting nearby (a
neighbor's weather station, a car remote, a garage door, or deliberately
crafted noise) can make `rtl_433` emit a line that looks like valid JSON. The
ingestion pipeline treats every line as untrusted:

- **Malformed input** — non-JSON lines, JSON that isn't an object (arrays,
  bare numbers), and oversized lines (>8KB) are discarded before they're ever
  parsed as a reading.
- **Non-finite numbers** — `NaN`/`Infinity`/`-Infinity` tokens are technically
  accepted by Python's JSON parser but aren't valid JSON and would break any
  standards-compliant consumer (like the browser); these lines are rejected.
- **Wrong device** — readings are matched against `SENSOR_MODEL_FILTER` (and
  optionally `SENSOR_ID_FILTER`) before being stored, so a different 433MHz
  device in range can't get mixed into this station's history. Rejected
  readings are counted in `/api/status` as `ignored_count`.
- **Implausible values** — even from the right device, each field is checked
  against a physically plausible range (e.g. -50–60°C, 0–100% humidity); a
  field outside that range is nulled rather than discarding the whole
  reading, so one corrupted field doesn't cost an otherwise-good reading.
- **Corrupt rain readings** — the rain counter only goes up, so a reading
  that drops (or leaps) looks just like a counter reset, and acting on one
  corrupt value would add it to the running total twice. Any such reading is
  held back until the next reading agrees with it; if the next reading is
  back to normal, the held one is discarded. Its raw value stays in
  `raw_payload`.
- **No reading can crash ingestion** — any unexpected failure while
  processing a single line is caught and logged; it's discarded without
  restarting the `rtl_433` subprocess.
- **Log/terminal injection** — raw lines are logged for debugging, so a
  crafted payload containing a bare `\r` or an ANSI escape sequence could
  otherwise forge or hide log lines in a terminal tailing the logs. Control
  characters are stripped before the text is logged or stored.
- **No SQL injection, SSRF, or command injection** — every query uses
  parameterized SQL, the app makes zero outbound network requests, and
  `rtl_433` is launched via an argument list (not a shell), so there's no
  path from a crafted reading to any of these.
- **Stuck-but-still-running `rtl_433`** — normally a dead/crashed `rtl_433`
  triggers the exponential-backoff restart loop, but it can also fail to
  claim the USB dongle (most commonly right after a redeploy, before the
  previous container's process has released it) without ever exiting on its
  own. A watchdog kills and restarts it if no reading arrives within
  `WATCHDOG_TIMEOUT_SECONDS`, regardless of whether the process technically
  looks "running". `rtl_433`'s own stderr diagnostics (device detection,
  tuner info, USB errors) are also logged at INFO, prefixed `rtl_433:`, so
  you can see what it's actually doing.
