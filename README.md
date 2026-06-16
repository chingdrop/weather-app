# weather-app

A Flask service that sends local weather notifications via [ntfy](https://ntfy.sh). It runs a background scheduler for
automatic reports and exposes an HTTP endpoint for on-demand requests.

## Features

- **Daily report** — sent every morning at a configurable hour (default 7:00 AM). Includes high/low temps, feels-like
  max, rain chance, wind gusts, UV index, sunrise/sunset, a simple outdoor recommendation, and an hour-by-hour
  breakdown from 7 AM to 11 PM. If the app restarts after the scheduled time and no report has been sent yet today,
  one is sent immediately on startup.
- **Rain alert** — checks on a configurable interval (default every 15 minutes) and fires a high-priority notification
  when rain is expected within the next few hours. Includes a per-hour breakdown of conditions and probability for the
  full rain window. Cooldown lasts until the end of the forecasted rain event; re-alerts immediately if the weather
  code changes (e.g. light rain escalates to thunderstorm).
- **Wind gust alert** — fires when forecast gusts exceed the configured threshold. Includes a per-hour gust breakdown.
  Cooldown lasts until the end of the wind event; re-alerts immediately if peak gusts increase.
- **Heat risk alert** — fires when feels-like temperature exceeds the configured threshold. Includes a per-hour
  feels-like breakdown. Cooldown lasts until the end of the heat event; re-alerts immediately if the peak rises.
- **Quick report** — on-demand current conditions via `GET /report`.

Weather data is sourced from [Open-Meteo](https://open-meteo.com) (free, no API key required). Notifications are
delivered through [ntfy](https://ntfy.sh) (free, self-hostable).

## Requirements

- Python 3.12+
- A [ntfy](https://ntfy.sh) topic (subscribe in the ntfy mobile/web app to receive notifications)

## Setup

```bash
# Install dependencies
uv sync

# Copy and fill in the config
cp .env.example .env
```

Edit `.env`:

| Variable                  | Description                                                                        | Default            |
|---------------------------|------------------------------------------------------------------------------------|--------------------|
| `NTFY_TOPIC`              | Long random string — the ntfy topic you subscribe to                               | *(required)*       |
| `LAT`                     | Latitude of your location                                                          | *(required)*       |
| `LON`                     | Longitude of your location                                                         | *(required)*       |
| `TIMEZONE`                | [IANA timezone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) | `America/New_York` |
| `DB_PATH`                 | Path to the SQLite database file                                                   | `weather.db`       |
| `HOST`                    | Bind address (`127.0.0.1` for local dev, `0.0.0.0` inside Docker)                  | `127.0.0.1`        |
| `PORT`                    | Port to listen on                                                                  | `5000`             |
| `FLASK_DEBUG`             | Set to `1` for debug logging and Flask debug mode (local dev only)                 | `0`                |
| `DAILY_REPORT_HOUR`       | Hour to send the daily report (24-hour format)                                     | `7`                |
| `ALERT_INTERVAL_MIN`      | How often to check for weather alerts (minutes)                                    | `15`               |
| `RAIN_PROB_ALERT_PERCENT` | Rain probability threshold for alerts (%)                                          | `50`               |
| `RAIN_AMOUNT_ALERT_IN`    | Rain amount threshold for alerts (inches)                                          | `0.05`             |
| `WIND_GUST_ALERT_MPH`     | Wind gust threshold for alerts (mph)                                               | `30`               |
| `HEAT_INDEX_ALERT_F`      | Feels-like temperature threshold for heat alerts (°F)                              | `100`              |

## Running locally

```bash
python main.py
```

The scheduler starts automatically. Trigger a quick report at any time:

```bash
curl http://127.0.0.1:5000/report
```

## Docker

```bash
docker compose up -d
```

The compose file binds to `127.0.0.1:5000` by default — put a reverse proxy (nginx, Caddy) in front if you need external
access.

## API endpoints

| Method | Path               | Description                                                             |
|--------|--------------------|-------------------------------------------------------------------------|
| `GET`  | `/report`          | Sends a current conditions notification and returns the message as JSON |
| `GET`  | `/health`          | Returns `{"status": "ok"}` — useful for uptime monitoring               |
| `GET`  | `/history/reports` | Returns past reports. Optional `?type=daily\|quick` and `?limit=N`      |
| `GET`  | `/history/alerts`  | Returns past alerts. Optional `?type=rain\|wind\|heat` and `?limit=N`   |

## Logging

Log level is controlled by `FLASK_DEBUG`:

- **Development** (`FLASK_DEBUG=1`) — `DEBUG`: all output including APScheduler internals
- **Production** (`FLASK_DEBUG=0`) — `WARNING`: startup banner, sent alerts/reports, and errors only

## Tests

```bash
pytest
```

## Project structure

```
adapter.py      # Generic HTTP client (retries, content-type parsing)
weather.py      # Open-Meteo client, WMO codes, fetch helpers, compass
notifier.py     # ntfy client and send_notification
db.py           # SQLAlchemy models (Report, Alert) and database queries
jobs.py         # Scheduled job functions — daily report, alerts, quick report
main.py         # Flask app, routes, startup wiring
wsgi.py         # Gunicorn entry point
tests/
  test_adapter.py
  test_weather.py
  test_notifier.py
  test_db.py
  test_jobs.py
  test_main.py
```