import os
import requests
import openmeteo_requests
import pandas as pd
import requests_cache
from datetime import datetime
from flask import Flask, jsonify
from retry_requests import retry

app = Flask(__name__)

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "weather-app")


def send_notification(message, title=None, priority=None, tags=None):
    headers = {}
    if title:
        headers["Title"] = title
    if priority:
        headers["Priority"] = priority
    if tags:
        headers["Tags"] = tags
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers=headers,
    )


def get_weather_data():
    cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
    retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
    openmeteo = openmeteo_requests.Client(session=retry_session)

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": 27.0442,
        "longitude": -82.2359,
        "hourly": ["temperature_2m", "relative_humidity_2m", "precipitation_probability", "wind_speed_10m",
                   "wind_direction_10m"],
        "timezone": "America/New_York",
        "wind_speed_unit": "mph",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
    }
    responses = openmeteo.weather_api(url, params=params)
    response = responses[0]

    hourly = response.Hourly()
    hourly_data = {
        "date": pd.date_range(
            start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=hourly.Interval()),
            inclusive="left"
        ).tz_convert(response.Timezone().decode()).strftime("%Y-%m-%dT%H:%M:%S%z").tolist(),
        "temperature_2m": hourly.Variables(0).ValuesAsNumpy().tolist(),
        "relative_humidity_2m": hourly.Variables(1).ValuesAsNumpy().tolist(),
        "precipitation_probability": hourly.Variables(2).ValuesAsNumpy().tolist(),
        "wind_speed_10m": hourly.Variables(3).ValuesAsNumpy().tolist(),
        "wind_direction_10m": hourly.Variables(4).ValuesAsNumpy().tolist(),
    }

    return {
        "meta": {
            "latitude": response.Latitude(),
            "longitude": response.Longitude(),
            "elevation": response.Elevation(),
            "timezone": response.Timezone().decode(),
        },
        "hourly": hourly_data,
    }


def current_hour_index(dates):
    parsed = [datetime.fromisoformat(d) for d in dates]
    now = datetime.now(tz=parsed[0].tzinfo)
    return min(range(len(parsed)), key=lambda i: abs((parsed[i] - now).total_seconds()))


@app.route("/weather")
def weather():
    return jsonify(get_weather_data())


@app.route("/notify")
def notify():
    data = get_weather_data()
    hourly = data["hourly"]
    idx = current_hour_index(hourly["date"])

    temp = hourly["temperature_2m"][idx]
    humidity = hourly["relative_humidity_2m"][idx]
    precip = hourly["precipitation_probability"][idx]
    wind = hourly["wind_speed_10m"][idx]

    message = (
        f"Temp: {temp:.1f}°F  |  Humidity: {humidity:.0f}%  |  "
        f"Rain: {precip:.0f}%  |  Wind: {wind:.1f} mph"
    )
    send_notification(message, title="Current Weather", tags="sunny")
    return jsonify({"status": "sent", "message": message})


if __name__ == '__main__':
    app.run(debug=True)
