import pytest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import main

EASTERN = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def reset_rain_cooldown():
    main._last_rain_alert = None
    yield
    main._last_rain_alert = None


@pytest.fixture
def client():
    main.app.config["TESTING"] = True
    with main.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# send_quick_report
# ---------------------------------------------------------------------------

CURRENT_DATA = {
    "current": {
        "temperature_2m": 88.0,
        "apparent_temperature": 95.0,
        "relative_humidity_2m": 72.0,
        "weather_code": 2,
        "wind_speed_10m": 12.0,
        "wind_direction_10m": 180.0,
        "precipitation": 0.0,
    }
}


class TestSendQuickReport:
    def test_message_contains_conditions(self):
        with patch("main.fetch", return_value=CURRENT_DATA), \
             patch("main.send_notification"):
            result = main.send_quick_report()
        assert "Partly cloudy" in result
        assert "88°F" in result
        assert "95°F" in result
        assert "72%" in result
        assert "12 mph S" in result

    def test_sends_notification_with_correct_title(self):
        with patch("main.fetch", return_value=CURRENT_DATA), \
             patch("main.send_notification") as mock_notify:
            main.send_quick_report()
        _, kwargs = mock_notify.call_args
        assert kwargs["title"] == "Current Conditions"


# ---------------------------------------------------------------------------
# send_daily_report
# ---------------------------------------------------------------------------

DAILY_DATA = {
    "daily": {
        "weather_code": [2],
        "temperature_2m_max": [88.0],
        "temperature_2m_min": [75.0],
        "precipitation_probability_max": [40.0],
        "precipitation_sum": [0.50],
        "uv_index_max": [8.0],
        "sunrise": ["2026-06-12T06:23"],
        "sunset": ["2026-06-12T20:15"],
    }
}


class TestSendDailyReport:
    def test_message_contains_key_fields(self):
        with patch("main.fetch", return_value=DAILY_DATA), \
             patch("main.send_notification") as mock_notify:
            main.send_daily_report()
        message = mock_notify.call_args[0][0]
        assert "88°F" in message
        assert "75°F" in message
        assert "40%" in message
        assert "06:23 AM" in message
        assert "20:15" not in message  # sunset uses 12-hour format
        assert "08:15 PM" in message

    def test_logs_and_swallows_api_error(self):
        with patch("main.fetch", side_effect=Exception("API down")), \
             patch("main.log") as mock_log:
            main.send_daily_report()  # must not raise
        mock_log.exception.assert_called_once()


# ---------------------------------------------------------------------------
# check_rain_alert
# ---------------------------------------------------------------------------

def _future_times(count: int) -> list[str]:
    now = datetime.now(EASTERN)
    return [(now + timedelta(hours=i + 1)).strftime("%Y-%m-%dT%H:00") for i in range(count)]


class TestCheckRainAlert:
    def test_sends_alert_when_rain_expected(self):
        times = _future_times(2)
        data = {
            "hourly": {
                "time": times,
                "precipitation_probability": [75.0, 80.0],
                "precipitation": [0.1, 0.2],
                "weather_code": [61, 63],
            }
        }
        with patch("main.fetch", return_value=data), \
             patch("main.send_notification") as mock_notify:
            main.check_rain_alert()
        mock_notify.assert_called_once()
        _, kwargs = mock_notify.call_args
        assert kwargs["priority"] == "high"

    def test_no_alert_when_no_rain(self):
        times = _future_times(2)
        data = {
            "hourly": {
                "time": times,
                "precipitation_probability": [10.0, 5.0],
                "precipitation": [0.0, 0.0],
                "weather_code": [0, 1],
            }
        }
        with patch("main.fetch", return_value=data), \
             patch("main.send_notification") as mock_notify:
            main.check_rain_alert()
        mock_notify.assert_not_called()

    def test_respects_two_hour_cooldown(self):
        main._last_rain_alert = datetime.now(EASTERN)
        with patch("main.fetch") as mock_fetch:
            main.check_rain_alert()
        mock_fetch.assert_not_called()

    def test_sets_cooldown_timestamp_after_alert(self):
        times = _future_times(1)
        data = {
            "hourly": {
                "time": times,
                "precipitation_probability": [80.0],
                "precipitation": [0.2],
                "weather_code": [61],
            }
        }
        with patch("main.fetch", return_value=data), \
             patch("main.send_notification"):
            main.check_rain_alert()
        assert main._last_rain_alert is not None

    def test_logs_and_swallows_api_error(self):
        with patch("main.fetch", side_effect=Exception("timeout")), \
             patch("main.log") as mock_log:
            main.check_rain_alert()  # must not raise
        mock_log.exception.assert_called_once()


# ---------------------------------------------------------------------------
# /report route
# ---------------------------------------------------------------------------

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