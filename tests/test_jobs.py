from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

import db
import jobs
import monitor as monitor_module
from conftest import TEST_CFG

EASTERN = ZoneInfo("America/New_York")


def _future_times(count: int) -> list[str]:
    now = datetime.now(EASTERN)
    return [(now + timedelta(hours=i + 1)).strftime("%Y-%m-%dT%H:00") for i in range(count)]


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

REPORT_DATA = {
    "current": {
        "temperature_2m": 88.0,
        "apparent_temperature": 95.0,
        "relative_humidity_2m": 72.0,
        "weather_code": 2,
        "wind_speed_10m": 12.0,
        "wind_direction_10m": 180.0,
        "wind_gusts_10m": 18.0,
        "precipitation": 0.0,
    },
    "daily": {
        "weather_code": [2],
        "temperature_2m_max": [88.0],
        "temperature_2m_min": [75.0],
        "apparent_temperature_max": [95.0],
        "precipitation_probability_max": [40.0],
        "precipitation_sum": [0.50],
        "rain_sum": [0.50],
        "wind_gusts_10m_max": [22.0],
        "uv_index_max": [8.0],
        "sunrise": ["2026-06-12T06:23"],
        "sunset": ["2026-06-12T20:15"],
    },
    "hourly": {
        "time": [],
        "precipitation_probability": [],
        "rain": [],
        "temperature_2m": [],
        "apparent_temperature": [],
        "wind_gusts_10m": [],
        "weather_code": [],
    },
}

_SAFE_CURRENT = {
    "temperature_2m": 80.0,
    "apparent_temperature": 82.0,
    "precipitation": 0.0,
    "rain": 0.0,
    "weather_code": 2,
    "wind_speed_10m": 5.0,
    "wind_gusts_10m": 10.0,
}


def _alert_data(times, precip_prob, rain, weather_codes, gusts, apparent_temps):
    return {
        "current": _SAFE_CURRENT,
        "hourly": {
            "time": times,
            "precipitation_probability": precip_prob,
            "precipitation": rain,
            "rain": rain,
            "weather_code": weather_codes,
            "wind_gusts_10m": gusts,
            "apparent_temperature": apparent_temps,
        },
    }


# ---------------------------------------------------------------------------
# init_cooldowns
# ---------------------------------------------------------------------------

class TestInitCooldowns:
    def test_all_none_when_no_alerts_in_db(self, monitor):
        monitor_module.init_cooldowns(monitor)
        assert monitor.rain.last_alert is None
        for alert in monitor.threshold_alerts:
            assert alert.last_alert is None

    def test_seeds_rain_from_db(self, monitor):
        db.record_alert(monitor.location_id, "rain", "a rain alert")
        monitor_module.init_cooldowns(monitor)
        assert monitor.rain.last_alert is not None
        assert monitor.threshold_alerts[0].last_alert is None  # wind still None

    def test_seeds_all_types(self, monitor):
        for name in ("rain", "wind", "heat", "frost"):
            db.record_alert(monitor.location_id, name, name)
        monitor_module.init_cooldowns(monitor)
        assert monitor.rain.last_alert is not None
        for alert in monitor.threshold_alerts:
            assert alert.last_alert is not None


# ---------------------------------------------------------------------------
# send_quick_report
# ---------------------------------------------------------------------------

class TestSendQuickReport:
    def test_message_contains_conditions(self, monitor):
        with patch("jobs.fetch_report_weather", return_value=REPORT_DATA), \
                patch("jobs.send_notification"):
            result = jobs.send_quick_report(monitor)
        assert "Partly cloudy" in result
        assert "88°F" in result
        assert "95°F" in result
        assert "72%" in result
        assert "12 mph S" in result
        assert "gusts 18 mph" in result

    def test_sends_notification_with_correct_title(self, monitor):
        with patch("jobs.fetch_report_weather", return_value=REPORT_DATA), \
                patch("jobs.send_notification") as mock_notify:
            jobs.send_quick_report(monitor)
        assert mock_notify.call_args.kwargs["title"] == "Current Conditions"
        assert mock_notify.call_args.kwargs["topic"] == TEST_CFG.ntfy_topic


# ---------------------------------------------------------------------------
# send_daily_report
# ---------------------------------------------------------------------------

class TestSendDailyReport:
    def test_message_contains_key_fields(self, monitor):
        with patch("jobs.fetch_report_weather", return_value=REPORT_DATA), \
                patch("jobs.send_notification") as mock_notify:
            jobs.send_daily_report(monitor)
        message = mock_notify.call_args[0][0]
        assert "88°F" in message
        assert "75°F" in message
        assert "95°F" in message
        assert "40%" in message
        assert "22 mph" in message
        assert "06:23 AM" in message
        assert "08:15 PM" in message

    def test_logs_and_swallows_api_error(self, monitor):
        with patch("jobs.fetch_report_weather", side_effect=Exception("API down")), \
                patch("jobs.send_notification"):
            jobs.send_daily_report(monitor)  # must not raise

    def test_hourly_section_appears_in_message(self, monitor):
        from datetime import date
        today = date.today()
        times = [f"{today}T{h:02d}:00" for h in range(7, 24)]
        data = {
            **REPORT_DATA,
            "hourly": {
                "time": times,
                "precipitation_probability": [10.0] * len(times),
                "rain": [0.0] * len(times),
                "temperature_2m": [85.0] * len(times),
                "apparent_temperature": [88.0] * len(times),
                "wind_gusts_10m": [12.0] * len(times),
                "weather_code": [2] * len(times),
            },
        }
        with patch("jobs.fetch_report_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.send_daily_report(monitor)
        message = mock_notify.call_args[0][0]
        assert "Hourly:" in message
        assert "85°F" in message

    def test_no_hourly_section_when_no_data(self, monitor):
        with patch("jobs.fetch_report_weather", return_value=REPORT_DATA), \
                patch("jobs.send_notification") as mock_notify:
            jobs.send_daily_report(monitor)
        assert "Hourly:" not in mock_notify.call_args[0][0]

    def test_uv_tip_appears_when_index_at_threshold(self, monitor):
        with patch("jobs.fetch_report_weather", return_value=REPORT_DATA), \
                patch("jobs.send_notification") as mock_notify:
            jobs.send_daily_report(monitor)
        assert "sun protection" in mock_notify.call_args[0][0]

    def test_no_uv_tip_when_index_below_threshold(self, monitor):
        data = {**REPORT_DATA, "daily": {**REPORT_DATA["daily"], "uv_index_max": [3.0]}}
        with patch("jobs.fetch_report_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.send_daily_report(monitor)
        assert "sun protection" not in mock_notify.call_args[0][0]


# ---------------------------------------------------------------------------
# send_evening_report
# ---------------------------------------------------------------------------

class TestSendEveningReport:
    def _data(self):
        from datetime import date, timedelta as td
        tomorrow = date.today() + td(days=1)
        times = [f"{tomorrow}T{h:02d}:00" for h in range(7, 24)]
        return {
            "daily": {
                "weather_code": [2, 3],
                "temperature_2m_max": [88.0, 91.0],
                "temperature_2m_min": [75.0, 78.0],
                "apparent_temperature_max": [95.0, 97.0],
                "precipitation_probability_max": [40.0, 25.0],
                "precipitation_sum": [0.5, 0.2],
                "rain_sum": [0.5, 0.2],
                "wind_gusts_10m_max": [22.0, 18.0],
                "uv_index_max": [8.0, 7.0],
                "sunrise": ["2026-06-16T06:23", "2026-06-17T06:24"],
                "sunset": ["2026-06-16T20:15", "2026-06-17T20:14"],
            },
            "hourly": {
                "time": times,
                "precipitation_probability": [15.0] * len(times),
                "rain": [0.0] * len(times),
                "temperature_2m": [89.0] * len(times),
                "apparent_temperature": [92.0] * len(times),
                "wind_gusts_10m": [15.0] * len(times),
                "weather_code": [3] * len(times),
            },
        }

    def test_message_contains_tomorrow_values(self, monitor):
        with patch("jobs.fetch_report_weather", return_value=self._data()), \
                patch("jobs.send_notification") as mock_notify:
            jobs.send_evening_report(monitor)
        message = mock_notify.call_args[0][0]
        assert "91°F" in message
        assert "78°F" in message
        assert "25%" in message

    def test_sends_with_correct_title(self, monitor):
        with patch("jobs.fetch_report_weather", return_value=self._data()), \
                patch("jobs.send_notification") as mock_notify:
            jobs.send_evening_report(monitor)
        assert mock_notify.call_args.kwargs["title"] == "Evening Weather Briefing"

    def test_hourly_shows_tomorrow(self, monitor):
        with patch("jobs.fetch_report_weather", return_value=self._data()), \
                patch("jobs.send_notification") as mock_notify:
            jobs.send_evening_report(monitor)
        assert "Hourly:" in mock_notify.call_args[0][0]

    def test_swallows_api_error(self, monitor):
        with patch("jobs.fetch_report_weather", side_effect=Exception("API down")), \
                patch("jobs.send_notification"):
            jobs.send_evening_report(monitor)  # must not raise


# ---------------------------------------------------------------------------
# check_weather_alerts — rain
# ---------------------------------------------------------------------------

class TestRainAlert:
    def test_sends_alert_when_rain_expected(self, monitor):
        times = _future_times(2)
        data = _alert_data(times, [75.0, 80.0], [0.1, 0.2], [61, 63], [15.0, 18.0], [82.0, 83.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Rain Alert" in titles

    def test_rain_alert_is_high_priority(self, monitor):
        times = _future_times(1)
        data = _alert_data(times, [80.0], [0.1], [61], [15.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        rain_call = next(c for c in mock_notify.call_args_list if c.kwargs.get("title") == "Rain Alert")
        assert rain_call.kwargs["priority"] == "high"

    def test_no_alert_when_no_rain(self, monitor):
        times = _future_times(2)
        data = _alert_data(times, [10.0, 5.0], [0.0, 0.0], [0, 1], [10.0, 12.0], [82.0, 83.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Rain Alert" not in titles

    def test_rain_cooldown_suppresses_alert(self, monitor):
        monitor.rain.last_alert = datetime.now(EASTERN)
        monitor.rain.last_code = 61
        times = _future_times(1)
        data = _alert_data(times, [80.0], [0.1], [61], [10.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Rain Alert" not in titles

    def test_sets_rain_cooldown_after_alert(self, monitor):
        times = _future_times(1)
        data = _alert_data(times, [80.0], [0.1], [61], [10.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification"):
            jobs.check_weather_alerts(monitor)
        assert monitor.rain.last_alert is not None

    def test_rain_resends_when_code_changes_during_cooldown(self, monitor):
        monitor.rain.last_alert = datetime.now(EASTERN)
        monitor.rain.last_code = 61
        times = _future_times(1)
        data = _alert_data(times, [80.0], [0.1], [95], [10.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Rain Alert" in titles

    def test_rain_cooldown_holds_when_code_same(self, monitor):
        monitor.rain.last_alert = datetime.now(EASTERN)
        monitor.rain.last_code = 61
        times = _future_times(1)
        data = _alert_data(times, [80.0], [0.1], [61], [10.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Rain Alert" not in titles

    def test_rain_alert_includes_start_and_end_times(self, monitor):
        times = _future_times(3)
        data = _alert_data(times, [80.0, 75.0, 60.0], [0.1, 0.2, 0.1], [61, 63, 61], [10.0, 10.0, 10.0], [82.0, 82.0, 82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        rain_call = next(c for c in mock_notify.call_args_list if c.kwargs.get("title") == "Rain Alert")
        assert "–" in rain_call.args[0]


# ---------------------------------------------------------------------------
# check_weather_alerts — wind
# ---------------------------------------------------------------------------

class TestWindAlert:
    def test_sends_alert_when_gusts_exceed_threshold(self, monitor):
        times = _future_times(2)
        data = _alert_data(times, [5.0, 5.0], [0.0, 0.0], [0, 0], [35.0, 38.0], [82.0, 83.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" in titles

    def test_sends_alert_on_current_gusts(self, monitor):
        data = {
            "current": {**_SAFE_CURRENT, "wind_gusts_10m": 35.0},
            "hourly": {
                "time": [], "precipitation_probability": [], "precipitation": [],
                "rain": [], "weather_code": [], "wind_gusts_10m": [], "apparent_temperature": [],
            },
        }
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" in titles

    def test_no_alert_below_threshold(self, monitor):
        times = _future_times(2)
        data = _alert_data(times, [5.0, 5.0], [0.0, 0.0], [0, 0], [10.0, 12.0], [82.0, 83.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" not in titles

    def test_wind_cooldown_suppresses_alert(self, monitor):
        wind = next(a for a in monitor.threshold_alerts if a.name == "wind")
        wind.last_alert = datetime.now(EASTERN)
        wind.last_peak = 38.0
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [38.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" not in titles

    def test_sets_wind_cooldown_after_alert(self, monitor):
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [38.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification"):
            jobs.check_weather_alerts(monitor)
        wind = next(a for a in monitor.threshold_alerts if a.name == "wind")
        assert wind.last_alert is not None

    def test_wind_resends_when_gusts_increase_during_cooldown(self, monitor):
        wind = next(a for a in monitor.threshold_alerts if a.name == "wind")
        wind.last_alert = datetime.now(EASTERN)
        wind.last_peak = 32.0
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [40.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" in titles

    def test_wind_cooldown_holds_when_gusts_same(self, monitor):
        wind = next(a for a in monitor.threshold_alerts if a.name == "wind")
        wind.last_alert = datetime.now(EASTERN)
        wind.last_peak = 38.0
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [38.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" not in titles

    def test_wind_alert_includes_time_range(self, monitor):
        times = _future_times(3)
        data = _alert_data(times, [5.0, 5.0, 5.0], [0.0, 0.0, 0.0], [0, 0, 0], [35.0, 38.0, 32.0], [82.0, 82.0, 82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        wind_call = next(c for c in mock_notify.call_args_list if c.kwargs.get("title") == "Wind Gust Alert")
        assert "from" in wind_call.args[0]
        assert "to" in wind_call.args[0]


# ---------------------------------------------------------------------------
# check_weather_alerts — heat
# ---------------------------------------------------------------------------

class TestHeatAlert:
    def test_sends_alert_when_heat_exceeds_threshold(self, monitor):
        times = _future_times(2)
        data = _alert_data(times, [5.0, 5.0], [0.0, 0.0], [0, 0], [10.0, 12.0], [103.0, 105.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Heat Risk Alert" in titles

    def test_sends_alert_on_current_heat(self, monitor):
        data = {
            "current": {**_SAFE_CURRENT, "apparent_temperature": 105.0},
            "hourly": {
                "time": [], "precipitation_probability": [], "precipitation": [],
                "rain": [], "weather_code": [], "wind_gusts_10m": [], "apparent_temperature": [],
            },
        }
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Heat Risk Alert" in titles

    def test_no_alert_below_threshold(self, monitor):
        times = _future_times(2)
        data = _alert_data(times, [5.0, 5.0], [0.0, 0.0], [0, 0], [10.0, 12.0], [82.0, 85.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Heat Risk Alert" not in titles

    def test_heat_cooldown_suppresses_alert(self, monitor):
        heat = next(a for a in monitor.threshold_alerts if a.name == "heat")
        heat.last_alert = datetime.now(EASTERN)
        heat.last_peak = 105.0
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [10.0], [105.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Heat Risk Alert" not in titles

    def test_heat_resends_when_temperature_rises_during_cooldown(self, monitor):
        heat = next(a for a in monitor.threshold_alerts if a.name == "heat")
        heat.last_alert = datetime.now(EASTERN)
        heat.last_peak = 102.0
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [10.0], [107.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Heat Risk Alert" in titles

    def test_heat_alert_includes_time_range(self, monitor):
        times = _future_times(3)
        data = _alert_data(times, [5.0, 5.0, 5.0], [0.0, 0.0, 0.0], [0, 0, 0], [10.0, 10.0, 10.0], [103.0, 106.0, 101.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        heat_call = next(c for c in mock_notify.call_args_list if c.kwargs.get("title") == "Heat Risk Alert")
        assert "from" in heat_call.args[0]
        assert "to" in heat_call.args[0]


# ---------------------------------------------------------------------------
# check_weather_alerts — frost
# ---------------------------------------------------------------------------

class TestFrostAlert:
    def test_sends_alert_when_temperature_below_threshold(self, monitor):
        times = _future_times(2)
        data = _alert_data(times, [5.0, 5.0], [0.0, 0.0], [0, 0], [10.0, 12.0], [30.0, 28.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Frost Alert" in titles

    def test_no_alert_above_threshold(self, monitor):
        times = _future_times(2)
        data = _alert_data(times, [5.0, 5.0], [0.0, 0.0], [0, 0], [10.0, 12.0], [50.0, 55.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Frost Alert" not in titles

    def test_frost_cooldown_suppresses_alert(self, monitor):
        frost = next(a for a in monitor.threshold_alerts if a.name == "frost")
        frost.last_alert = datetime.now(EASTERN)
        frost.last_peak = 30.0
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [10.0], [30.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Frost Alert" not in titles

    def test_frost_resends_when_temperature_drops_further(self, monitor):
        frost = next(a for a in monitor.threshold_alerts if a.name == "frost")
        frost.last_alert = datetime.now(EASTERN)
        frost.last_peak = 34.0
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [10.0], [28.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Frost Alert" in titles

    def test_frost_alert_includes_time_range(self, monitor):
        times = _future_times(3)
        data = _alert_data(times, [5.0, 5.0, 5.0], [0.0, 0.0, 0.0], [0, 0, 0], [10.0, 10.0, 10.0], [34.0, 30.0, 32.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts(monitor)
        frost_call = next(c for c in mock_notify.call_args_list if c.kwargs.get("title") == "Frost Alert")
        assert "from" in frost_call.args[0]
        assert "to" in frost_call.args[0]


# ---------------------------------------------------------------------------
# check_weather_alerts — combined cooldown skip
# ---------------------------------------------------------------------------

class TestAlertCooldownSkip:
    def test_skips_fetch_when_all_cooldowns_active(self, monitor):
        now = datetime.now(EASTERN)
        for alert in monitor.all_alerts:
            alert.last_alert = now
        with patch("jobs.fetch_rain_check_weather") as mock_fetch:
            jobs.check_weather_alerts(monitor)
        mock_fetch.assert_not_called()

    def test_logs_and_swallows_api_error(self, monitor):
        with patch("jobs.fetch_rain_check_weather", side_effect=Exception("timeout")), \
                patch("jobs.send_notification"):
            jobs.check_weather_alerts(monitor)  # must not raise


# ---------------------------------------------------------------------------
# API failure notifications
# ---------------------------------------------------------------------------

class TestApiFailureNotification:
    def test_notifies_after_threshold(self, monitor):
        with patch("jobs.fetch_report_weather", side_effect=Exception("API down")), \
                patch("jobs.send_notification") as mock_notify:
            for _ in range(jobs.API_FAILURE_NOTIFY_AFTER):
                jobs.send_daily_report(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Weather App Error" in titles

    def test_does_not_notify_before_threshold(self, monitor):
        with patch("jobs.fetch_report_weather", side_effect=Exception("API down")), \
                patch("jobs.send_notification") as mock_notify:
            for _ in range(jobs.API_FAILURE_NOTIFY_AFTER - 1):
                jobs.send_daily_report(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Weather App Error" not in titles

    def test_notifies_only_once_per_outage(self, monitor):
        with patch("jobs.fetch_report_weather", side_effect=Exception("API down")), \
                patch("jobs.send_notification") as mock_notify:
            for _ in range(jobs.API_FAILURE_NOTIFY_AFTER + 3):
                jobs.send_daily_report(monitor)
        error_calls = [c for c in mock_notify.call_args_list if c.kwargs.get("title") == "Weather App Error"]
        assert len(error_calls) == 1

    def test_resets_and_renotifies_after_recovery(self, monitor):
        with patch("jobs.fetch_report_weather", side_effect=Exception("down")), \
                patch("jobs.send_notification"):
            for _ in range(jobs.API_FAILURE_NOTIFY_AFTER):
                jobs.send_daily_report(monitor)
        with patch("jobs.fetch_report_weather", return_value=REPORT_DATA), \
                patch("jobs.send_notification"):
            jobs.send_daily_report(monitor)
        with patch("jobs.fetch_report_weather", side_effect=Exception("down")), \
                patch("jobs.send_notification") as mock_notify:
            for _ in range(jobs.API_FAILURE_NOTIFY_AFTER):
                jobs.send_daily_report(monitor)
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Weather App Error" in titles


# ---------------------------------------------------------------------------
# prune_database
# ---------------------------------------------------------------------------

class TestPruneDatabase:
    def test_logs_pruned_counts(self):
        with patch("jobs.db.prune_old_records", return_value=(2, 5)) as mock_prune, \
                patch("jobs.log") as mock_log:
            jobs.prune_database()
        mock_prune.assert_called_once_with(jobs.DB_RETAIN_DAYS)
        mock_log.info.assert_called_once()

    def test_swallows_exception(self):
        with patch("jobs.db.prune_old_records", side_effect=Exception("disk full")), \
                patch("jobs.log") as mock_log:
            jobs.prune_database()  # must not raise
        mock_log.exception.assert_called_once()