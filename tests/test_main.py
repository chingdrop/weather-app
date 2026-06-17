from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app import db as db_module
from app import app as flask_app
import app.state as state
import app.startup as startup_module
from conftest import TEST_CFG

TEST_LOCATION_ID = None  # resolved in fixture below


@pytest.fixture
def client(monitor):
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealthRoute:
    def test_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /report
# ---------------------------------------------------------------------------

class TestReportRoute:
    def test_returns_sent_status(self, client):
        with patch("app.routes.api.send_quick_report", return_value="Partly cloudy\nTemp: 88°F"):
            resp = client.get("/report")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "sent"
        assert "88°F" in data["message"]

    def test_returns_500_json_on_error(self, client):
        with patch("app.routes.api.send_quick_report", side_effect=Exception("API error")):
            resp = client.get("/report")
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["status"] == "error"
        assert "API error" in data["message"]

    def test_returns_400_when_no_monitors(self, client):
        state.monitors.clear()
        resp = client.get("/report")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /history/reports
# ---------------------------------------------------------------------------

class TestHistoryReportsRoute:
    def test_empty_initially(self, client):
        assert client.get("/history/reports").get_json() == []

    def test_returns_recorded_reports(self, client, monitor):
        db_module.record_report(monitor.location_id, "daily", "morning report")
        data = client.get("/history/reports").get_json()
        assert len(data) == 1
        assert data[0]["type"] == "daily"
        assert data[0]["message"] == "morning report"

    def test_filter_by_type(self, client, monitor):
        db_module.record_report(monitor.location_id, "daily", "daily")
        db_module.record_report(monitor.location_id, "quick", "quick")
        data = client.get("/history/reports?type=daily").get_json()
        assert len(data) == 1
        assert data[0]["type"] == "daily"

    def test_filter_by_location(self, client, monitor):
        db_module.record_report(monitor.location_id, "daily", "report")
        data = client.get(f"/history/reports?location={TEST_CFG.name}").get_json()
        assert len(data) == 1

    def test_unknown_location_returns_404(self, client):
        resp = client.get("/history/reports?location=nowhere")
        assert resp.status_code == 404

    def test_limit_param(self, client, monitor):
        for i in range(5):
            db_module.record_report(monitor.location_id, "quick", f"report {i}")
        assert len(client.get("/history/reports?limit=3").get_json()) == 3

    def test_invalid_limit_returns_400(self, client):
        assert client.get("/history/reports?limit=abc").status_code == 400


# ---------------------------------------------------------------------------
# /history/alerts
# ---------------------------------------------------------------------------

class TestHistoryAlertsRoute:
    def test_empty_initially(self, client):
        assert client.get("/history/alerts").get_json() == []

    def test_returns_recorded_alerts(self, client, monitor):
        db_module.record_alert(monitor.location_id, "rain", "rain alert")
        data = client.get("/history/alerts").get_json()
        assert len(data) == 1
        assert data[0]["type"] == "rain"
        assert data[0]["message"] == "rain alert"

    def test_filter_by_type(self, client, monitor):
        db_module.record_alert(monitor.location_id, "rain", "rain")
        db_module.record_alert(monitor.location_id, "wind", "wind")
        data = client.get("/history/alerts?type=wind").get_json()
        assert len(data) == 1
        assert data[0]["type"] == "wind"

    def test_filter_by_location(self, client, monitor):
        db_module.record_alert(monitor.location_id, "rain", "alert")
        data = client.get(f"/history/alerts?location={TEST_CFG.name}").get_json()
        assert len(data) == 1

    def test_unknown_location_returns_404(self, client):
        resp = client.get("/history/alerts?location=nowhere")
        assert resp.status_code == 404

    def test_limit_param(self, client, monitor):
        for i in range(5):
            db_module.record_alert(monitor.location_id, "heat", f"alert {i}")
        assert len(client.get("/history/alerts?limit=3").get_json()) == 3

    def test_invalid_limit_returns_400(self, client):
        assert client.get("/history/alerts?limit=abc").status_code == 400

    def test_reports_not_visible_in_alerts(self, client, monitor):
        db_module.record_report(monitor.location_id, "daily", "report")
        assert client.get("/history/alerts").get_json() == []


# ---------------------------------------------------------------------------
# startup — catch-up daily report
# ---------------------------------------------------------------------------

class TestStartupDailyReport:
    def _run_startup(self):
        with patch("app.startup.db.init_db"), \
                patch("app.startup.start_scheduler"), \
                patch("app.startup.send_daily_report") as mock_report:
            startup_module.startup()
        return mock_report

    def test_sends_report_when_none_recorded_today(self, location_id):
        mock_report = self._run_startup()
        mock_report.assert_called_once()

    def test_skips_report_when_already_sent_today(self, location_id):
        db_module.record_report(location_id, "daily", "already sent")
        mock_report = self._run_startup()
        mock_report.assert_not_called()

    def test_sends_report_when_last_was_yesterday(self, location_id):
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        with db_module.Session(db_module._require_engine()) as session:
            session.add(db_module.Report(location_id=location_id, type="daily", message="yesterday", created_at=yesterday))
            session.commit()
        mock_report = self._run_startup()
        mock_report.assert_called_once()