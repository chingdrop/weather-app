# Deployment

Single-container Flask + APScheduler weather app deployed with Docker Compose.

## Prerequisites

- Docker with Compose plugin (`docker compose version` to verify)
- A machine with outbound internet access to reach [Open-Meteo](https://open-meteo.com) and [ntfy.sh](https://ntfy.sh)

## Quickstart

```bash
git clone <your-repo-url> weather-app && cd weather-app
cp .env.example .env
```

Edit `.env` — at minimum set `NTFY_TOPIC`, `LAT`, and `LON`. See `.env.example` for the full list of options including alert thresholds and scheduler settings.

`NTFY_TOPIC` is required. The app will refuse to start without it.

Key optional variables (all have defaults):

| Variable             | Description                                     | Default |
|----------------------|-------------------------------------------------|---------|
| `DAILY_REPORT_HOUR`  | Hour to send the daily report (24-hour format)  | `7`     |
| `ALERT_INTERVAL_MIN` | How often to check for weather alerts (minutes) | `15`    |
| `FLASK_DEBUG`        | Set to `1` for debug logging (dev only)         | `0`     |

### Development

```bash
docker compose up -d --build
```

`docker-compose.override.yml` is picked up automatically. Flask debug mode is on, no restart policy.

### Production

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Adds `restart: unless-stopped`, healthchecks, and safe defaults (`FLASK_DEBUG=0`, `HOST=0.0.0.0`).

## API endpoints

```bash
# Trigger an on-demand weather report
curl http://127.0.0.1:5000/report

# Health check
curl http://127.0.0.1:5000/health

# View recent reports (optional: ?type=daily|quick&limit=N)
curl http://127.0.0.1:5000/history/reports

# View recent alerts (optional: ?type=rain|wind|heat&limit=N)
curl http://127.0.0.1:5000/history/alerts
```

## Notes

**Startup catch-up.** If the container restarts after the scheduled daily report time and no report has been recorded for today, one is sent automatically on startup.

**Logging.** In production (`FLASK_DEBUG=0`) the log level is `WARNING` — you will see the startup banner, any alerts/reports sent, and errors. Set `FLASK_DEBUG=1` in dev to get `DEBUG`-level output including APScheduler internals.

**One instance only.** The app embeds APScheduler inside the Flask process. Gunicorn is intentionally configured with
`--workers 1` — multiple workers would cause every scheduled job to fire once per worker.

**Network access.** The port is bound to `127.0.0.1:5000` by default, so it is only reachable from the host machine. To
expose it on your LAN or over a VPN, either change the port binding in `docker-compose.yml` to `"5000:5000"` or put a
reverse proxy (Caddy, nginx) in front of it.

**Database persistence.** The SQLite database is stored in `./data/weather.db` on the host, mounted into the container
at `/data`. This directory is excluded from git. Back it up alongside `.env` when moving to a new host.

**Portability.** The image has no baked-in secrets. Moving to a new host is: copy the project directory, copy `.env`,
copy `./data/`, run `docker compose up -d --build`.

---

## ntfy setup

The app publishes to [ntfy](https://ntfy.sh), an open-source push notification service. You have two options:

### Option A — ntfy.sh (hosted, no setup required)

1. Choose a long, unguessable topic name (e.g. `weather-abc123xyz`).
2. Set `NTFY_SELF_HOSTED=0` and `NTFY_TOPIC=<your-topic>` in `.env`.
3. Subscribe to that topic in the [ntfy app](https://ntfy.sh) or web UI.

Notifications are published to `https://ntfy.sh/<topic>` — anyone who knows the topic name can subscribe, so keep it private.

### Option B — self-hosted ntfy

The compose file includes an optional ntfy container. To use it:

1. Edit `ntfy/etc/server.yml` and set `base-url` to your host's reachable address:

   ```yaml
   base-url: "http://192.168.1.100:8080"
   ```

2. Set `NTFY_SELF_HOSTED=1` in `.env`. The weather app will publish internally over the Docker network.

3. Subscribe using any ntfy client pointed at `http://<your-host>:8080`.

**iOS push notifications** require `upstream-base-url: "https://ntfy.sh"` in `server.yml`. This lets ntfy.sh relay
the Apple push wake-up signal to your device; your self-hosted server then delivers the actual message content. If
notifications show "New message" instead of real text, the device received the wake-up but could not reach your server
— verify `base-url` is correct and reachable from the device.