import atexit
import logging
import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify

from notifier import NTFY_TOPIC, send_notification
from weather import EASTERN, RAIN_CODES, WMO, compass, fetch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

_last_rain_alert: datetime | None = None


def send_daily_report() -> None:
    try:
        data = fetch({
            "daily": [
                "temperature_2m_max", "temperature_2m_min", "weather_code",
                "precipitation_sum", "precipitation_probability_max",
                "uv_index_max", "sunrise", "sunset",
            ]
        })
        d = data["daily"]
        condition = WMO.get(d["weather_code"][0], "Unknown")
        sunrise = datetime.fromisoformat(d["sunrise"][0]).strftime("%I:%M %p")
        sunset = datetime.fromisoformat(d["sunset"][0]).strftime("%I:%M %p")

        message = (
            f"Good morning! Today in Sarasota:\n"
            f"{condition}\n"
            f"High: {d['temperature_2m_max'][0]:.0f}°F  Low: {d['temperature_2m_min'][0]:.0f}°F\n"
            f"Rain: {d['precipitation_probability_max'][0]:.0f}% chance, {d['precipitation_sum'][0]:.2f}\" possible\n"
            f"UV Index: {d['uv_index_max'][0]:.0f}\n"
            f"Sunrise: {sunrise}  Sunset: {sunset}"
        )
        send_notification(message, title="Daily Weather Report", tags="sun_with_face")
        log.info("Daily report sent")
    except Exception:
        log.exception("Daily report failed")


def check_rain_alert() -> None:
    global _last_rain_alert

    now = datetime.now(EASTERN)
    if _last_rain_alert and (now - _last_rain_alert).total_seconds() < 7200:
        return

    try:
        data = fetch({
            "hourly": ["precipitation_probability", "precipitation", "weather_code"],
            "forecast_days": 1,
        })
        h = data["hourly"]

        upcoming = [
            (h["time"][i], h["precipitation_probability"][i], h["precipitation"][i], int(h["weather_code"][i]))
            for i in range(len(h["time"]))
            if datetime.fromisoformat(h["time"][i]).replace(tzinfo=EASTERN) > now
        ][:3]

        rain_hours = [row for row in upcoming if row[1] >= 50 or row[3] in RAIN_CODES]
        if not rain_hours:
            return

        first_time = datetime.fromisoformat(rain_hours[0][0]).strftime("%I:%M %p")
        max_prob = max(row[1] for row in rain_hours)
        condition = WMO.get(rain_hours[0][3], "Rain")

        message = (
            f"{condition} expected around {first_time}\n"
            f"Up to {max_prob:.0f}% chance in the next few hours"
        )
        send_notification(message, title="Rain Alert", tags="rain_cloud", priority="high")
        _last_rain_alert = now
        log.info("Rain alert sent")
    except Exception:
        log.exception("Rain alert check failed")


def send_quick_report() -> str:
    data = fetch({
        "current": [
            "temperature_2m", "apparent_temperature", "relative_humidity_2m",
            "weather_code", "wind_speed_10m", "wind_direction_10m", "precipitation",
        ]
    })
    c = data["current"]
    condition = WMO.get(c["weather_code"], "Unknown")

    message = (
        f"{condition}\n"
        f"Temp: {c['temperature_2m']:.0f}°F (feels like {c['apparent_temperature']:.0f}°F)\n"
        f"Humidity: {c['relative_humidity_2m']:.0f}%\n"
        f"Wind: {c['wind_speed_10m']:.0f} mph {compass(c['wind_direction_10m'])}\n"
        f"Precip: {c['precipitation']:.2f}\""
    )
    send_notification(message, title="Current Conditions", tags="partly_sunny")
    return message


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/report")
def report():
    try:
        message = send_quick_report()
        return jsonify({"status": "sent", "message": message})
    except Exception as e:
        log.exception("Quick report failed")
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    if not NTFY_TOPIC:
        raise SystemExit("NTFY_TOPIC environment variable is required — copy .env.example to .env and set it")

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    scheduler = BackgroundScheduler(timezone=EASTERN)
    scheduler.add_job(send_daily_report, "cron", hour=7, minute=0)
    scheduler.add_job(check_rain_alert, "interval", minutes=30)
    scheduler.start()
    atexit.register(scheduler.shutdown)
    app.run(host=host, port=port, debug=debug, use_reloader=False)