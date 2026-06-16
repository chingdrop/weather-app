import atexit
import logging
import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify

from notifier import NTFY_TOPIC, send_notification
from weather import EASTERN, RAIN_CODES, WMO, compass, fetch_rain_check_weather, fetch_report_weather

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

RAIN_PROB_ALERT_PERCENT = float(os.environ.get("RAIN_PROB_ALERT_PERCENT", "50"))
RAIN_AMOUNT_ALERT_IN = float(os.environ.get("RAIN_AMOUNT_ALERT_IN", "0.05"))
WIND_GUST_ALERT_MPH = float(os.environ.get("WIND_GUST_ALERT_MPH", "30"))
HEAT_INDEX_ALERT_F = float(os.environ.get("HEAT_INDEX_ALERT_F", "100"))

_last_rain_alert: datetime | None = None
_last_wind_alert: datetime | None = None
_last_heat_alert: datetime | None = None


def send_daily_report() -> None:
    try:
        data = fetch_report_weather()
        d = data["daily"]
        condition = WMO.get(d["weather_code"][0], "Unknown")
        sunrise = datetime.fromisoformat(d["sunrise"][0]).strftime("%I:%M %p")
        sunset = datetime.fromisoformat(d["sunset"][0]).strftime("%I:%M %p")

        high = d["temperature_2m_max"][0]
        low = d["temperature_2m_min"][0]
        feels_like_max = d["apparent_temperature_max"][0]
        rain_chance = d["precipitation_probability_max"][0]
        rain_sum = d["rain_sum"][0]
        wind_gusts_max = d["wind_gusts_10m_max"][0]
        uv = d["uv_index_max"][0]

        tips = []
        if feels_like_max >= HEAT_INDEX_ALERT_F:
            tips.append("Heat risk high this afternoon")
        if rain_chance >= 60:
            tips.append("Storm/rain risk increases later today")
        elif rain_chance < 20 and feels_like_max < HEAT_INDEX_ALERT_F:
            tips.append("Best outdoor window: morning")
        if wind_gusts_max >= WIND_GUST_ALERT_MPH:
            tips.append(f"Wind gusts up to {wind_gusts_max:.0f} mph expected")

        message = (
            f"Good morning! Today in Sarasota:\n"
            f"{condition}\n"
            f"High: {high:.0f}°F  Low: {low:.0f}°F  Feels like: {feels_like_max:.0f}°F\n"
            f"Rain: {rain_chance:.0f}% chance, {rain_sum:.2f}\" possible\n"
            f"Wind gusts: up to {wind_gusts_max:.0f} mph\n"
            f"UV Index: {uv:.0f}\n"
            f"Sunrise: {sunrise}  Sunset: {sunset}"
        )
        if tips:
            message += "\n" + "\n".join(tips)

        send_notification(message, title="Daily Weather Report", tags="sun_with_face")
        log.info("Daily report sent")
    except Exception:
        log.exception("Daily report failed")


def check_weather_alerts() -> None:
    global _last_rain_alert, _last_wind_alert, _last_heat_alert

    now = datetime.now(EASTERN)
    rain_due = not _last_rain_alert or (now - _last_rain_alert).total_seconds() >= 7200
    wind_due = not _last_wind_alert or (now - _last_wind_alert).total_seconds() >= 14400
    heat_due = not _last_heat_alert or (now - _last_heat_alert).total_seconds() >= 21600

    if not (rain_due or wind_due or heat_due):
        return

    try:
        data = fetch_rain_check_weather()
        h = data["hourly"]
        c = data["current"]

        upcoming = [
            (
                h["time"][i],
                h["precipitation_probability"][i],
                h["rain"][i],
                int(h["weather_code"][i]),
                h["wind_gusts_10m"][i],
                h["apparent_temperature"][i],
            )
            for i in range(len(h["time"]))
            if datetime.fromisoformat(h["time"][i]).replace(tzinfo=EASTERN) > now
        ][:3]

        if rain_due:
            rain_hours = [
                r for r in upcoming
                if r[1] >= RAIN_PROB_ALERT_PERCENT or r[2] >= RAIN_AMOUNT_ALERT_IN or r[3] in RAIN_CODES
            ]
            if rain_hours:
                first_time = datetime.fromisoformat(rain_hours[0][0]).strftime("%I:%M %p")
                max_prob = max(r[1] for r in rain_hours)
                condition = WMO.get(rain_hours[0][3], "Rain")
                message = (
                    f"Rain likely around {first_time}. Outdoor work window is closing.\n"
                    f"{condition} — up to {max_prob:.0f}% chance in the next few hours"
                )
                send_notification(message, title="Rain Alert", tags="rain_cloud", priority="high")
                _last_rain_alert = now
                log.info("Rain alert sent")

        if wind_due:
            peak_gusts = max(c["wind_gusts_10m"], max((r[4] for r in upcoming), default=0))
            if peak_gusts >= WIND_GUST_ALERT_MPH:
                message = (
                    f"Wind gusts may reach {peak_gusts:.0f} mph. "
                    f"Secure shade cloth, buckets, and lightweight gear."
                )
                send_notification(message, title="Wind Gust Alert", tags="wind_face", priority="high")
                _last_wind_alert = now
                log.info("Wind alert sent")

        if heat_due:
            peak_heat = max(c["apparent_temperature"], max((r[5] for r in upcoming), default=0))
            if peak_heat >= HEAT_INDEX_ALERT_F:
                message = f"Heat risk high. Feels-like temperature may reach {peak_heat:.0f}°F."
                send_notification(message, title="Heat Risk Alert", tags="thermometer", priority="high")
                _last_heat_alert = now
                log.info("Heat alert sent")

    except Exception:
        log.exception("Weather alert check failed")


def send_quick_report() -> str:
    data = fetch_report_weather()
    c = data["current"]
    condition = WMO.get(c["weather_code"], "Unknown")

    message = (
        f"{condition}\n"
        f"Temp: {c['temperature_2m']:.0f}°F (feels like {c['apparent_temperature']:.0f}°F)\n"
        f"Humidity: {c['relative_humidity_2m']:.0f}%\n"
        f"Wind: {c['wind_speed_10m']:.0f} mph {compass(c['wind_direction_10m'])} "
        f"(gusts {c['wind_gusts_10m']:.0f} mph)\n"
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
    scheduler.add_job(check_weather_alerts, "interval", minutes=30)
    scheduler.start()
    atexit.register(scheduler.shutdown)
    app.run(host=host, port=port, debug=debug, use_reloader=False)