from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import db
import app.state as state
from app.helpers import build_cfg, get_settings, parse_location_form
from app.scheduler import start_scheduler
from app.jobs import send_daily_report
from app.monitor import LocationMonitor, init_cooldowns

setup_bp = Blueprint("setup", __name__)


@setup_bp.route("/setup", methods=["GET", "POST"])
def setup():
    if state.monitors:
        return redirect(url_for("config.config_locations"))

    settings = get_settings()

    if request.method == "POST":
        try:
            fields = parse_location_form(request.form)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("setup.html", settings=settings)

        location_id = db.upsert_location(**fields)
        loc = db.get_location_by_name(fields["name"])
        cfg = build_cfg(loc)
        monitor = LocationMonitor.create(location_id, cfg)
        init_cooldowns(monitor)
        state.monitors[fields["name"]] = monitor
        start_scheduler()
        send_daily_report(monitor)
        flash(f"Location '{fields['name']}' added. Weather app is running.", "success")
        return redirect(url_for("config.config_locations"))

    return render_template("setup.html", settings=settings)