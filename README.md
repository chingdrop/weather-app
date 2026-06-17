# weather-app

A Flask service that sends local weather notifications via [ntfy](https://ntfy.sh). It runs a background scheduler
for automatic reports, checks for alert conditions on a configurable interval, and exposes a web UI for configuration.

## Features

- **Daily report** — sent every morning at a configurable hour (default 7:00 AM). Includes high/low temps, feels-like
  max, rain chance, wind gusts, UV index, sunrise/sunset, a simple outdoor recommendation, and an hour-by-hour
  breakdown from 7 AM to 11 PM. If the app restarts after the scheduled time and no report has been sent yet today,
  one is sent immediately on startup.
- **Evening report** — sent nightly at a configurable hour (default 9:00 PM) with tomorrow's full forecast.
- **Rain alert** — checks on a configurable interval (default every 15 minutes) and fires a high-priority notification
  when rain is expected within the next few hours. Includes a per-hour breakdown of conditions and probability for the
  full rain window. Cooldown lasts until the end of the forecasted rain event; re-alerts immediately if the weather
  code changes (e.g. light rain escalates to thunderstorm).
- **Wind gust alert** — fires when forecast gusts exceed the configured threshold. Cooldown lasts until the end of
  the wind event; re-alerts immediately if peak gusts increase.
- **Heat risk alert** — fires when feels-like temperature exceeds the configured threshold. Re-alerts if the peak rises.
- **Frost alert** — fires when feels-like temperature drops below the configured threshold. Re-alerts if it drops further.
- **Quick report** — on-demand current conditions via `GET /report`.
- **Web UI** — configure locations, alert thresholds, and scheduler settings without restarting the app.

Weather data is sourced from [Open-Meteo](https://open-meteo.com) (free, no API key required). Notifications are
delivered through [ntfy](https://ntfy.sh) (free, self-hostable).

## Requirements

- Python 3.12+
- A [ntfy](https://ntfy.sh) topic (subscribe in the ntfy mobile/web app to receive notifications)

## Setup

```bash
uv sync
cp .env.example .env
python main.py
```

Then open `http://127.0.0.1:5000/setup` to add your first location and ntfy topic. All location config and alert
thresholds are managed through the web UI — no need to edit config files.

## Environment variables

Infrastructure settings go in `.env`. Everything else (locations, thresholds, scheduler timing) is managed via the
web UI and stored in the database.

| Variable                  | Description                                                                | Default       |
|---------------------------|----------------------------------------------------------------------------|---------------|
| `NTFY_SELF_HOSTED`        | Set to `1` to publish to the self-hosted ntfy container                    | `0`           |
| `DB_PATH`                 | Path to the SQLite database file                                           | `weather.db`  |
| `SECRET_KEY`              | Flask session signing key — set a stable value in production               | random        |
| `HOST`                    | Bind address (`127.0.0.1` for local dev, `0.0.0.0` inside Docker)         | `127.0.0.1`   |
| `PORT`                    | Port to listen on                                                          | `5000`        |
| `FLASK_DEBUG`             | Set to `1` for debug logging and Flask debug mode (local dev only)         | `0`           |
| `DAILY_REPORT_HOUR`       | Fallback if not set in the web UI                                          | `7`           |
| `EVENING_REPORT_HOUR`     | Fallback if not set in the web UI                                          | `21`          |
| `ALERT_INTERVAL_MIN`      | Fallback if not set in the web UI                                          | `15`          |
| `RAIN_PROB_ALERT_PERCENT` | Fallback global threshold if not set in the web UI                         | `50`          |
| `RAIN_AMOUNT_ALERT_IN`    | Fallback global threshold if not set in the web UI                         | `0.05`        |
| `WIND_GUST_ALERT_MPH`     | Fallback global threshold if not set in the web UI                         | `30`          |
| `HEAT_INDEX_ALERT_F`      | Fallback global threshold if not set in the web UI                         | `100`         |
| `FROST_TEMP_ALERT_F`      | Fallback global threshold if not set in the web UI                         | `36`          |
| `UV_INDEX_ALERT`          | Fallback global threshold if not set in the web UI                         | `8`           |

## Docker

```bash
docker compose up -d
```

The compose file binds to `127.0.0.1:5000` by default — put a reverse proxy (nginx, Caddy) in front if you need
external access. See [DEPLOYMENT.md](DEPLOYMENT.md) for production setup.

## API endpoints

| Method | Path                          | Description                                                          |
|--------|-------------------------------|----------------------------------------------------------------------|
| `GET`  | `/health`                     | Returns `{"status": "ok"}` — for uptime monitoring                  |
| `GET`  | `/report`                     | Sends a current conditions notification and returns it as JSON       |
| `GET`  | `/history/reports`            | Past reports. Optional `?type=daily\|evening\|quick`, `?location=`, `?limit=N` |
| `GET`  | `/history/alerts`             | Past alerts. Optional `?type=rain\|wind\|heat\|frost`, `?location=`, `?limit=N` |
| `POST` | `/restart`                    | Gracefully restart the app process                                   |
| `GET`  | `/setup`                      | First-run setup wizard (redirects to /config/locations if configured) |
| `GET`  | `/config/locations`           | List and manage locations                                            |
| `GET`  | `/config/locations/new`       | Add a location                                                       |
| `GET`  | `/config/locations/<name>`    | Edit a location                                                      |
| `POST` | `/config/locations/<name>/delete` | Delete a location                                               |
| `GET`  | `/config/settings`            | Scheduler, database, and global threshold settings                   |

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
app/
  __init__.py      # Flask app factory, logging setup
  adapter.py       # Generic HTTP client (retries, content-type parsing)
  db.py            # SQLAlchemy models and database queries
  helpers.py       # Settings resolution, config building, form parsing
  jobs.py          # Scheduled job functions — reports, alerts, pruning
  monitor.py       # LocationConfig, LocationMonitor, alert config dataclasses
  notifier.py      # ntfy client
  startup.py       # App lifecycle — monitors, scheduler, startup()
  weather.py       # Open-Meteo client, WMO codes, fetch helpers
  routes/
    api.py         # /health, /report, /history/*, /restart
    config.py      # /config/locations/*, /config/settings
    setup.py       # /setup
  templates/
    base.html
    setup.html
    config/
main.py            # Development entry point (python main.py)
wsgi.py            # Gunicorn entry point
```