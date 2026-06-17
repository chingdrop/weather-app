import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from dataclasses import dataclass

from app import db


@dataclass
class LocationConfig:
    name: str
    lat: float
    lon: float
    timezone: str
    ntfy_topic: str
    rain_prob_alert_percent: float | None = None
    rain_amount_alert_in: float | None = None
    wind_gust_alert_mph: float | None = None
    heat_index_alert_f: float | None = None
    frost_temp_alert_f: float | None = None
    uv_index_alert: int | None = None

log = logging.getLogger(__name__)

# Global threshold defaults — overridden per-location in locations.json
RAIN_PROB_ALERT_PERCENT = float(os.environ.get("RAIN_PROB_ALERT_PERCENT", "50"))
RAIN_AMOUNT_ALERT_IN = float(os.environ.get("RAIN_AMOUNT_ALERT_IN", "0.05"))
WIND_GUST_ALERT_MPH = float(os.environ.get("WIND_GUST_ALERT_MPH", "30"))
HEAT_INDEX_ALERT_F = float(os.environ.get("HEAT_INDEX_ALERT_F", "100"))
FROST_TEMP_ALERT_F = float(os.environ.get("FROST_TEMP_ALERT_F", "36"))
UV_INDEX_ALERT = int(os.environ.get("UV_INDEX_ALERT", "8"))


@dataclass
class AlertConfig:
    """Shared config and runtime state for all alert types."""
    name: str
    title: str
    tags: str
    default_cooldown_secs: float
    last_alert: datetime | None = field(default=None)
    cooldown_secs: float = field(init=False)

    def __post_init__(self) -> None:
        self.cooldown_secs = self.default_cooldown_secs


@dataclass
class RainAlertConfig(AlertConfig):
    last_code: int | None = field(default=None)


@dataclass
class ThresholdAlertConfig(AlertConfig):
    """Config and runtime state for a single numeric-threshold weather alert.

    Monitors one value from the hourly tuple:
      (time, precip_prob, rain, weather_code, wind_gusts, apparent_temp)

    Set exceeds=False for cold alerts (e.g. frost) where lower values are worse.
    Adding a new alert type means adding one instance in LocationMonitor.create().
    """
    threshold: float = 0.0
    value_index: int = 0  # index into the hourly tuple
    current_key: str = ""  # key in data["current"] for the live reading
    summary_template: str = ""  # .format(peak=..., time_range=...)
    hourly_prefix: str = ""  # e.g. "Feels like " for heat/frost
    hourly_unit: str = ""  # e.g. " mph", "°F"
    exceeds: bool = True  # True: alert when value > threshold; False: when value < threshold
    last_peak: float | None = field(default=None)


@dataclass
class LocationMonitor:
    """Per-location configuration and runtime alert state."""
    location_id: int
    cfg: LocationConfig
    tz: ZoneInfo
    rain: RainAlertConfig
    rain_prob: float
    rain_amt: float
    uv_threshold: int
    threshold_alerts: list[ThresholdAlertConfig]
    all_alerts: list[AlertConfig]
    api_failure_count: int = field(default=0)
    failure_notified: bool = field(default=False)

    @classmethod
    def create(cls, location_id: int, cfg: LocationConfig) -> "LocationMonitor":
        tz = ZoneInfo(cfg.timezone)

        def _t(val: float | int | None, default: float | int) -> float:
            return float(val) if val is not None else float(default)

        rain = RainAlertConfig(
            name="rain", title="Rain Alert", tags="rain_cloud", default_cooldown_secs=7200.0,
        )
        wind = ThresholdAlertConfig(
            name="wind", title="Wind Gust Alert", tags="wind_face",
            threshold=_t(cfg.wind_gust_alert_mph, WIND_GUST_ALERT_MPH),
            value_index=4, current_key="wind_gusts_10m",
            default_cooldown_secs=14400.0,
            summary_template="Wind gusts up to {peak:.0f} mph{time_range}. Secure shade cloth, buckets, and lightweight gear.",
            hourly_unit=" mph",
        )
        heat = ThresholdAlertConfig(
            name="heat", title="Heat Risk Alert", tags="thermometer",
            threshold=_t(cfg.heat_index_alert_f, HEAT_INDEX_ALERT_F),
            value_index=5, current_key="apparent_temperature",
            default_cooldown_secs=21600.0,
            summary_template="Heat risk high{time_range}. Feels-like temperature may reach {peak:.0f}°F.",
            hourly_prefix="Feels like ", hourly_unit="°F",
        )
        frost = ThresholdAlertConfig(
            name="frost", title="Frost Alert", tags="snowflake",
            threshold=_t(cfg.frost_temp_alert_f, FROST_TEMP_ALERT_F),
            value_index=5, current_key="apparent_temperature",
            default_cooldown_secs=21600.0,
            summary_template="Frost risk{time_range}. Feels-like temperature may drop to {peak:.0f}°F. Bring in sensitive plants.",
            hourly_prefix="Feels like ", hourly_unit="°F",
            exceeds=False,
        )

        threshold_alerts = [wind, heat, frost]
        return cls(
            location_id=location_id,
            cfg=cfg,
            tz=tz,
            rain=rain,
            rain_prob=_t(cfg.rain_prob_alert_percent, RAIN_PROB_ALERT_PERCENT),
            rain_amt=_t(cfg.rain_amount_alert_in, RAIN_AMOUNT_ALERT_IN),
            uv_threshold=int(_t(cfg.uv_index_alert, UV_INDEX_ALERT)),
            threshold_alerts=threshold_alerts,
            all_alerts=[rain, *threshold_alerts],
        )


def init_cooldowns(monitor: LocationMonitor) -> None:
    for alert in monitor.all_alerts:
        alert.last_alert = db.get_last_alert_time(monitor.location_id, alert.name)
