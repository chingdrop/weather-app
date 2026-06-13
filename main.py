import atexit
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import certifi
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, jsonify
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
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

_last_rain_alert: datetime | None = None


@dataclass
class RestAdapterConfig:
    base_url: str
    timeout: float = 10.0
    retries: int = 3
    backoff_factor: float = 0.3
    headers: dict[str, str] = field(default_factory=dict)
    auth: Any = None
    proxies: dict[str, str] | None = None
    verify: bool | str = True


class RestAdapter:
    """
    A thin wrapper around `requests.Session` with:
      - automatic retries
      - content-type-aware response parsing
      - unified request method
      - optional verbose logging
    """

    def __init__(self, config: RestAdapterConfig, logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

        self.session = requests.Session()
        self.session.headers.update(config.headers)
        if config.auth:
            self.session.auth = config.auth
        if config.proxies:
            self.session.proxies.update(config.proxies)

        retry_strategy = Retry(
            total=config.retries,
            backoff_factor=config.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST", "PUT", "DELETE"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def request(
            self,
            method: str,
            endpoint: str,
            *,
            params: dict[str, Any] | None = None,
            data: bytes | dict[str, Any] | None = None,
            json: Any = None,
            headers: dict[str, str] | None = None,
            cookies: dict[str, str] | None = None,
            timeout: float | None = None,
            allow_redirects: bool = True,
    ) -> dict[str, Any] | str | bytes:
        """
        Make an HTTP request and return parsed JSON, text, or raw bytes.

        Raises:
            requests.HTTPError on 4xx/5xx (after retries).
        """
        url = urljoin(self.config.base_url, endpoint)
        req_headers = dict(self.session.headers)
        if headers:
            req_headers.update(headers)

        self.logger.debug(f"→ {method} {url} params={params} json={json or data}")
        resp = self.session.request(
            method=method,
            url=url,
            params=params,
            data=data,
            json=json,
            headers=req_headers,
            cookies=cookies,
            timeout=timeout or self.config.timeout,
            verify=certifi.where() if self.config.verify is True else self.config.verify,
            allow_redirects=allow_redirects,
        )
        resp.raise_for_status()
        self.logger.debug(f"← {resp.status_code} {resp.headers.get('Content-Type')}")

        ctype = resp.headers.get("Content-Type", "").lower()
        if "application/json" in ctype:
            return resp.json()
        if "text" in ctype or "html" in ctype:
            return resp.text
        return resp.content

    def get(self, endpoint: str = "", **kwargs) -> dict[str, Any] | str | bytes:
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint: str = "", **kwargs) -> dict[str, Any] | str | bytes:
        return self.request("POST", endpoint, **kwargs)

    def put(self, endpoint: str = "", **kwargs) -> dict[str, Any] | str | bytes:
        return self.request("PUT", endpoint, **kwargs)

    def delete(self, endpoint: str = "", **kwargs) -> dict[str, Any] | str | bytes:
        return self.request("DELETE", endpoint, **kwargs)


_weather_api = RestAdapter(RestAdapterConfig(base_url="https://api.open-meteo.com/v1/forecast"))
_ntfy_api = RestAdapter(RestAdapterConfig(base_url="https://ntfy.sh", retries=2))


def _fetch(extra_params: dict) -> dict[str, Any]:
    return cast(dict[str, Any], _weather_api.get(params={
        "latitude": LAT,
        "longitude": LON,
        "timezone": TIMEZONE,
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        **extra_params,
    }))


def _compass(degrees: float) -> str:
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(degrees / 45) % 8]


def send_notification(
        message: str,
        title: str | None = None,
        priority: str | None = None,
        tags: str | None = None,
) -> None:
    headers = {}
    if title:
        headers["Title"] = title
    if priority:
        headers["Priority"] = priority
    if tags:
        headers["Tags"] = tags
    _ntfy_api.post(f"/{NTFY_TOPIC}", data=message.encode("utf-8"), headers=headers)


def send_daily_report() -> None:
    try:
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
        log.info("Daily report sent")
    except Exception:
        log.exception("Daily report failed")


def check_rain_alert() -> None:
    global _last_rain_alert

    now = datetime.now(EASTERN)
    if _last_rain_alert and (now - _last_rain_alert).total_seconds() < 7200:
        return

    try:
        data = _fetch({
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

    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    scheduler.add_job(send_daily_report, "cron", hour=7, minute=0)
    scheduler.add_job(check_rain_alert, "interval", minutes=30)
    scheduler.start()
    atexit.register(scheduler.shutdown)
    app.run(host=host, port=port, debug=debug, use_reloader=False)
