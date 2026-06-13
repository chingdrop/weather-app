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

```bash
docker compose up -d --build
```

## Common commands

| Task | Command |
|---|---|
| View logs | `docker logs -f weather-app` |
| Restart | `docker compose restart weather-app` |
| Stop | `docker compose down` |
| Rebuild after code change | `docker compose up -d --build` |
| Check health | `curl http://127.0.0.1:5000/health` |
| Trigger report | `curl http://127.0.0.1:5000/report` |

## Notes

**One instance only.** The app embeds APScheduler inside the Flask process. Do not run multiple replicas or workers — the daily report and rain alert jobs would fire multiple times.

**Network access.** The port is bound to `127.0.0.1:5000` by default, so it is only reachable from inside the VM. To expose it on your LAN or over Tailscale, either:
- Change the port binding in `docker-compose.yml` to `"5000:5000"`, or
- Put a reverse proxy (Caddy, nginx) in front of it on the same VM.

**Portability.** The image has no baked-in secrets. Moving to a new Proxmox host is: copy the project directory, copy `.env`, run `docker compose up -d --build`.