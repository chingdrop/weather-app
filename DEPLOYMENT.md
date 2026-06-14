# Deployment

Single-container Flask + APScheduler weather app, deployed with Docker Compose on a Debian/Ubuntu VM inside Proxmox.

## Prerequisites

### 1. Create a Debian/Ubuntu VM in Proxmox

Any small VM works. 1 vCPU and 512 MB RAM is sufficient.

### 2. Install Docker and Docker Compose

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # log out and back in after this
```

Docker Compose is included with modern Docker installs (`docker compose`).

### 3. Copy the project to the VM

```bash
# Option A — clone from git
git clone <your-repo-url> weather-app && cd weather-app

# Option B — copy files manually
scp -r . user@vm-ip:~/weather-app && cd ~/weather-app
```

## Configuration

```bash
cp .env.example .env
nano .env   # set NTFY_TOPIC, LAT, LON, TIMEZONE
```

`NTFY_TOPIC` is required. The app will refuse to start without it.

## Run

### Development

```bash
docker compose up -d --build
```

`docker-compose.override.yml` is picked up automatically. Services bind to `127.0.0.1` only, Flask debug mode is on, no restart policy.

### Production

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Adds `restart: unless-stopped`, healthchecks, ntfy exposed on all interfaces for LAN access, and safe env defaults (`FLASK_DEBUG=0`, `HOST=0.0.0.0`). All user-specific values (`NTFY_TOPIC`, `LAT`, `LON`, etc.) still come from `.env`.

## Common commands

| Task | Dev | Prod |
|---|---|---|
| View logs | `docker logs -f weather-app` | same |
| Restart | `docker compose restart weather-app` | add `-f` flags |
| Stop | `docker compose down` | add `-f` flags |
| Rebuild | `docker compose up -d --build` | add `-f` flags |
| Check health | `curl http://127.0.0.1:5000/health` | same |
| Trigger report | `curl http://127.0.0.1:5000/report` | same |

## Notes

**One instance only.** The app embeds APScheduler inside the Flask process. Do not run multiple replicas or workers — the daily report and alert jobs would fire multiple times.

**Network access.** The port is bound to `127.0.0.1:5000` by default, so it is only reachable from inside the VM. To expose it on your LAN or over Tailscale, either:
- Change the port binding in `docker-compose.yml` to `"5000:5000"`, or
- Put a reverse proxy (Caddy, nginx) in front of it on the same VM.

**Portability.** The image has no baked-in secrets. Moving to a new Proxmox host is: copy the project directory, copy `.env`, run `docker compose up -d --build`.

---

## Self-hosted ntfy with iPhone

The compose file runs a local ntfy container alongside the weather app. The weather app publishes internally over the Docker network; the iPhone subscribes over LAN or Tailscale.

```
weather-app ──► http://ntfy  (internal Docker network, port 80)
iPhone      ──► http://<vm-lan-ip>:8080  (LAN or Tailscale)
```

### 1. Configure ntfy

Edit `ntfy/etc/server.yml` and replace the placeholder IP:

```yaml
base-url: "http://192.168.1.100:8080"   # your Docker VM's LAN IP
```

This value must exactly match the **Default Server** URL you configure in the iPhone ntfy app.

### 2. Start the stack

```bash
docker compose up -d --build
```

Both services start. The weather app waits for ntfy to pass its healthcheck before starting.

### 3. Verify

```bash
# Check both containers are running
docker ps

# Check ntfy health
curl http://127.0.0.1:8080/v1/health

# Send a test notification from the VM
curl -d "test from self-hosted ntfy" http://127.0.0.1:8080/YOUR_TOPIC

# Trigger a weather report
curl http://127.0.0.1:5000/report
```

### 4. iPhone ntfy app setup

1. Open the ntfy app → **Settings** → **Default Server**.
2. Set it to the same URL as `base-url` in `ntfy/etc/server.yml`, e.g. `http://192.168.1.100:8080`.
3. Subscribe to the same topic used in `NTFY_TOPIC`.

### iOS push behavior

- **`upstream-base-url: "https://ntfy.sh"`** is required for instant iOS push. ntfy.sh relays the Apple Push Notification wake-up signal to your phone. The phone then fetches the actual message content from your self-hosted server using `base-url`.
- **If notifications show "New message"** instead of the real text: the phone received the wake-up from ntfy.sh but could not reach your self-hosted server to fetch the content. Check that `base-url` is correct and that the phone can reach the VM IP on port 8080.
- **Away from home:** LAN-only access stops working when the phone is off Wi-Fi. Use Tailscale, or later expose ntfy through HTTPS on a domain, for reliable remote access.