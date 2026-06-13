import os
from typing import Any, cast
from zoneinfo import ZoneInfo

from adapter import RestAdapter, RestAdapterConfig

LAT = float(os.environ.get("LAT", "27.0442"))
LON = float(os.environ.get("LON", "-82.2359"))
TIMEZONE = os.environ.get("TIMEZONE", "America/New_York")
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

_weather_api = RestAdapter(RestAdapterConfig(base_url="https://api.open-meteo.com/v1/forecast"))


def fetch(extra_params: dict) -> dict[str, Any]:
    return cast(dict[str, Any], _weather_api.get(params={
        "latitude": LAT,
        "longitude": LON,
        "timezone": TIMEZONE,
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        **extra_params,
    }))


def compass(degrees: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(degrees / 45) % 8]
