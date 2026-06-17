import atexit
import logging
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()

_dev = os.environ.get("FLASK_DEBUG", "0") == "1"

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

import db
from config import LocationConfig
from monitor import (
    FROST_TEMP_ALERT_F, HEAT_INDEX_ALERT_F, RAIN_AMOUNT_ALERT_IN,
    RAIN_PROB_ALERT_PERCENT, UV_INDEX_ALERT, WIND_GUST_ALERT_MPH,
    LocationMonitor, init_cooldowns,
)
from jobs import (
    API_FAILURE_NOTIFY_AFTER, DB_RETAIN_DAYS,
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
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

_monitors: dict[str, LocationMonitor] = {}
_scheduler: BackgroundScheduler | None = None

# Last-resort defaults (overridden by DB settings table)
DAILY_REPORT_HOUR = int(os.environ.get("DAILY_REPORT_HOUR", "7"))
EVENING_REPORT_HOUR = int(os.environ.get("EVENING_REPORT_HOUR", "21"))
ALERT_INTERVAL_MIN = int(os.environ.get("ALERT_INTERVAL_MIN", "15"))

atexit.register(lambda: _scheduler.shutdown(wait=False) if _scheduler and _scheduler.running else None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_settings() -> dict:
    """Return all app settings with effective values (DB → module default)."""
    def _s(key: str, default) -> str:
        return db.get_setting(key) or str(default)

    return {
        "daily_report_hour": int(_s("daily_report_hour", DAILY_REPORT_HOUR)),
        "evening_report_hour": int(_s("evening_report_hour", EVENING_REPORT_HOUR)),
        "alert_interval_min": int(_s("alert_interval_min", ALERT_INTERVAL_MIN)),
        "db_retain_days": int(_s("db_retain_days", DB_RETAIN_DAYS)),
        "api_failure_notify_after": int(_s("api_failure_notify_after", API_FAILURE_NOTIFY_AFTER)),
        "rain_prob_alert_percent": float(_s("rain_prob_alert_percent", RAIN_PROB_ALERT_PERCENT)),
        "rain_amount_alert_in": float(_s("rain_amount_alert_in", RAIN_AMOUNT_ALERT_IN)),
        "wind_gust_alert_mph": float(_s("wind_gust_alert_mph", WIND_GUST_ALERT_MPH)),
        "heat_index_alert_f": float(_s("heat_index_alert_f", HEAT_INDEX_ALERT_F)),
        "frost_temp_alert_f": float(_s("frost_temp_alert_f", FROST_TEMP_ALERT_F)),
        "uv_index_alert": int(_s("uv_index_alert", UV_INDEX_ALERT)),
    }


def _build_cfg(loc: db.Location) -> LocationConfig:
    """Build a LocationConfig from a DB Location, resolving per-location vs. global defaults."""
    settings = _get_settings()

    def _eff(loc_val, key: str, cast=float):
        return cast(loc_val) if loc_val is not None else cast(settings[key])

    return LocationConfig(
        name=loc.name,
        lat=loc.lat,
        lon=loc.lon,
        timezone=loc.timezone,
        ntfy_topic=loc.ntfy_topic,
        rain_prob_alert_percent=_eff(loc.rain_prob_alert_percent, "rain_prob_alert_percent"),
        rain_amount_alert_in=_eff(loc.rain_amount_alert_in, "rain_amount_alert_in"),
        wind_gust_alert_mph=_eff(loc.wind_gust_alert_mph, "wind_gust_alert_mph"),
        heat_index_alert_f=_eff(loc.heat_index_alert_f, "heat_index_alert_f"),
        frost_temp_alert_f=_eff(loc.frost_temp_alert_f, "frost_temp_alert_f"),
        uv_index_alert=_eff(loc.uv_index_alert, "uv_index_alert", cast=lambda x: int(float(x))),
    )


def _start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)

    settings = _get_settings()
    _scheduler = BackgroundScheduler()
    for monitor in _monitors.values():
        _scheduler.add_job(
            send_daily_report, "cron",
            hour=settings["daily_report_hour"], minute=0,
            args=[monitor], timezone=monitor.tz,
        )
        _scheduler.add_job(
            send_evening_report, "cron",
            hour=settings["evening_report_hour"], minute=0,
            args=[monitor], timezone=monitor.tz,
        )
        _scheduler.add_job(
            check_weather_alerts, "interval",
            minutes=settings["alert_interval_min"],
            args=[monitor],
        )
    _scheduler.add_job(prune_database, "cron", hour=3, minute=0)
    _scheduler.start()
    s = _get_settings()
    log.warning(
        "Scheduler started — %d location(s), daily %02d:00, evening %02d:00, alerts every %d min",
        len(_monitors), s["daily_report_hour"], s["evening_report_hour"], s["alert_interval_min"],
    )


def _get_monitor(name: str | None) -> LocationMonitor | None:
    if not _monitors:
        return None
    if name:
        return _monitors.get(name)
    if len(_monitors) == 1:
        return next(iter(_monitors.values()))
    return None


def _parse_location_form(form) -> dict:
    """Parse and validate location form fields. Raises ValueError on bad input."""
    name = form.get("name", "").strip()
    if not name:
        raise ValueError("Name is required.")

    try:
        lat = float(form["lat"])
        lon = float(form["lon"])
    except (KeyError, ValueError):
        raise ValueError("Latitude and longitude must be valid numbers.")
    if not (-90 <= lat <= 90):
        raise ValueError("Latitude must be between -90 and 90.")
    if not (-180 <= lon <= 180):
        raise ValueError("Longitude must be between -180 and 180.")

    timezone = form.get("timezone", "").strip()
    if not timezone:
        raise ValueError("Timezone is required.")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"Unknown timezone: {timezone!r}. Use an IANA name like America/New_York.")

    ntfy_topic = form.get("ntfy_topic", "").strip()
    if not ntfy_topic:
        raise ValueError("NTFY topic is required.")

    def _opt_float(key):
        v = form.get(key, "").strip()
        return float(v) if v else None

    def _opt_int(key):
        v = form.get(key, "").strip()
        return int(v) if v else None

    return {
        "name": name,
        "lat": lat,
        "lon": lon,
        "timezone": timezone,
        "ntfy_topic": ntfy_topic,
        "rain_prob_alert_percent": _opt_float("rain_prob_alert_percent"),
        "rain_amount_alert_in": _opt_float("rain_amount_alert_in"),
        "wind_gust_alert_mph": _opt_float("wind_gust_alert_mph"),
        "heat_index_alert_f": _opt_float("heat_index_alert_f"),
        "frost_temp_alert_f": _opt_float("frost_temp_alert_f"),
        "uv_index_alert": _opt_int("uv_index_alert"),
    }


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

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


@app.route("/restart", methods=["POST"])
def restart():
    def _exit():
        time.sleep(1)
        os._exit(0)
    threading.Thread(target=_exit, daemon=True).start()
    return jsonify({"status": "restarting"})


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

@app.route("/setup", methods=["GET", "POST"])
def setup():
    if _monitors:
        return redirect(url_for("config_locations"))

    settings = _get_settings()

    if request.method == "POST":
        try:
            fields = _parse_location_form(request.form)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("setup.html", settings=settings)

        location_id = db.upsert_location(**fields)
        loc = db.get_location_by_name(fields["name"])
        cfg = _build_cfg(loc)
        monitor = LocationMonitor.create(location_id, cfg)
        init_cooldowns(monitor)
        _monitors[fields["name"]] = monitor
        _start_scheduler()
        send_daily_report(monitor)
        flash(f"Location '{fields['name']}' added. Weather app is running.", "success")
        return redirect(url_for("config_locations"))

    return render_template("setup.html", settings=settings)


# ---------------------------------------------------------------------------
# Config — locations
# ---------------------------------------------------------------------------

@app.route("/config/locations")
def config_locations():
    locations = db.get_locations()
    return render_template("config/locations.html", locations=locations, title="Locations")


@app.route("/config/locations/new", methods=["GET", "POST"])
def config_location_new():
    settings = _get_settings()

    if request.method == "POST":
        try:
            fields = _parse_location_form(request.form)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("config/location_form.html", loc=None, settings=settings, title="Add Location")

        if db.get_location_by_name(fields["name"]):
            flash(f"A location named '{fields['name']}' already exists.", "error")
            return render_template("config/location_form.html", loc=None, settings=settings, title="Add Location")

        db.upsert_location(**fields)
        flash(f"Location '{fields['name']}' added. Restart the app to activate it.", "success")
        return redirect(url_for("config_locations"))

    return render_template("config/location_form.html", loc=None, settings=settings, title="Add Location")


@app.route("/config/locations/<name>", methods=["GET", "POST"])
def config_location_edit(name):
    loc = db.get_location_by_name(name)
    if loc is None:
        flash(f"Location '{name}' not found.", "error")
        return redirect(url_for("config_locations"))

    settings = _get_settings()

    if request.method == "POST":
        try:
            fields = _parse_location_form(request.form)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("config/location_form.html", loc=loc, settings=settings, title=f"Edit {name}")

        db.upsert_location(**fields)

        monitor = _monitors.get(name)
        if monitor:
            updated = db.get_location_by_name(name)
            cfg = _build_cfg(updated)
            monitor.cfg = cfg
            monitor.rain_prob = cfg.rain_prob_alert_percent
            monitor.rain_amt = cfg.rain_amount_alert_in
            monitor.uv_threshold = int(cfg.uv_index_alert)
            for alert in monitor.threshold_alerts:
                if alert.name == "wind":
                    alert.threshold = cfg.wind_gust_alert_mph
                elif alert.name == "heat":
                    alert.threshold = cfg.heat_index_alert_f
                elif alert.name == "frost":
                    alert.threshold = cfg.frost_temp_alert_f

        flash(f"Location '{name}' updated.", "success")
        return redirect(url_for("config_locations"))

    return render_template("config/location_form.html", loc=loc, settings=settings, title=f"Edit {name}")


@app.route("/config/locations/<name>/delete", methods=["POST"])
def config_location_delete(name):
    loc = db.get_location_by_name(name)
    if loc is None:
        flash(f"Location '{name}' not found.", "error")
        return redirect(url_for("config_locations"))

    db.delete_location(loc.id)
    _monitors.pop(name, None)
    flash(f"Location '{name}' deleted. Restart the app to update the scheduler.", "success")
    return redirect(url_for("config_locations"))


# ---------------------------------------------------------------------------
# Config — settings
# ---------------------------------------------------------------------------

@app.route("/config/settings", methods=["GET", "POST"])
def config_settings():
    if request.method == "POST":
        try:
            fields = {
                "daily_report_hour": int(request.form["daily_report_hour"]),
                "evening_report_hour": int(request.form["evening_report_hour"]),
                "alert_interval_min": int(request.form["alert_interval_min"]),
                "db_retain_days": int(request.form["db_retain_days"]),
                "api_failure_notify_after": int(request.form["api_failure_notify_after"]),
                "rain_prob_alert_percent": float(request.form["rain_prob_alert_percent"]),
                "rain_amount_alert_in": float(request.form["rain_amount_alert_in"]),
                "wind_gust_alert_mph": float(request.form["wind_gust_alert_mph"]),
                "heat_index_alert_f": float(request.form["heat_index_alert_f"]),
                "frost_temp_alert_f": float(request.form["frost_temp_alert_f"]),
                "uv_index_alert": int(request.form["uv_index_alert"]),
            }
        except (KeyError, ValueError) as e:
            flash(f"Invalid value: {e}", "error")
            return render_template("config/settings.html", settings=_get_settings(), title="Settings")

        for key, value in fields.items():
            db.set_setting(key, str(value))

        flash("Settings saved. Restart the app to apply scheduler changes.", "success")
        return redirect(url_for("config_settings"))

    return render_template("config/settings.html", settings=_get_settings(), title="Settings")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def _startup() -> None:
    _monitors.clear()
    mode = "development" if _dev else "production"
    log.warning("Starting weather-app [%s]", mode)
    db.init_db()

    locations = db.get_locations()
    if not locations:
        log.warning("No locations configured — open /setup to get started")
        return

    for loc in locations:
        cfg = _build_cfg(loc)
        monitor = LocationMonitor.create(loc.id, cfg)
        init_cooldowns(monitor)
        _monitors[loc.name] = monitor
        log.warning("Loaded location: %s | DB id: %d | NTFY topic: %s", loc.name, loc.id, loc.ntfy_topic)

    for monitor in _monitors.values():
        today = datetime.now(monitor.tz).date()
        last_daily = db.get_last_report_time(monitor.location_id, "daily")
        if last_daily is None or last_daily.astimezone(monitor.tz).date() < today:
            log.warning("No daily report for %s today — sending now", monitor.cfg.name)
            send_daily_report(monitor)

    _start_scheduler()


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    _startup()
    app.run(host=host, port=port, debug=debug, use_reloader=False)