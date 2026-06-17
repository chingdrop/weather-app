from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import db
import app.state as state
from app.helpers import build_cfg, get_settings, parse_location_form

config_bp = Blueprint("config", __name__)


@config_bp.route("/config/locations")
def config_locations():
    locations = db.get_locations()
    return render_template("config/locations.html", locations=locations, title="Locations")


@config_bp.route("/config/locations/new", methods=["GET", "POST"])
def config_location_new():
    settings = get_settings()

    if request.method == "POST":
        try:
            fields = parse_location_form(request.form)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("config/location_form.html", loc=None, settings=settings, title="Add Location")

        if db.get_location_by_name(fields["name"]):
            flash(f"A location named '{fields['name']}' already exists.", "error")
            return render_template("config/location_form.html", loc=None, settings=settings, title="Add Location")

        db.upsert_location(**fields)
        flash(f"Location '{fields['name']}' added. Restart the app to activate it.", "success")
        return redirect(url_for("config.config_locations"))

    return render_template("config/location_form.html", loc=None, settings=settings, title="Add Location")


@config_bp.route("/config/locations/<name>", methods=["GET", "POST"])
def config_location_edit(name):
    loc = db.get_location_by_name(name)
    if loc is None:
        flash(f"Location '{name}' not found.", "error")
        return redirect(url_for("config.config_locations"))

    settings = get_settings()

    if request.method == "POST":
        try:
            fields = parse_location_form(request.form)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("config/location_form.html", loc=loc, settings=settings, title=f"Edit {name}")

        db.upsert_location(**fields)

        monitor = state.monitors.get(name)
        if monitor:
            updated = db.get_location_by_name(name)
            cfg = build_cfg(updated)
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
        return redirect(url_for("config.config_locations"))

    return render_template("config/location_form.html", loc=loc, settings=settings, title=f"Edit {name}")


@config_bp.route("/config/locations/<name>/delete", methods=["POST"])
def config_location_delete(name):
    loc = db.get_location_by_name(name)
    if loc is None:
        flash(f"Location '{name}' not found.", "error")
        return redirect(url_for("config.config_locations"))

    db.delete_location(loc.id)
    state.monitors.pop(name, None)
    flash(f"Location '{name}' deleted. Restart the app to update the scheduler.", "success")
    return redirect(url_for("config.config_locations"))


@config_bp.route("/config/settings", methods=["GET", "POST"])
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
            return render_template("config/settings.html", settings=get_settings(), title="Settings")

        for key, value in fields.items():
            db.set_setting(key, str(value))

        flash("Settings saved. Restart the app to apply scheduler changes.", "success")
        return redirect(url_for("config.config_settings"))

    return render_template("config/settings.html", settings=get_settings(), title="Settings")