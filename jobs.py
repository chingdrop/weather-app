import logging
import os
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

_last_rain_alert: datetime | None = None
_last_wind_alert: datetime | None = None
_last_heat_alert: datetime | None = None
_rain_cooldown_secs: float = 7200.0
_last_rain_code: int | None = None
_wind_cooldown_secs: float = 14400.0
_last_wind_peak: float = 0.0
_heat_cooldown_secs: float = 21600.0
_last_heat_peak: float = 0.0
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
    global _last_rain_alert, _last_wind_alert, _last_heat_alert
    _last_rain_alert = db.get_last_alert_time("rain")
    _last_wind_alert = db.get_last_alert_time("wind")
    _last_heat_alert = db.get_last_alert_time("heat")


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
    global _last_rain_alert, _last_wind_alert, _last_heat_alert
    global _rain_cooldown_secs, _last_rain_code, _wind_cooldown_secs, _last_wind_peak, _heat_cooldown_secs, _last_heat_peak

    now = datetime.now(EASTERN)
    rain_time_due = not _last_rain_alert or (now - _last_rain_alert).total_seconds() >= _rain_cooldown_secs
    wind_time_due = not _last_wind_alert or (now - _last_wind_alert).total_seconds() >= _wind_cooldown_secs
    heat_time_due = not _last_heat_alert or (now - _last_heat_alert).total_seconds() >= _heat_cooldown_secs

    if not (rain_time_due or wind_time_due or heat_time_due):
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
            bool(rain_hours) and _last_rain_code is not None and current_rain_code != _last_rain_code
        )
        if rain_hours and (rain_time_due or rain_code_changed):
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
            _rain_cooldown_secs = _event_secs(all_rain, 7200.0)
            _last_rain_code = current_rain_code
            _last_rain_alert = now
            log.info("Rain alert sent")

        # Wind — re-alert if cooldown expired OR gusts increased
        peak_gusts = max(c["wind_gusts_10m"], max((r[4] for r in upcoming), default=0))
        wind_hours = [r for r in all_future if r[4] >= WIND_GUST_ALERT_MPH]
        if peak_gusts >= WIND_GUST_ALERT_MPH and (wind_time_due or peak_gusts > _last_wind_peak):
            time_range = f" from {_fmt(wind_hours[0][0])} to {_fmt(wind_hours[-1][0])}" if wind_hours else ""
            hourly = "\n".join(f"{_fmt(r[0]):>6}  {r[4]:.0f} mph" for r in wind_hours)
            message = (
                f"Wind gusts up to {peak_gusts:.0f} mph{time_range}. "
                f"Secure shade cloth, buckets, and lightweight gear."
                + (f"\n\n{hourly}" if hourly else "")
            )
            send_notification(message, title="Wind Gust Alert", tags="wind_face", priority="high")
            db.record_alert("wind", message)
            _wind_cooldown_secs = _event_secs(wind_hours, 14400.0)
            _last_wind_peak = peak_gusts
            _last_wind_alert = now
            log.info("Wind alert sent")

        # Heat — re-alert if cooldown expired OR feels-like rose
        peak_heat = max(c["apparent_temperature"], max((r[5] for r in upcoming), default=0))
        heat_hours = [r for r in all_future if r[5] >= HEAT_INDEX_ALERT_F]
        if peak_heat >= HEAT_INDEX_ALERT_F and (heat_time_due or peak_heat > _last_heat_peak):
            time_range = f" from {_fmt(heat_hours[0][0])} to {_fmt(heat_hours[-1][0])}" if heat_hours else ""
            hourly = "\n".join(f"{_fmt(r[0]):>6}  Feels like {r[5]:.0f}°F" for r in heat_hours)
            message = (
                f"Heat risk high{time_range}. Feels-like temperature may reach {peak_heat:.0f}°F."
                + (f"\n\n{hourly}" if hourly else "")
            )
            send_notification(message, title="Heat Risk Alert", tags="thermometer", priority="high")
            db.record_alert("heat", message)
            _heat_cooldown_secs = _event_secs(heat_hours, 21600.0)
            _last_heat_peak = peak_heat
            _last_heat_alert = now
            log.info("Heat alert sent")

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
