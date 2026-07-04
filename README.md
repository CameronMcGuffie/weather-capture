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
- REST API: current conditions, aggregated history, CSV export, and a
  Home Assistant-compatible feed.
- Dashboard: live metric cards, an animated wind compass, interactive charts
  (1h / 24h / 7d / 30d / custom, plus a this-week-vs-last-week comparison),
  and a status indicator tied to the ingestion process's actual health.
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
| `CORS_ORIGINS`                | `*`                            | Comma-separated allowed origins, or `*`               |
| `WEB_PORT`                    | `8000`                         | Host port published by `docker-compose.yml`          |

## API

| Endpoint       | Description                                                        |
|----------------|----------------------------------------------------------------------|
| `GET /api/latest`  | Most recent decoded reading                                        |
| `GET /api/history` | `?range=1h\|24h\|7d\|30d\|custom&start=&end=` — raw points for spans ≤24h, hourly averages beyond that |
| `GET /api/export`  | `?start=&end=` — CSV download for the given range                  |
| `GET /api/ha`      | Flattened JSON for Home Assistant RESTful sensors                  |
| `GET /api/status`  | `rtl_433` subprocess health: status, PID, restart count, last error |

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
