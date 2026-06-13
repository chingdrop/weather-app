# weather-app

A Flask service that sends local weather notifications via [ntfy](https://ntfy.sh). It runs a background scheduler for automatic reports and exposes an HTTP endpoint for on-demand requests.

## Features

- **Daily report** — sent every morning at 7:00 AM with high/low temps, rain chance, UV index, and sunrise/sunset
- **Rain alert** — checks every 30 minutes and sends a high-priority notification when rain is expected within the next few hours (2-hour cooldown between alerts)
- **Quick report** — on-demand current conditions via `GET /report`

Weather data is sourced from [Open-Meteo](https://open-meteo.com) (free, no API key required). Notifications are delivered through [ntfy](https://ntfy.sh) (free, self-hostable).

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

| Variable | Description |
|---|---|
| `NTFY_TOPIC` | Long random string — the ntfy topic you subscribe to |
| `LAT` | Latitude of your location |
| `LON` | Longitude of your location |
| `TIMEZONE` | [IANA timezone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) (e.g. `America/New_York`) |
| `HOST` | Bind address (`127.0.0.1` for local dev, `0.0.0.0` inside Docker) |
| `PORT` | Port to listen on (default `5000`) |
| `FLASK_DEBUG` | Set to `1` for debug mode, `0` in production |

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

The compose file binds to `127.0.0.1:5000` by default — put a reverse proxy (nginx, Caddy) in front if you need external access.

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/report` | Sends a current conditions notification and returns the message as JSON |
| `GET` | `/health` | Returns `{"status": "ok"}` — useful for uptime monitoring |

## Tests

```bash
pytest
```

## Project structure

```
adapter.py      # Generic HTTP client (retries, content-type parsing)
weather.py      # Open-Meteo client, WMO codes, fetch/compass helpers
notifier.py     # ntfy client and send_notification
main.py         # Flask app, scheduled tasks, entry point
tests/
  test_adapter.py
  test_weather.py
  test_notifier.py
  test_main.py
```