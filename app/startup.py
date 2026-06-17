import logging
import os
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app import db
from app.helpers import build_cfg, get_settings
from app.jobs import (
    check_weather_alerts, prune_database, send_daily_report,
    send_evening_report, send_quick_report,  # noqa: F401 — re-exported for patches
)
from app.monitor import LocationMonitor, init_cooldowns

_dev = os.environ.get("FLASK_DEBUG", "0") == "1"
log = logging.getLogger(__name__)

monitors: dict[str, LocationMonitor] = {}
scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)

    settings = get_settings()
    scheduler = BackgroundScheduler()
    for monitor in monitors.values():
        scheduler.add_job(
            send_daily_report, "cron",
            hour=settings["daily_report_hour"], minute=0,
            args=[monitor], timezone=monitor.tz,
        )
        scheduler.add_job(
            send_evening_report, "cron",
            hour=settings["evening_report_hour"], minute=0,
            args=[monitor], timezone=monitor.tz,
        )
        scheduler.add_job(
            check_weather_alerts, "interval",
            minutes=settings["alert_interval_min"],
            args=[monitor],
        )
    scheduler.add_job(prune_database, "cron", hour=3, minute=0)
    scheduler.start()

    s = get_settings()
    log.warning(
        "Scheduler started — %d location(s), daily %02d:00, evening %02d:00, alerts every %d min",
        len(monitors), s["daily_report_hour"], s["evening_report_hour"], s["alert_interval_min"],
    )


def startup() -> None:
    monitors.clear()
    mode = "development" if _dev else "production"
    log.warning("Starting weather-app [%s]", mode)
    db.init_db()

    locations = db.get_locations()
    if not locations:
        log.warning("No locations configured — open /setup to get started")
        return

    for loc in locations:
        cfg = build_cfg(loc)
        monitor = LocationMonitor.create(loc.id, cfg)
        init_cooldowns(monitor)
        monitors[loc.name] = monitor
        log.warning("Loaded location: %s | DB id: %d | NTFY topic: %s", loc.name, loc.id, loc.ntfy_topic)

    for monitor in monitors.values():
        today = datetime.now(monitor.tz).date()
        last_daily = db.get_last_report_time(monitor.location_id, "daily")
        if last_daily is None or last_daily.astimezone(monitor.tz).date() < today:
            log.warning("No daily report for %s today — sending now", monitor.cfg.name)
            send_daily_report(monitor)

    start_scheduler()