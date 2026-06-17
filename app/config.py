from dataclasses import dataclass


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