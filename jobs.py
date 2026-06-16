import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

import db
from notifier import send_notification
from weather import EASTERN, RAIN_CODES, WMO, compass, fetch_rain_check_weather, fetch_report_weather

log = logging.getLogger(__name__)

RAIN_PROB_ALERT_PERCENT = float(os.environ.get("RAIN_PROB_ALERT_PERCENT", "50"))
RAIN_AMOUNT_ALERT_IN = float(os.environ.get("RAIN_AMOUNT_ALERT_IN", "0.05"))
WIND_GUST_ALERT_MPH = float(os.environ.get("WIND_GUST_ALERT_MPH", "30"))
HEAT_INDEX_ALERT_F = float(os.environ.get("HEAT_INDEX_ALERT_F", "100"))
DB_RETAIN_DAYS = int(os.environ.get("DB_RETAIN_DAYS", "30"))
API_FAILURE_NOTIFY_AFTER = int(os.environ.get("API_FAILURE_NOTIFY_AFTER", "3"))


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
    Adding a new alert type means adding one instance to _THRESHOLD_ALERTS below.
    """
    threshold: float = 0.0
    value_index: int = 0              # index into the hourly tuple
    current_key: str = ""             # key in data["current"] for the live reading
    summary_template: str = ""        # .format(peak=..., time_range=...)
    hourly_prefix: str = ""           # e.g. "Feels like " for heat/frost
    hourly_unit: str = ""             # e.g. " mph", "°F"
    exceeds: bool = True              # True: alert when value > threshold; False: when value < threshold
    last_peak: float | None = field(default=None)


_rain = RainAlertConfig(
    name="rain",
    title="Rain Alert",
    tags="rain_cloud",
    default_cooldown_secs=7200.0,
)

_wind_alert = ThresholdAlertConfig(
    name="wind",
    title="Wind Gust Alert",
    tags="wind_face",
    threshold=WIND_GUST_ALERT_MPH,
    value_index=4,
    current_key="wind_gusts_10m",
    default_cooldown_secs=14400.0,
    summary_template="Wind gusts up to {peak:.0f} mph{time_range}. Secure shade cloth, buckets, and lightweight gear.",
    hourly_unit=" mph",
)

_heat_alert = ThresholdAlertConfig(
    name="heat",
    title="Heat Risk Alert",
    tags="thermometer",
    threshold=HEAT_INDEX_ALERT_F,
    value_index=5,
    current_key="apparent_temperature",
    default_cooldown_secs=21600.0,
    summary_template="Heat risk high{time_range}. Feels-like temperature may reach {peak:.0f}°F.",
    hourly_prefix="Feels like ",
    hourly_unit="°F",
)

# Add new threshold-based alert types here. Rain is handled separately in check_weather_alerts
# because it uses multiple trigger conditions (probability, amount, WMO code) and tracks code changes.
_THRESHOLD_ALERTS: list[ThresholdAlertConfig] = [_wind_alert, _heat_alert]
_ALL_ALERTS: list[AlertConfig] = [_rain, *_THRESHOLD_ALERTS]

_api_failure_count: int = 0
_failure_notified: bool = False


def _on_api_success() -> None:
    global _api_failure_count, _failure_notified
    _api_failure_count = 0
    _failure_notified = False


def _on_api_failure(context: str) -> None:
    global _api_failure_count, _failure_notified
    _api_failure_count += 1
    log.exception("%s failed (consecutive failures: %d)", context, _api_failure_count)
    if _api_failure_count >= API_FAILURE_NOTIFY_AFTER and not _failure_notified:
        try:
            send_notification(
                f"Weather API has failed {_api_failure_count} times in a row. Check logs.",
                title="Weather App Error",
                tags="warning",
                priority="high",
            )
            _failure_notified = True
        except Exception:
            log.exception("Failed to send error notification")


def init_cooldowns() -> None:
    for alert in _ALL_ALERTS:
        alert.last_alert = db.get_last_alert_time(alert.name)


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

        h = data["hourly"]
        today = datetime.now(EASTERN).date()
        hourly_lines = []
        for i, t in enumerate(h["time"]):
            dt = datetime.fromisoformat(t).replace(tzinfo=EASTERN)
            if dt.date() != today or not (7 <= dt.hour <= 23):
                continue
            cond = WMO.get(int(h["weather_code"][i]), "Unknown")
            temp = h["temperature_2m"][i]
            rain = int(h["precipitation_probability"][i])
            time_str = dt.strftime("%I %p").lstrip("0")
            hourly_lines.append(f"{time_str:>6}  {cond}  {temp:.0f}°F  {rain}%")
        if hourly_lines:
            message += "\n\nHourly:\n" + "\n".join(hourly_lines)

        send_notification(message, title="Daily Weather Report", tags="sun_with_face")
        db.record_report("daily", message)
        _on_api_success()
        log.info("Daily report sent")
    except Exception:
        _on_api_failure("Daily report")


def check_weather_alerts() -> None:
    now = datetime.now(EASTERN)

    def _time_due(alert: AlertConfig) -> bool:
        return not alert.last_alert or (now - alert.last_alert).total_seconds() >= alert.cooldown_secs

    if not any(_time_due(a) for a in _ALL_ALERTS):
        return

    try:
        data = fetch_rain_check_weather()
        h = data["hourly"]
        c = data["current"]

        def _fmt(iso: str) -> str:
            return datetime.fromisoformat(iso).strftime("%I %p").lstrip("0")

        def _event_secs(rows: list, default: float) -> float:
            return max(
                (datetime.fromisoformat(rows[-1][0]).replace(tzinfo=EASTERN) - now).total_seconds()
                if rows else default,
                3600.0,
            )

        all_future = [
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
        ]
        upcoming = all_future[:3]

        # Rain — re-alert if cooldown expired OR the leading rain code changed
        rain_hours = [
            r for r in upcoming
            if r[1] >= RAIN_PROB_ALERT_PERCENT or r[2] >= RAIN_AMOUNT_ALERT_IN or r[3] in RAIN_CODES
        ]
        all_rain = [
            r for r in all_future
            if r[1] >= RAIN_PROB_ALERT_PERCENT or r[2] >= RAIN_AMOUNT_ALERT_IN or r[3] in RAIN_CODES
        ]
        current_rain_code = all_rain[0][3] if all_rain else None
        rain_code_changed = (
                bool(rain_hours) and _rain.last_code is not None and current_rain_code != _rain.last_code
        )
        if rain_hours and (_time_due(_rain) or rain_code_changed):
            start_time = _fmt(all_rain[0][0])
            end_time = _fmt(all_rain[-1][0])
            max_prob = max(r[1] for r in rain_hours)
            condition = WMO.get(rain_hours[0][3], "Rain")
            hourly = "\n".join(
                f"{_fmt(r[0]):>6}  {WMO.get(r[3], 'Rain')}  {r[1]:.0f}%"
                for r in all_rain
            )
            message = (
                f"Rain likely {start_time}–{end_time}. Outdoor work window is closing.\n"
                f"{condition} — up to {max_prob:.0f}% chance\n\n"
                f"{hourly}"
            )
            send_notification(message, title="Rain Alert", tags="rain_cloud", priority="high")
            db.record_alert("rain", message)
            _rain.cooldown_secs = _event_secs(all_rain, 7200.0)
            _rain.last_code = current_rain_code
            _rain.last_alert = now
            log.info("Rain alert sent")

        # Threshold alerts (wind, heat, etc.) — re-alert if cooldown expired OR conditions worsened
        for alert in _THRESHOLD_ALERTS:
            current_val = c[alert.current_key]
            hourly_vals = [r[alert.value_index] for r in upcoming]
            if alert.exceeds:
                peak = max(current_val, max(hourly_vals, default=0))
                triggered = peak >= alert.threshold
                worsened = alert.last_peak is not None and peak > alert.last_peak
                qualifying = [r for r in all_future if r[alert.value_index] >= alert.threshold]
            else:
                peak = min(current_val, min(hourly_vals, default=float("inf")))
                triggered = peak <= alert.threshold
                worsened = alert.last_peak is not None and peak < alert.last_peak
                qualifying = [r for r in all_future if r[alert.value_index] <= alert.threshold]

            time_due = not alert.last_alert or (now - alert.last_alert).total_seconds() >= alert.cooldown_secs

            if triggered and (time_due or worsened):
                time_range = f" from {_fmt(qualifying[0][0])} to {_fmt(qualifying[-1][0])}" if qualifying else ""
                hourly = "\n".join(
                    f"{_fmt(r[0]):>6}  {alert.hourly_prefix}{r[alert.value_index]:.0f}{alert.hourly_unit}"
                    for r in qualifying
                )
                message = alert.summary_template.format(peak=peak, time_range=time_range)
                if hourly:
                    message += f"\n\n{hourly}"
                send_notification(message, title=alert.title, tags=alert.tags, priority="high")
                db.record_alert(alert.name, message)
                alert.cooldown_secs = _event_secs(qualifying, alert.default_cooldown_secs)
                alert.last_peak = peak
                alert.last_alert = now
                log.info("%s sent", alert.title)

        _on_api_success()
    except Exception:
        _on_api_failure("Weather alert check")


def prune_database() -> None:
    try:
        reports, alerts = db.prune_old_records(DB_RETAIN_DAYS)
        log.info("Pruned %d reports and %d alerts older than %d days", reports, alerts, DB_RETAIN_DAYS)
    except Exception:
        log.exception("Database pruning failed")


# Intentionally lets exceptions propagate — the /report route handler catches them.
# send_daily_report and check_weather_alerts swallow exceptions because they run
# in the scheduler and a raised exception would silence future job runs.
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
    db.record_report("quick", message)
    return message
