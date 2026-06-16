from unittest.mock import MagicMock, patch

import pytest

import main


@pytest.fixture
def client():
    main.app.config["TESTING"] = True
    with main.app.test_client() as c:
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
# /history/reports
# ---------------------------------------------------------------------------

class TestHistoryReportsRoute:
    def test_empty_initially(self, client):
        assert client.get("/history/reports").get_json() == []

    def test_returns_recorded_reports(self, client):
        import db as db_module
        db_module.record_report("daily", "morning report")
        data = client.get("/history/reports").get_json()
        assert len(data) == 1
        assert data[0]["type"] == "daily"
        assert data[0]["message"] == "morning report"

    def test_filter_by_type(self, client):
        import db as db_module
        db_module.record_report("daily", "daily")
        db_module.record_report("quick", "quick")
        data = client.get("/history/reports?type=daily").get_json()
        assert len(data) == 1
        assert data[0]["type"] == "daily"

    def test_limit_param(self, client):
        import db as db_module
        for i in range(5):
            db_module.record_report("quick", f"report {i}")
        assert len(client.get("/history/reports?limit=3").get_json()) == 3

    def test_invalid_limit_returns_400(self, client):
        assert client.get("/history/reports?limit=abc").status_code == 400


# ---------------------------------------------------------------------------
# /history/alerts
# ---------------------------------------------------------------------------

class TestHistoryAlertsRoute:
    def test_empty_initially(self, client):
        assert client.get("/history/alerts").get_json() == []

    def test_returns_recorded_alerts(self, client):
        import db as db_module
        db_module.record_alert("rain", "rain alert")
        data = client.get("/history/alerts").get_json()
        assert len(data) == 1
        assert data[0]["type"] == "rain"
        assert data[0]["message"] == "rain alert"

    def test_filter_by_type(self, client):
        import db as db_module
        db_module.record_alert("rain", "rain")
        db_module.record_alert("wind", "wind")
        data = client.get("/history/alerts?type=wind").get_json()
        assert len(data) == 1
        assert data[0]["type"] == "wind"

    def test_limit_param(self, client):
        import db as db_module
        for i in range(5):
            db_module.record_alert("heat", f"alert {i}")
        assert len(client.get("/history/alerts?limit=3").get_json()) == 3

    def test_invalid_limit_returns_400(self, client):
        assert client.get("/history/alerts?limit=abc").status_code == 400

    def test_reports_not_visible_in_alerts(self, client):
        import db as db_module
        db_module.record_report("daily", "report")
        assert client.get("/history/alerts").get_json() == []


# ---------------------------------------------------------------------------
# _startup — catch-up daily report
# ---------------------------------------------------------------------------

class TestStartupDailyReport:
    def _run_startup(self):
        mock_sched = MagicMock()
        with patch("main.BackgroundScheduler", return_value=mock_sched), \
                patch("main.send_daily_report") as mock_report:
            main._startup()
        return mock_report

    def test_sends_report_when_none_recorded_today(self):
        mock_report = self._run_startup()
        mock_report.assert_called_once()

    def test_skips_report_when_already_sent_today(self):
        import db as db_module
        db_module.record_report("daily", "already sent")
        mock_report = self._run_startup()
        mock_report.assert_not_called()

    def test_sends_report_when_last_was_yesterday(self):
        from datetime import timedelta, timezone
        import db as db_module
        yesterday = __import__("datetime").datetime.now(timezone.utc) - timedelta(days=1)
        with db_module.Session(db_module._require_engine()) as session:
            session.add(db_module.Report(type="daily", message="yesterday", created_at=yesterday))
            session.commit()
        mock_report = self._run_startup()
        mock_report.assert_called_once()
