import logging
import os
from datetime import datetime, timedelta

from app import db
from app.monitor import AlertConfig, LocationMonitor
from app.notifier import send_notification
from app.weather import RAIN_CODES, WMO, compass, fetch_rain_check_weather, fetch_report_weather

log = logging.getLogger(__name__)

DB_RETAIN_DAYS = int(os.environ.get("DB_RETAIN_DAYS", "30"))
API_FAILURE_NOTIFY_AFTER = int(os.environ.get("API_FAILURE_NOTIFY_AFTER", "3"))


def _on_api_success(monitor: LocationMonitor) -> None:
    monitor.api_failure_count = 0
    monitor.failure_notified = False


def _on_api_failure(monitor: LocationMonitor, context: str) -> None:
    monitor.api_failure_count += 1
    log.exception("%s failed for %s (consecutive failures: %d)", context, monitor.cfg.name, monitor.api_failure_count)
    threshold = int(db.get_setting("api_failure_notify_after") or API_FAILURE_NOTIFY_AFTER)
    if monitor.api_failure_count >= threshold and not monitor.failure_notified:
        try:
            send_notification(
                f"Weather API has failed {monitor.api_failure_count} times in a row. Check logs.",
                topic=monitor.cfg.ntfy_topic,
                title="Weather App Error",
                tags="warning",
                priority="high",
            )
            monitor.failure_notified = True
        except Exception:
            log.exception("Failed to send error notification for %s", monitor.cfg.name)


def _build_report_message(data: dict, day_offset: int, monitor: LocationMonitor) -> str:
    d = data["daily"]
    condition = WMO.get(d["weather_code"][day_offset], "Unknown")
    sunrise = datetime.fromisoformat(d["sunrise"][day_offset]).strftime("%I:%M %p")
    sunset = datetime.fromisoformat(d["sunset"][day_offset]).strftime("%I:%M %p")

    high = d["temperature_2m_max"][day_offset]
    low = d["temperature_2m_min"][day_offset]
    feels_like_max = d["apparent_temperature_max"][day_offset]
    rain_chance = d["precipitation_probability_max"][day_offset]
    rain_sum = d["rain_sum"][day_offset]
    wind_gusts_max = d["wind_gusts_10m_max"][day_offset]
    uv = d["uv_index_max"][day_offset]

    tips = []
    if feels_like_max >= monitor.threshold_alerts[1].threshold:  # heat
        tips.append("Heat risk high this afternoon" if day_offset == 0 else "Heat risk high tomorrow afternoon")
    if rain_chance >= 60:
        tips.append("Storm/rain risk increases later today" if day_offset == 0 else "Storm/rain risk high tomorrow")
    elif rain_chance < 20 and feels_like_max < monitor.threshold_alerts[1].threshold:
        tips.append("Best outdoor window: morning")
    if wind_gusts_max >= monitor.threshold_alerts[0].threshold:  # wind
        tips.append(f"Wind gusts up to {wind_gusts_max:.0f} mph expected")
    if uv >= monitor.uv_threshold:
        tips.append(f"High UV ({uv:.0f}) — sun protection recommended")

    greeting = "Good morning! Today" if day_offset == 0 else "Good evening! Tomorrow"
    message = (
        f"{greeting} in {monitor.cfg.name}:\n"
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
    report_date = datetime.now(monitor.tz).date() + timedelta(days=day_offset)
    hourly_lines = []
    for i, t in enumerate(h["time"]):
        dt = datetime.fromisoformat(t).replace(tzinfo=monitor.tz)
        if dt.date() != report_date or not (7 <= dt.hour <= 23):
            continue
        cond = WMO.get(int(h["weather_code"][i]), "Unknown")
        temp = h["temperature_2m"][i]
        rain = int(h["precipitation_probability"][i])
        time_str = dt.strftime("%I %p").lstrip("0")
        hourly_lines.append(f"{time_str:>6}  {cond}  {temp:.0f}°F  {rain}%")
    if hourly_lines:
        message += "\n\nHourly:\n" + "\n".join(hourly_lines)

    return message


def _send_report(monitor: LocationMonitor, day_offset: int, title: str, tags: str, report_type: str) -> None:
    try:
        data = fetch_report_weather(monitor.cfg.lat, monitor.cfg.lon, monitor.cfg.timezone)
        message = _build_report_message(data, day_offset, monitor)
        send_notification(message, topic=monitor.cfg.ntfy_topic, title=title, tags=tags)
        db.record_report(monitor.location_id, report_type, message)
        _on_api_success(monitor)
        log.info("%s sent for %s", title, monitor.cfg.name)
    except Exception:
        _on_api_failure(monitor, title)


def send_daily_report(monitor: LocationMonitor) -> None:
    _send_report(monitor, 0, "Daily Weather Report", "sun_with_face", "daily")


def send_evening_report(monitor: LocationMonitor) -> None:
    _send_report(monitor, 1, "Evening Weather Briefing", "night_with_stars", "evening")


def check_weather_alerts(monitor: LocationMonitor) -> None:
    now = datetime.now(monitor.tz)

    def _time_due(alert: AlertConfig) -> bool:
        return not alert.last_alert or (now - alert.last_alert).total_seconds() >= alert.cooldown_secs

    if not any(_time_due(a) for a in monitor.all_alerts):
        return

    try:
        data = fetch_rain_check_weather(monitor.cfg.lat, monitor.cfg.lon, monitor.cfg.timezone)
        h = data["hourly"]
        c = data["current"]

        def _fmt(iso: str) -> str:
            return datetime.fromisoformat(iso).strftime("%I %p").lstrip("0")

        def _event_secs(rows: list, default: float) -> float:
            return max(
                (datetime.fromisoformat(rows[-1][0]).replace(tzinfo=monitor.tz) - now).total_seconds()
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
            if datetime.fromisoformat(h["time"][i]).replace(tzinfo=monitor.tz) > now
        ]
        upcoming = all_future[:3]

        # Rain — re-alert if cooldown expired OR the leading rain code changed
        rain_hours = [
            r for r in upcoming
            if r[1] >= monitor.rain_prob or r[2] >= monitor.rain_amt or r[3] in RAIN_CODES
        ]
        all_rain = [
            r for r in all_future
            if r[1] >= monitor.rain_prob or r[2] >= monitor.rain_amt or r[3] in RAIN_CODES
        ]
        current_rain_code = all_rain[0][3] if all_rain else None
        rain_code_changed = (
                bool(rain_hours) and monitor.rain.last_code is not None and current_rain_code != monitor.rain.last_code
        )
        if rain_hours and (_time_due(monitor.rain) or rain_code_changed):
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
            send_notification(message, topic=monitor.cfg.ntfy_topic, title="Rain Alert", tags="rain_cloud",
                              priority="high")
            db.record_alert(monitor.location_id, "rain", message)
            monitor.rain.cooldown_secs = _event_secs(all_rain, 7200.0)
            monitor.rain.last_code = current_rain_code
            monitor.rain.last_alert = now
            log.info("Rain alert sent for %s", monitor.cfg.name)

        # Threshold alerts (wind, heat, frost, etc.) — re-alert if cooldown expired OR conditions worsened
        for alert in monitor.threshold_alerts:
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

            if triggered and (_time_due(alert) or worsened):
                time_range = f" from {_fmt(qualifying[0][0])} to {_fmt(qualifying[-1][0])}" if qualifying else ""
                hourly = "\n".join(
                    f"{_fmt(r[0]):>6}  {alert.hourly_prefix}{r[alert.value_index]:.0f}{alert.hourly_unit}"
                    for r in qualifying
                )
                message = alert.summary_template.format(peak=peak, time_range=time_range)
                if hourly:
                    message += f"\n\n{hourly}"
                send_notification(message, topic=monitor.cfg.ntfy_topic, title=alert.title, tags=alert.tags,
                                  priority="high")
                db.record_alert(monitor.location_id, alert.name, message)
                alert.cooldown_secs = _event_secs(qualifying, alert.default_cooldown_secs)
                alert.last_peak = peak
                alert.last_alert = now
                log.info("%s sent for %s", alert.title, monitor.cfg.name)

        _on_api_success(monitor)
    except Exception:
        _on_api_failure(monitor, "Weather alert check")


def prune_database() -> None:
    try:
        days = int(db.get_setting("db_retain_days") or DB_RETAIN_DAYS)
        reports, alerts = db.prune_old_records(days)
        log.info("Pruned %d reports and %d alerts older than %d days", reports, alerts, days)
    except Exception:
        log.exception("Database pruning failed")


# Intentionally lets exceptions propagate — the /report route handler catches them.
def send_quick_report(monitor: LocationMonitor) -> str:
    data = fetch_report_weather(monitor.cfg.lat, monitor.cfg.lon, monitor.cfg.timezone)
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
    send_notification(message, topic=monitor.cfg.ntfy_topic, title="Current Conditions", tags="partly_sunny")
    db.record_report(monitor.location_id, "quick", message)
    return message
