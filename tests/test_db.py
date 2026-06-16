from sqlalchemy import inspect

import db


class TestInitDb:
    def test_creates_both_tables(self):
        tables = inspect(db._engine).get_table_names()
        assert "reports" in tables
        assert "alerts" in tables

    def test_idempotent(self):
        db.init_db()
        db.init_db()


class TestRecordReport:
    def test_inserts_row(self):
        db.record_report("daily", "Morning report")
        rows = db.get_reports()
        assert len(rows) == 1
        assert rows[0]["type"] == "daily"
        assert rows[0]["message"] == "Morning report"
        assert rows[0]["created_at"] is not None

    def test_multiple_reports(self):
        db.record_report("daily", "first")
        db.record_report("quick", "second")
        assert len(db.get_reports()) == 2

    def test_does_not_appear_in_alerts(self):
        db.record_report("daily", "report")
        assert db.get_alerts() == []


class TestRecordAlert:
    def test_inserts_row(self):
        db.record_alert("rain", "Rain incoming")
        rows = db.get_alerts()
        assert len(rows) == 1
        assert rows[0]["type"] == "rain"
        assert rows[0]["message"] == "Rain incoming"

    def test_multiple_alerts(self):
        db.record_alert("rain", "Rain")
        db.record_alert("wind", "Wind")
        assert len(db.get_alerts()) == 2

    def test_does_not_appear_in_reports(self):
        db.record_alert("rain", "alert")
        assert db.get_reports() == []


class TestGetReports:
    def test_returns_most_recent_first(self):
        db.record_report("daily", "first")
        db.record_report("quick", "second")
        rows = db.get_reports()
        assert rows[0]["message"] == "second"

    def test_filter_by_type(self):
        db.record_report("daily", "daily report")
        db.record_report("quick", "quick report")
        rows = db.get_reports(report_type="daily")
        assert len(rows) == 1
        assert rows[0]["type"] == "daily"

    def test_limit(self):
        for i in range(5):
            db.record_report("quick", f"report {i}")
        assert len(db.get_reports(limit=3)) == 3

    def test_empty_returns_empty_list(self):
        assert db.get_reports() == []

    def test_unknown_type_returns_empty(self):
        db.record_report("daily", "report")
        assert db.get_reports(report_type="unknown") == []


class TestGetAlerts:
    def test_returns_most_recent_first(self):
        db.record_alert("rain", "first")
        db.record_alert("wind", "second")
        rows = db.get_alerts()
        assert rows[0]["message"] == "second"

    def test_filter_by_type(self):
        db.record_alert("rain", "rain alert")
        db.record_alert("wind", "wind alert")
        rows = db.get_alerts(alert_type="wind")
        assert len(rows) == 1
        assert rows[0]["type"] == "wind"

    def test_limit(self):
        for i in range(5):
            db.record_alert("heat", f"alert {i}")
        assert len(db.get_alerts(limit=3)) == 3

    def test_empty_returns_empty_list(self):
        assert db.get_alerts() == []

    def test_unknown_type_returns_empty(self):
        db.record_alert("rain", "alert")
        assert db.get_alerts(alert_type="unknown") == []