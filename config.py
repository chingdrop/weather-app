import json
import os
from dataclasses import dataclass

LOCATIONS_FILE = os.environ.get("LOCATIONS_FILE", "locations.json")


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


def load_locations() -> list[LocationConfig]:
    with open(LOCATIONS_FILE) as f:
        data = json.load(f)
    locations = []
    for entry in data:
        t = entry.get("thresholds", {})
        locations.append(LocationConfig(
            name=entry["name"],
            lat=float(entry["lat"]),
            lon=float(entry["lon"]),
            timezone=entry["timezone"],
            ntfy_topic=entry["ntfy_topic"],
            rain_prob_alert_percent=t.get("rain_prob_alert_percent"),
            rain_amount_alert_in=t.get("rain_amount_alert_in"),
            wind_gust_alert_mph=t.get("wind_gust_alert_mph"),
            heat_index_alert_f=t.get("heat_index_alert_f"),
            frost_temp_alert_f=t.get("frost_temp_alert_f"),
            uv_index_alert=t.get("uv_index_alert"),
        ))
    return locations
