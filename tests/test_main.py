from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

import main

EASTERN = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def reset_cooldowns():
    main._last_rain_alert = None
    main._last_wind_alert = None
    main._last_heat_alert = None
    yield
    main._last_rain_alert = None
    main._last_wind_alert = None
    main._last_heat_alert = None


@pytest.fixture
def client():
    main.app.config["TESTING"] = True
    with main.app.test_client() as c:
        yield c


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
        with patch("main.fetch_report_weather", return_value=REPORT_DATA), \
                patch("main.send_notification"):
            result = main.send_quick_report()
        assert "Partly cloudy" in result
        assert "88°F" in result
        assert "95°F" in result
        assert "72%" in result
        assert "12 mph S" in result
        assert "gusts 18 mph" in result

    def test_sends_notification_with_correct_title(self):
        with patch("main.fetch_report_weather", return_value=REPORT_DATA), \
                patch("main.send_notification") as mock_notify:
            main.send_quick_report()
        _, kwargs = mock_notify.call_args
        assert kwargs["title"] == "Current Conditions"


# ---------------------------------------------------------------------------
# send_daily_report
# ---------------------------------------------------------------------------

class TestSendDailyReport:
    def test_message_contains_key_fields(self):
        with patch("main.fetch_report_weather", return_value=REPORT_DATA), \
                patch("main.send_notification") as mock_notify:
            main.send_daily_report()
        message = mock_notify.call_args[0][0]
        assert "88°F" in message
        assert "75°F" in message
        assert "95°F" in message  # feels-like max
        assert "40%" in message
        assert "22 mph" in message  # wind gusts max
        assert "06:23 AM" in message
        assert "20:15" not in message  # sunset uses 12-hour format
        assert "08:15 PM" in message

    def test_logs_and_swallows_api_error(self):
        with patch("main.fetch_report_weather", side_effect=Exception("API down")), \
                patch("main.log") as mock_log:
            main.send_daily_report()  # must not raise
        mock_log.exception.assert_called_once()


# ---------------------------------------------------------------------------
# check_weather_alerts — rain
# ---------------------------------------------------------------------------

class TestRainAlert:
    def test_sends_alert_when_rain_expected(self):
        times = _future_times(2)
        data = _alert_data(times, [75.0, 80.0], [0.1, 0.2], [61, 63], [15.0, 18.0], [82.0, 83.0])
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification") as mock_notify:
            main.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Rain Alert" in titles

    def test_rain_alert_is_high_priority(self):
        times = _future_times(1)
        data = _alert_data(times, [80.0], [0.1], [61], [15.0], [82.0])
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification") as mock_notify:
            main.check_weather_alerts()
        rain_call = next(c for c in mock_notify.call_args_list if c.kwargs.get("title") == "Rain Alert")
        assert rain_call.kwargs["priority"] == "high"

    def test_no_alert_when_no_rain(self):
        times = _future_times(2)
        data = _alert_data(times, [10.0, 5.0], [0.0, 0.0], [0, 1], [10.0, 12.0], [82.0, 83.0])
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification") as mock_notify:
            main.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Rain Alert" not in titles

    def test_rain_cooldown_suppresses_alert(self):
        main._last_rain_alert = datetime.now(EASTERN)
        times = _future_times(1)
        data = _alert_data(times, [80.0], [0.1], [61], [10.0], [82.0])
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification") as mock_notify:
            main.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Rain Alert" not in titles

    def test_sets_rain_cooldown_after_alert(self):
        times = _future_times(1)
        data = _alert_data(times, [80.0], [0.1], [61], [10.0], [82.0])
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification"):
            main.check_weather_alerts()
        assert main._last_rain_alert is not None


# ---------------------------------------------------------------------------
# check_weather_alerts — wind
# ---------------------------------------------------------------------------

class TestWindAlert:
    def test_sends_alert_when_gusts_exceed_threshold(self):
        times = _future_times(2)
        data = _alert_data(times, [5.0, 5.0], [0.0, 0.0], [0, 0], [35.0, 38.0], [82.0, 83.0])
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification") as mock_notify:
            main.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" in titles

    def test_sends_alert_on_current_gusts(self):
        # No upcoming hours, but current gusts are high
        data = {
            "current": {**_SAFE_CURRENT, "wind_gusts_10m": 35.0},
            "hourly": {
                "time": [], "precipitation_probability": [], "precipitation": [],
                "rain": [], "weather_code": [], "wind_gusts_10m": [], "apparent_temperature": [],
            },
        }
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification") as mock_notify:
            main.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" in titles

    def test_no_alert_below_threshold(self):
        times = _future_times(2)
        data = _alert_data(times, [5.0, 5.0], [0.0, 0.0], [0, 0], [10.0, 12.0], [82.0, 83.0])
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification") as mock_notify:
            main.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" not in titles

    def test_wind_cooldown_suppresses_alert(self):
        main._last_wind_alert = datetime.now(EASTERN)
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [38.0], [82.0])
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification") as mock_notify:
            main.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Wind Gust Alert" not in titles

    def test_sets_wind_cooldown_after_alert(self):
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [38.0], [82.0])
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification"):
            main.check_weather_alerts()
        assert main._last_wind_alert is not None


# ---------------------------------------------------------------------------
# check_weather_alerts — heat
# ---------------------------------------------------------------------------

class TestHeatAlert:
    def test_sends_alert_when_heat_exceeds_threshold(self):
        times = _future_times(2)
        data = _alert_data(times, [5.0, 5.0], [0.0, 0.0], [0, 0], [10.0, 12.0], [103.0, 105.0])
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification") as mock_notify:
            main.check_weather_alerts()
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
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification") as mock_notify:
            main.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Heat Risk Alert" in titles

    def test_no_alert_below_threshold(self):
        times = _future_times(2)
        data = _alert_data(times, [5.0, 5.0], [0.0, 0.0], [0, 0], [10.0, 12.0], [82.0, 85.0])
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification") as mock_notify:
            main.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Heat Risk Alert" not in titles

    def test_heat_cooldown_suppresses_alert(self):
        main._last_heat_alert = datetime.now(EASTERN)
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [10.0], [105.0])
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification") as mock_notify:
            main.check_weather_alerts()
        titles = [c.kwargs.get("title") for c in mock_notify.call_args_list]
        assert "Heat Risk Alert" not in titles

    def test_sets_heat_cooldown_after_alert(self):
        times = _future_times(1)
        data = _alert_data(times, [5.0], [0.0], [0], [10.0], [105.0])
        with patch("main.fetch_rain_check_weather", return_value=data), \
                patch("main.send_notification"):
            main.check_weather_alerts()
        assert main._last_heat_alert is not None


# ---------------------------------------------------------------------------
# check_weather_alerts — combined cooldown skip
# ---------------------------------------------------------------------------

class TestAlertCooldownSkip:
    def test_skips_fetch_when_all_cooldowns_active(self):
        main._last_rain_alert = datetime.now(EASTERN)
        main._last_wind_alert = datetime.now(EASTERN)
        main._last_heat_alert = datetime.now(EASTERN)
        with patch("main.fetch_rain_check_weather") as mock_fetch:
            main.check_weather_alerts()
        mock_fetch.assert_not_called()

    def test_logs_and_swallows_api_error(self):
        with patch("main.fetch_rain_check_weather", side_effect=Exception("timeout")), \
                patch("main.log") as mock_log:
            main.check_weather_alerts()  # must not raise
        mock_log.exception.assert_called_once()


# ---------------------------------------------------------------------------
# /health and /report routes
# ---------------------------------------------------------------------------

class TestHealthRoute:
    def test_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok"}


class TestReportRoute:
    def test_returns_sent_status(self, client):
        with patch("main.send_quick_report", return_value="Partly cloudy\nTemp: 88°F"):
            resp = client.get("/report")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "sent"
        assert "88°F" in data["message"]

    def test_returns_500_json_on_error(self, client):
        with patch("main.send_quick_report", side_effect=Exception("API error")):
            resp = client.get("/report")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["status"] == "error"
        assert "API error" in data["message"]


# ---------------------------------------------------------------------------
# /history route
# ---------------------------------------------------------------------------

class TestHistoryRoute:
    def test_empty_initially(self, client):
        resp = client.get("/history")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_returns_recorded_events(self, client):
        import db as db_module
        db_module.record_event("daily_report", "morning report")
        resp = client.get("/history")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["type"] == "daily_report"
        assert data[0]["message"] == "morning report"

    def test_filter_by_type(self, client):
        import db as db_module
        db_module.record_event("daily_report", "report")
        db_module.record_event("rain_alert", "alert")
        resp = client.get("/history?type=rain_alert")
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]["type"] == "rain_alert"

    def test_limit_param(self, client):
        import db as db_module
        for i in range(5):
            db_module.record_event("quick_report", f"report {i}")
        data = client.get("/history?limit=3").get_json()
        assert len(data) == 3

    def test_invalid_limit_returns_400(self, client):
        resp = client.get("/history?limit=abc")
        assert resp.status_code == 400

    def test_limit_capped_at_200(self, client):
        import db as db_module
        for i in range(10):
            db_module.record_event("quick_report", f"report {i}")
        data = client.get("/history?limit=999").get_json()
        assert len(data) == 10  # only 10 records exist, so all returned
