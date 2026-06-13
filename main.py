import atexit
import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify

app = Flask(__name__)

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "weather-app")
LAT, LON = 27.0442, -82.2359
TIMEZONE = "America/New_York"
EASTERN = ZoneInfo(TIMEZONE)

RAIN_CODES = {51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99}

WMO = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Light rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Light snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Light showers", 81: "Moderate showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

_last_rain_alert: datetime | None = None


def _fetch(extra_params: dict) -> dict:
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": LAT,
            "longitude": LON,
            "timezone": TIMEZONE,
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            **extra_params,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _compass(degrees: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(degrees / 45) % 8]


def send_notification(message: str, title: str | None = None, priority: str | None = None, tags: str | None = None) -> None:
    headers = {}
    if title:
        headers["Title"] = title
    if priority:
        headers["Priority"] = priority
    if tags:
        headers["Tags"] = tags
    response = requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()


def send_daily_report() -> None:
    data = _fetch({
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


def check_rain_alert() -> None:
    global _last_rain_alert

    now = datetime.now(EASTERN)
    if _last_rain_alert and (now - _last_rain_alert).total_seconds() < 7200:
        return

    data = _fetch({
        "hourly": ["precipitation_probability", "precipitation", "weather_code"],
        "forecast_days": 1,
    })
    h = data["hourly"]

    # Filter to future hours only, look at next 3
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


def send_quick_report() -> str:
    data = _fetch({
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
        f"Wind: {c['wind_speed_10m']:.0f} mph {_compass(c['wind_direction_10m'])}\n"
        f"Precip: {c['precipitation']:.2f}\""
    )
    send_notification(message, title="Current Conditions", tags="partly_sunny")
    return message


@app.route("/report")
def report():
    return jsonify({"status": "sent", "message": send_quick_report()})


if __name__ == "__main__":
    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    scheduler.add_job(send_daily_report, "cron", hour=7, minute=0)
    scheduler.add_job(check_rain_alert, "interval", minutes=30)
    scheduler.start()
    atexit.register(scheduler.shutdown)
    app.run(debug=True, use_reloader=False)
