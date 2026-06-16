import atexit
import logging
import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

_dev = os.environ.get("FLASK_DEBUG", "0") == "1"

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, request

import db
from config import LOCATIONS_FILE, load_locations
from monitor import LocationMonitor, init_cooldowns
from jobs import (
    check_weather_alerts, prune_database, send_daily_report,
    send_evening_report, send_quick_report,
)

logging.basicConfig(
    level=logging.DEBUG if _dev else logging.WARNING,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

_monitors: dict[str, LocationMonitor] = {}


def _get_monitor(name: str | None) -> LocationMonitor | None:
    if not _monitors:
        return None
    if name:
        return _monitors.get(name)
    if len(_monitors) == 1:
        return next(iter(_monitors.values()))
    return None


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/history/reports")
def history_reports():
    location_name = request.args.get("location") or None
    report_type = request.args.get("type") or None
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except ValueError:
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400

    location_id = None
    if location_name:
        m = _monitors.get(location_name)
        if m is None:
            return jsonify({"status": "error", "message": f"unknown location: {location_name}"}), 404
        location_id = m.location_id

    return jsonify(db.get_reports(location_id=location_id, report_type=report_type, limit=limit))


@app.route("/history/alerts")
def history_alerts():
    location_name = request.args.get("location") or None
    alert_type = request.args.get("type") or None
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except ValueError:
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400

    location_id = None
    if location_name:
        m = _monitors.get(location_name)
        if m is None:
            return jsonify({"status": "error", "message": f"unknown location: {location_name}"}), 404
        location_id = m.location_id

    return jsonify(db.get_alerts(location_id=location_id, alert_type=alert_type, limit=limit))


@app.route("/report")
def report():
    location_name = request.args.get("location") or None
    monitor = _get_monitor(location_name)
    if monitor is None:
        msg = "specify ?location=name" if len(_monitors) > 1 else "no locations configured"
        return jsonify({"status": "error", "message": msg}), 400
    try:
        message = send_quick_report(monitor)
        return jsonify({"status": "sent", "message": message})
    except Exception as e:
        log.exception("Quick report failed")
        return jsonify({"status": "error", "message": str(e)}), 500


DAILY_REPORT_HOUR = int(os.environ.get("DAILY_REPORT_HOUR", "7"))
EVENING_REPORT_HOUR = int(os.environ.get("EVENING_REPORT_HOUR", "21"))
ALERT_INTERVAL_MIN = int(os.environ.get("ALERT_INTERVAL_MIN", "15"))


def _startup() -> None:
    mode = "development" if _dev else "production"
    log.warning("Starting weather-app [%s]", mode)
    db.init_db()

    try:
        locations = load_locations()
    except FileNotFoundError:
        raise SystemExit(f"Locations config not found at {LOCATIONS_FILE!r}. Create one from locations.json.example.")

    for cfg in locations:
        location_id = db.upsert_location(
            name=cfg.name,
            lat=cfg.lat,
            lon=cfg.lon,
            tz_name=cfg.timezone,
            ntfy_topic=cfg.ntfy_topic,
            rain_prob_alert_percent=cfg.rain_prob_alert_percent,
            rain_amount_alert_in=cfg.rain_amount_alert_in,
            wind_gust_alert_mph=cfg.wind_gust_alert_mph,
            heat_index_alert_f=cfg.heat_index_alert_f,
            frost_temp_alert_f=cfg.frost_temp_alert_f,
            uv_index_alert=cfg.uv_index_alert,
        )
        monitor = LocationMonitor.create(location_id, cfg)
        init_cooldowns(monitor)
        _monitors[cfg.name] = monitor
        log.warning("Loaded location: %s | DB id: %d | NTFY topic: %s", cfg.name, location_id, cfg.ntfy_topic)

    for monitor in _monitors.values():
        today = datetime.now(monitor.tz).date()
        last_daily = db.get_last_report_time(monitor.location_id, "daily")
        if last_daily is None or last_daily.astimezone(monitor.tz).date() < today:
            log.warning("No daily report for %s today — sending now", monitor.cfg.name)
            send_daily_report(monitor)

    scheduler = BackgroundScheduler()
    for monitor in _monitors.values():
        scheduler.add_job(
            send_daily_report, "cron",
            hour=DAILY_REPORT_HOUR, minute=0,
            args=[monitor], timezone=monitor.tz,
        )
        scheduler.add_job(
            send_evening_report, "cron",
            hour=EVENING_REPORT_HOUR, minute=0,
            args=[monitor], timezone=monitor.tz,
        )
        scheduler.add_job(
            check_weather_alerts, "interval",
            minutes=ALERT_INTERVAL_MIN,
            args=[monitor],
        )
    scheduler.add_job(prune_database, "cron", hour=3, minute=0)
    scheduler.start()
    atexit.register(scheduler.shutdown)
    log.warning(
        "Scheduler started — %d location(s), daily %02d:00, evening %02d:00, alerts every %d min, db prune at 03:00",
        len(_monitors), DAILY_REPORT_HOUR, EVENING_REPORT_HOUR, ALERT_INTERVAL_MIN,
    )


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    _startup()
    app.run(host=host, port=port, debug=debug, use_reloader=False)
