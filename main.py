import atexit
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, request

import db
from jobs import check_weather_alerts, init_cooldowns, send_daily_report, send_quick_report
from notifier import NTFY_TOPIC
from weather import EASTERN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

app = Flask(__name__)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/history/reports")
def history_reports():
    report_type = request.args.get("type") or None
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except ValueError:
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400
    return jsonify(db.get_reports(report_type=report_type, limit=limit))


@app.route("/history/alerts")
def history_alerts():
    alert_type = request.args.get("type") or None
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except ValueError:
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400
    return jsonify(db.get_alerts(alert_type=alert_type, limit=limit))


@app.route("/report")
def report():
    try:
        message = send_quick_report()
        return jsonify({"status": "sent", "message": message})
    except Exception as e:
        log.exception("Quick report failed")
        return jsonify({"status": "error", "message": str(e)}), 500


def _startup() -> None:
    db.init_db()
    init_cooldowns()
    scheduler = BackgroundScheduler(timezone=EASTERN)
    scheduler.add_job(send_daily_report, "cron", hour=7, minute=0)
    scheduler.add_job(check_weather_alerts, "interval", minutes=30)
    scheduler.start()
    atexit.register(scheduler.shutdown)


if __name__ == "__main__":
    if not NTFY_TOPIC:
        raise SystemExit("NTFY_TOPIC environment variable is required — copy .env.example to .env and set it")

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    _startup()
    app.run(host=host, port=port, debug=debug, use_reloader=False)
