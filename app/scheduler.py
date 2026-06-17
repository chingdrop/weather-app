import logging

from apscheduler.schedulers.background import BackgroundScheduler

import app.state as state
from app.helpers import get_settings
from app.jobs import check_weather_alerts, prune_database, send_daily_report, send_evening_report

log = logging.getLogger(__name__)


def start_scheduler() -> None:
    if state.scheduler and state.scheduler.running:
        state.scheduler.shutdown(wait=False)

    settings = get_settings()
    state.scheduler = BackgroundScheduler()
    for monitor in state.monitors.values():
        state.scheduler.add_job(
            send_daily_report, "cron",
            hour=settings["daily_report_hour"], minute=0,
            args=[monitor], timezone=monitor.tz,
        )
        state.scheduler.add_job(
            send_evening_report, "cron",
            hour=settings["evening_report_hour"], minute=0,
            args=[monitor], timezone=monitor.tz,
        )
        state.scheduler.add_job(
            check_weather_alerts, "interval",
            minutes=settings["alert_interval_min"],
            args=[monitor],
        )
    state.scheduler.add_job(prune_database, "cron", hour=3, minute=0)
    state.scheduler.start()

    s = get_settings()
    log.warning(
        "Scheduler started — %d location(s), daily %02d:00, evening %02d:00, alerts every %d min",
        len(state.monitors), s["daily_report_hour"], s["evening_report_hour"], s["alert_interval_min"],
    )