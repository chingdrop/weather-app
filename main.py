import openmeteo_requests
import pandas as pd
import requests_cache
from flask import Flask, jsonify
from retry_requests import retry

app = Flask(__name__)


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


@app.route("/weather")
def weather():
    return jsonify(get_weather_data())


if __name__ == '__main__':
    app.run(debug=True)
