import logging
import os
import threading
import time

from flask import Blueprint, jsonify, request

from app import db
from app.jobs import send_quick_report
from app.helpers import get_monitor
import app.state as state

api_bp = Blueprint("api", __name__)
log = logging.getLogger(__name__)


@api_bp.route("/health")
def health():
    return jsonify({"status": "ok"})


@api_bp.route("/history/reports")
def history_reports():
    location_name = request.args.get("location") or None
    report_type = request.args.get("type") or None
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except ValueError:
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400

    location_id = None
    if location_name:
        m = state.monitors.get(location_name)
        if m is None:
            return jsonify({"status": "error", "message": f"unknown location: {location_name}"}), 404
        location_id = m.location_id

    return jsonify(db.get_reports(location_id=location_id, report_type=report_type, limit=limit))


@api_bp.route("/history/alerts")
def history_alerts():
    location_name = request.args.get("location") or None
    alert_type = request.args.get("type") or None
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except ValueError:
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400

    location_id = None
    if location_name:
        m = state.monitors.get(location_name)
        if m is None:
            return jsonify({"status": "error", "message": f"unknown location: {location_name}"}), 404
        location_id = m.location_id

    return jsonify(db.get_alerts(location_id=location_id, alert_type=alert_type, limit=limit))


@api_bp.route("/report")
def report():
    location_name = request.args.get("location") or None
    monitor = get_monitor(location_name)
    if monitor is None:
        msg = "specify ?location=name" if len(state.monitors) > 1 else "no locations configured"
        return jsonify({"status": "error", "message": msg}), 400
    try:
        message = send_quick_report(monitor)
        return jsonify({"status": "sent", "message": message})
    except Exception as e:
        log.exception("Quick report failed")
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route("/restart", methods=["POST"])
def restart():
    def _exit():
        time.sleep(1)
        os._exit(0)
    threading.Thread(target=_exit, daemon=True).start()
    return jsonify({"status": "restarting"})