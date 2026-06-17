import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import db
from app.config import LocationConfig
from app.jobs import API_FAILURE_NOTIFY_AFTER, DB_RETAIN_DAYS
from app.monitor import (
    FROST_TEMP_ALERT_F,
    HEAT_INDEX_ALERT_F,
    RAIN_AMOUNT_ALERT_IN,
    RAIN_PROB_ALERT_PERCENT,
    UV_INDEX_ALERT,
    WIND_GUST_ALERT_MPH,
    LocationMonitor,
)

import app.state as state

DAILY_REPORT_HOUR = int(os.environ.get("DAILY_REPORT_HOUR", "7"))
EVENING_REPORT_HOUR = int(os.environ.get("EVENING_REPORT_HOUR", "21"))
ALERT_INTERVAL_MIN = int(os.environ.get("ALERT_INTERVAL_MIN", "15"))


def get_settings() -> dict:
    def _s(key: str, default) -> str:
        return db.get_setting(key) or str(default)

    return {
        "daily_report_hour": int(_s("daily_report_hour", DAILY_REPORT_HOUR)),
        "evening_report_hour": int(_s("evening_report_hour", EVENING_REPORT_HOUR)),
        "alert_interval_min": int(_s("alert_interval_min", ALERT_INTERVAL_MIN)),
        "db_retain_days": int(_s("db_retain_days", DB_RETAIN_DAYS)),
        "api_failure_notify_after": int(_s("api_failure_notify_after", API_FAILURE_NOTIFY_AFTER)),
        "rain_prob_alert_percent": float(_s("rain_prob_alert_percent", RAIN_PROB_ALERT_PERCENT)),
        "rain_amount_alert_in": float(_s("rain_amount_alert_in", RAIN_AMOUNT_ALERT_IN)),
        "wind_gust_alert_mph": float(_s("wind_gust_alert_mph", WIND_GUST_ALERT_MPH)),
        "heat_index_alert_f": float(_s("heat_index_alert_f", HEAT_INDEX_ALERT_F)),
        "frost_temp_alert_f": float(_s("frost_temp_alert_f", FROST_TEMP_ALERT_F)),
        "uv_index_alert": int(_s("uv_index_alert", UV_INDEX_ALERT)),
    }


def build_cfg(loc: db.Location) -> LocationConfig:
    settings = get_settings()

    def _eff(loc_val, key: str, cast=float):
        return cast(loc_val) if loc_val is not None else cast(settings[key])

    return LocationConfig(
        name=loc.name,
        lat=loc.lat,
        lon=loc.lon,
        timezone=loc.timezone,
        ntfy_topic=loc.ntfy_topic,
        rain_prob_alert_percent=_eff(loc.rain_prob_alert_percent, "rain_prob_alert_percent"),
        rain_amount_alert_in=_eff(loc.rain_amount_alert_in, "rain_amount_alert_in"),
        wind_gust_alert_mph=_eff(loc.wind_gust_alert_mph, "wind_gust_alert_mph"),
        heat_index_alert_f=_eff(loc.heat_index_alert_f, "heat_index_alert_f"),
        frost_temp_alert_f=_eff(loc.frost_temp_alert_f, "frost_temp_alert_f"),
        uv_index_alert=_eff(loc.uv_index_alert, "uv_index_alert", cast=lambda x: int(float(x))),
    )


def get_monitor(name: str | None) -> LocationMonitor | None:
    if not state.monitors:
        return None
    if name:
        return state.monitors.get(name)
    if len(state.monitors) == 1:
        return next(iter(state.monitors.values()))
    return None


def parse_location_form(form) -> dict:
    name = form.get("name", "").strip()
    if not name:
        raise ValueError("Name is required.")

    try:
        lat = float(form["lat"])
        lon = float(form["lon"])
    except (KeyError, ValueError):
        raise ValueError("Latitude and longitude must be valid numbers.")
    if not (-90 <= lat <= 90):
        raise ValueError("Latitude must be between -90 and 90.")
    if not (-180 <= lon <= 180):
        raise ValueError("Longitude must be between -180 and 180.")

    timezone = form.get("timezone", "").strip()
    if not timezone:
        raise ValueError("Timezone is required.")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"Unknown timezone: {timezone!r}. Use an IANA name like America/New_York.")

    ntfy_topic = form.get("ntfy_topic", "").strip()
    if not ntfy_topic:
        raise ValueError("NTFY topic is required.")

    def _opt_float(key):
        v = form.get(key, "").strip()
        return float(v) if v else None

    def _opt_int(key):
        v = form.get(key, "").strip()
        return int(v) if v else None

    return {
        "name": name,
        "lat": lat,
        "lon": lon,
        "timezone": timezone,
        "ntfy_topic": ntfy_topic,
        "rain_prob_alert_percent": _opt_float("rain_prob_alert_percent"),
        "rain_amount_alert_in": _opt_float("rain_amount_alert_in"),
        "wind_gust_alert_mph": _opt_float("wind_gust_alert_mph"),
        "heat_index_alert_f": _opt_float("heat_index_alert_f"),
        "frost_temp_alert_f": _opt_float("frost_temp_alert_f"),
        "uv_index_alert": _opt_int("uv_index_alert"),
    }