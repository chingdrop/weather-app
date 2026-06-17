import logging
import os
from datetime import datetime

import db
import app.state as state
from app.helpers import build_cfg
from app.scheduler import start_scheduler
from jobs import send_daily_report
from monitor import LocationMonitor, init_cooldowns

_dev = os.environ.get("FLASK_DEBUG", "0") == "1"
log = logging.getLogger(__name__)


def startup() -> None:
    state.monitors.clear()
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
        state.monitors[loc.name] = monitor
        log.warning("Loaded location: %s | DB id: %d | NTFY topic: %s", loc.name, loc.id, loc.ntfy_topic)

    for monitor in state.monitors.values():
        today = datetime.now(monitor.tz).date()
        last_daily = db.get_last_report_time(monitor.location_id, "daily")
        if last_daily is None or last_daily.astimezone(monitor.tz).date() < today:
            log.warning("No daily report for %s today — sending now", monitor.cfg.name)
            send_daily_report(monitor)

    start_scheduler()