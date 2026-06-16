from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

import jobs

EASTERN = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def reset_cooldowns():
    jobs._last_rain_alert = None
    jobs._last_wind_alert = None
    jobs._last_heat_alert = None
    jobs._rain_cooldown_secs = 7200.0
    jobs._last_rain_code = None
    jobs._wind_cooldown_secs = 14400.0
    jobs._last_wind_peak = 0.0
    jobs._heat_cooldown_secs = 21600.0
    jobs._last_heat_peak = 0.0
    yield
    jobs._last_rain_alert = None
    jobs._last_wind_alert = None
    jobs._last_heat_alert = None
    jobs._rain_cooldown_secs = 7200.0
    jobs._last_rain_code = None
    jobs._wind_cooldown_secs = 14400.0
    jobs._last_wind_peak = 0.0
    jobs._heat_cooldown_secs = 21600.0
    jobs._last_heat_peak = 0.0


# ---------------------------------------------------------------------------
# init_cooldowns
# ---------------------------------------------------------------------------

class TestInitCooldowns:
    def test_all_none_when_no_alerts_in_db(self):
        jobs.init_cooldowns()
        assert jobs._last_rain_alert is None
        assert jobs._last_wind_alert is None
        assert jobs._last_heat_alert is None

    def test_seeds_from_db(self):
        import db as db_module
        db_module.record_alert("rain", "a rain alert")
        jobs.init_cooldowns()
        assert jobs._last_rain_alert is not None
        assert jobs._last_wind_alert is None
        assert jobs._last_heat_alert is None

    def test_seeds_all_types(self):
        import db as db_module
        db_module.record_alert("rain", "rain")
        db_module.record_alert("wind", "wind")
        db_module.record_alert("heat", "heat")
        jobs.init_cooldowns()
        assert jobs._last_rain_alert is not None
        assert jobs._last_wind_alert is not None
        assert jobs._last_heat_alert is not None


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
# send_quick_report
# ---------------------------------------------------------------------------

class TestSendQuickReport:
    def test_message_contains_conditions(self):
        with patch("jobs.fetch_report_weather", return_value=REPORT_DATA), \
                patch("jobs.send_notification"):
            result = jobs.send_quick_report()
        assert "Partly cloudy" in result
        assert "88°F" in result
        assert "95°F" in result
        assert "72%" in result
        assert "12 mph S" in result
        assert "gusts 18 mph" in result

    def test_sends_notification_with_correct_title(self):
        with patch("jobs.fetch_report_weather", return_value=REPORT_DATA), \
                patch("jobs.send_notification") as mock_notify:
            jobs.send_quick_report()
        _, kwargs = mock_notify.call_args
        assert kwargs["title"] == "Current Conditions"


# ---------------------------------------------------------------------------
# send_daily_report
# ---------------------------------------------------------------------------

class TestSendDailyReport:
    def test_message_contains_key_fields(self):
        with patch("jobs.fetch_report_weather", return_value=REPORT_DATA), \
                patch("jobs.send_notification") as mock_notify:
            jobs.send_daily_report()
        message = mock_notify.call_args[0][0]
        assert "88°F" in message
        assert "75°F" in message
        assert "95°F" in message
        assert "40%" in message
        assert "22 mph" in message
        assert "06:23 AM" in message
        assert "20:15" not in message
        assert "08:15 PM" in message

    def test_logs_and_swallows_api_error(self):
        with patch("jobs.fetch_report_weather", side_effect=Exception("API down")), \
                patch("jobs.log") as mock_log:
            jobs.send_daily_report()  # must not raise
        mock_log.exception.assert_called_once()

    def test_hourly_section_appears_in_message(self):
        from datetime import date
        today = date.today()
        times = [f"{today}T{h:02d}:00" for h in range(6, 23)]
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
            jobs.send_daily_report()
        message = mock_notify.call_args[0][0]
        assert "Hourly:" in message
        assert "85°F" in message
        assert "10%" in message

    def test_no_hourly_section_when_no_data(self):
        with patch("jobs.fetch_report_weather", return_value=REPORT_DATA), \
                patch("jobs.send_notification") as mock_notify:
            jobs.send_daily_report()
        message = mock_notify.call_args[0][0]
        assert "Hourly:" not in message


# ---------------------------------------------------------------------------
# check_weather_alerts — rain
# ---------------------------------------------------------------------------

class TestRainAlert:
    def test_sends_alert_when_rain_expected(self):
        times = _future_times(2)
        data = _alert_data(times, [75.0, 80.0], [0.1, 0.2], [61, 63], [15.0, 18.0], [82.0, 83.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Rain Alert" in titles

    def test_rain_alert_is_high_priority(self):
        times = _future_times(1)
        data = _alert_data(times, [80.0], [0.1], [61], [15.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        rain_call = next(c for c in mock_notify.call_args_list if c.kwargs.get("title") == "Rain Alert")
        assert rain_call.kwargs["priority"] == "high"

    def test_no_alert_when_no_rain(self):
        times = _future_times(2)
        data = _alert_data(times, [10.0, 5.0], [0.0, 0.0], [0, 1], [10.0, 12.0], [82.0, 83.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Rain Alert" not in titles

    def test_rain_cooldown_suppresses_alert(self):
        jobs._last_rain_alert = datetime.now(EASTERN)
        times = _future_times(1)
        data = _alert_data(times, [80.0], [0.1], [61], [10.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Rain Alert" not in titles

    def test_sets_rain_cooldown_after_alert(self):
        times = _future_times(1)
        data = _alert_data(times, [80.0], [0.1], [61], [10.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification"):
            jobs.check_weather_alerts()
        assert jobs._last_rain_alert is not None

    def test_rain_resends_when_code_changes_during_cooldown(self):
        jobs._last_rain_alert = datetime.now(EASTERN)
        jobs._last_rain_code = 61  # last alert was light rain
        times = _future_times(1)
        data = _alert_data(times, [80.0], [0.1], [95], [10.0], [82.0])  # now thunderstorm
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Rain Alert" in titles

    def test_rain_cooldown_holds_when_code_same(self):
        jobs._last_rain_alert = datetime.now(EASTERN)
        jobs._last_rain_code = 61
        times = _future_times(1)
        data = _alert_data(times, [80.0], [0.1], [61], [10.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Rain Alert" not in titles

    def test_rain_alert_includes_start_and_end_times(self):
        times = _future_times(3)
        data = _alert_data(times, [80.0, 75.0, 60.0], [0.1, 0.2, 0.1], [61, 63, 61], [10.0, 10.0, 10.0], [82.0, 82.0, 82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        rain_call = next(c for c in mock_notify.call_args_list if c.kwargs.get("title") == "Rain Alert")
        message = rain_call.args[0]
        assert "–" in message


# ---------------------------------------------------------------------------
# check_weather_alerts — wind
# ---------------------------------------------------------------------------

class TestWindAlert:
    def test_sends_alert_when_gusts_exceed_threshold(self):
        times = _future_times(2)
        data = _alert_data(times, [5.0, 5.0], [0.0, 0.0], [0, 0], [35.0, 38.0], [82.0, 83.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" in titles

    def test_sends_alert_on_current_gusts(self):
        data = {
            "current": {**_SAFE_CURRENT, "wind_gusts_10m": 35.0},
            "hourly": {
                "time": [], "precipitation_probability": [], "precipitation": [],
                "rain": [], "weather_code": [], "wind_gusts_10m": [], "apparent_temperature": [],
            },
        }
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" in titles

    def test_no_alert_below_threshold(self):
        times = _future_times(2)
        data = _alert_data(times, [5.0, 5.0], [0.0, 0.0], [0, 0], [10.0, 12.0], [82.0, 83.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" not in titles

    def test_wind_cooldown_suppresses_alert(self):
        jobs._last_wind_alert = datetime.now(EASTERN)
        jobs._last_wind_peak = 38.0
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [38.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" not in titles

    def test_sets_wind_cooldown_after_alert(self):
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [38.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification"):
            jobs.check_weather_alerts()
        assert jobs._last_wind_alert is not None

    def test_wind_resends_when_gusts_increase_during_cooldown(self):
        jobs._last_wind_alert = datetime.now(EASTERN)
        jobs._last_wind_peak = 32.0
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [40.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" in titles

    def test_wind_cooldown_holds_when_gusts_same(self):
        jobs._last_wind_alert = datetime.now(EASTERN)
        jobs._last_wind_peak = 38.0
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [38.0], [82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" not in titles

    def test_wind_alert_includes_time_range(self):
        times = _future_times(3)
        data = _alert_data(times, [5.0, 5.0, 5.0], [0.0, 0.0, 0.0], [0, 0, 0], [35.0, 38.0, 32.0], [82.0, 82.0, 82.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        wind_call = next(c for c in mock_notify.call_args_list if c.kwargs.get("title") == "Wind Gust Alert")
        message = wind_call.args[0]
        assert "from" in message
        assert "to" in message


# ---------------------------------------------------------------------------
# check_weather_alerts — heat
# ---------------------------------------------------------------------------

class TestHeatAlert:
    def test_sends_alert_when_heat_exceeds_threshold(self):
        times = _future_times(2)
        data = _alert_data(times, [5.0, 5.0], [0.0, 0.0], [0, 0], [10.0, 12.0], [103.0, 105.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Heat Risk Alert" in titles

    def test_sends_alert_on_current_heat(self):
        data = {
            "current": {**_SAFE_CURRENT, "apparent_temperature": 105.0},
            "hourly": {
                "time": [], "precipitation_probability": [], "precipitation": [],
                "rain": [], "weather_code": [], "wind_gusts_10m": [], "apparent_temperature": [],
            },
        }
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Heat Risk Alert" in titles

    def test_no_alert_below_threshold(self):
        times = _future_times(2)
        data = _alert_data(times, [5.0, 5.0], [0.0, 0.0], [0, 0], [10.0, 12.0], [82.0, 85.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Heat Risk Alert" not in titles

    def test_heat_cooldown_suppresses_alert(self):
        jobs._last_heat_alert = datetime.now(EASTERN)
        jobs._last_heat_peak = 105.0
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [10.0], [105.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Heat Risk Alert" not in titles

    def test_sets_heat_cooldown_after_alert(self):
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [10.0], [105.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification"):
            jobs.check_weather_alerts()
        assert jobs._last_heat_alert is not None

    def test_heat_resends_when_temperature_rises_during_cooldown(self):
        jobs._last_heat_alert = datetime.now(EASTERN)
        jobs._last_heat_peak = 102.0
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [10.0], [107.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Heat Risk Alert" in titles

    def test_heat_cooldown_holds_when_temperature_same(self):
        jobs._last_heat_alert = datetime.now(EASTERN)
        jobs._last_heat_peak = 106.0
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [10.0], [106.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Heat Risk Alert" not in titles

    def test_heat_alert_includes_time_range(self):
        times = _future_times(3)
        data = _alert_data(times, [5.0, 5.0, 5.0], [0.0, 0.0, 0.0], [0, 0, 0], [10.0, 10.0, 10.0], [103.0, 106.0, 101.0])
        with patch("jobs.fetch_rain_check_weather", return_value=data), \
                patch("jobs.send_notification") as mock_notify:
            jobs.check_weather_alerts()
        heat_call = next(c for c in mock_notify.call_args_list if c.kwargs.get("title") == "Heat Risk Alert")
        message = heat_call.args[0]
        assert "from" in message
        assert "to" in message


# ---------------------------------------------------------------------------
# check_weather_alerts — combined cooldown skip
# ---------------------------------------------------------------------------

class TestAlertCooldownSkip:
    def test_skips_fetch_when_all_cooldowns_active(self):
        jobs._last_rain_alert = datetime.now(EASTERN)
        jobs._last_wind_alert = datetime.now(EASTERN)
        jobs._last_heat_alert = datetime.now(EASTERN)
        with patch("jobs.fetch_rain_check_weather") as mock_fetch:
            jobs.check_weather_alerts()
        mock_fetch.assert_not_called()

    def test_logs_and_swallows_api_error(self):
        with patch("jobs.fetch_rain_check_weather", side_effect=Exception("timeout")), \
                patch("jobs.log") as mock_log:
            jobs.check_weather_alerts()  # must not raise
        mock_log.exception.assert_called_once()
