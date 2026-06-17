from datetime import timedelta, timezone

import pytest
from sqlalchemy import inspect

from app import db


class TestInitDb:
    def test_creates_all_tables(self):
        tables = inspect(db._engine).get_table_names()
        assert "locations" in tables
        assert "reports" in tables
        assert "alerts" in tables

    def test_idempotent(self):
        db.init_db()
        db.init_db()


class TestUpsertLocation:
    def test_creates_location(self):
        lid = db.upsert_location("home", 27.3, -82.5, "America/New_York", "topic1")
        assert isinstance(lid, int)

    def test_returns_same_id_on_repeat(self):
        lid1 = db.upsert_location("home", 27.3, -82.5, "America/New_York", "topic1")
        lid2 = db.upsert_location("home", 27.3, -82.5, "America/New_York", "topic1")
        assert lid1 == lid2

    def test_updates_fields_on_repeat(self):
        db.upsert_location("home", 27.3, -82.5, "America/New_York", "old-topic")
        db.upsert_location("home", 27.3, -82.5, "America/New_York", "new-topic")
        with db.Session(db._require_engine()) as session:
            loc = session.query(db.Location).filter_by(name="home").first()
        assert loc.ntfy_topic == "new-topic"

    def test_stores_thresholds(self):
        db.upsert_location("home", 27.3, -82.5, "America/New_York", "t", wind_gust_alert_mph=25.0)
        with db.Session(db._require_engine()) as session:
            loc = session.query(db.Location).filter_by(name="home").first()
        assert loc.wind_gust_alert_mph == 25.0

    def test_separate_locations_get_separate_ids(self):
        lid1 = db.upsert_location("home", 27.3, -82.5, "America/New_York", "t1")
        lid2 = db.upsert_location("cabin", 35.0, -83.0, "America/New_York", "t2")
        assert lid1 != lid2


class TestRecordReport:
    def test_inserts_row(self, location_id):
        db.record_report(location_id, "daily", "Morning report")
        rows = db.get_reports(location_id)
        assert len(rows) == 1
        assert rows[0]["type"] == "daily"
        assert rows[0]["message"] == "Morning report"
        assert rows[0]["created_at"] is not None

    def test_multiple_reports(self, location_id):
        db.record_report(location_id, "daily", "first")
        db.record_report(location_id, "quick", "second")
        assert len(db.get_reports(location_id)) == 2

    def test_does_not_appear_in_alerts(self, location_id):
        db.record_report(location_id, "daily", "report")
        assert db.get_alerts(location_id) == []


class TestRecordAlert:
    def test_inserts_row(self, location_id):
        db.record_alert(location_id, "rain", "Rain incoming")
        rows = db.get_alerts(location_id)
        assert len(rows) == 1
        assert rows[0]["type"] == "rain"
        assert rows[0]["message"] == "Rain incoming"

    def test_multiple_alerts(self, location_id):
        db.record_alert(location_id, "rain", "Rain")
        db.record_alert(location_id, "wind", "Wind")
        assert len(db.get_alerts(location_id)) == 2

    def test_does_not_appear_in_reports(self, location_id):
        db.record_alert(location_id, "rain", "alert")
        assert db.get_reports(location_id) == []


class TestGetReports:
    def test_returns_most_recent_first(self, location_id):
        db.record_report(location_id, "daily", "first")
        db.record_report(location_id, "quick", "second")
        rows = db.get_reports(location_id)
        assert rows[0]["message"] == "second"

    def test_filter_by_type(self, location_id):
        db.record_report(location_id, "daily", "daily report")
        db.record_report(location_id, "quick", "quick report")
        rows = db.get_reports(location_id, report_type="daily")
        assert len(rows) == 1
        assert rows[0]["type"] == "daily"

    def test_limit(self, location_id):
        for i in range(5):
            db.record_report(location_id, "quick", f"report {i}")
        assert len(db.get_reports(location_id, limit=3)) == 3

    def test_empty_returns_empty_list(self, location_id):
        assert db.get_reports(location_id) == []

    def test_unknown_type_returns_empty(self, location_id):
        db.record_report(location_id, "daily", "report")
        assert db.get_reports(location_id, report_type="unknown") == []

    def test_no_location_filter_returns_all(self):
        lid1 = db.upsert_location("a", 1.0, 1.0, "UTC", "t1")
        lid2 = db.upsert_location("b", 2.0, 2.0, "UTC", "t2")
        db.record_report(lid1, "daily", "loc1")
        db.record_report(lid2, "daily", "loc2")
        assert len(db.get_reports()) == 2

    def test_location_filter_isolates_records(self):
        lid1 = db.upsert_location("a", 1.0, 1.0, "UTC", "t1")
        lid2 = db.upsert_location("b", 2.0, 2.0, "UTC", "t2")
        db.record_report(lid1, "daily", "loc1")
        db.record_report(lid2, "daily", "loc2")
        assert len(db.get_reports(lid1)) == 1
        assert db.get_reports(lid1)[0]["message"] == "loc1"


class TestGetAlerts:
    def test_returns_most_recent_first(self, location_id):
        db.record_alert(location_id, "rain", "first")
        db.record_alert(location_id, "wind", "second")
        rows = db.get_alerts(location_id)
        assert rows[0]["message"] == "second"

    def test_filter_by_type(self, location_id):
        db.record_alert(location_id, "rain", "rain alert")
        db.record_alert(location_id, "wind", "wind alert")
        rows = db.get_alerts(location_id, alert_type="wind")
        assert len(rows) == 1
        assert rows[0]["type"] == "wind"

    def test_limit(self, location_id):
        for i in range(5):
            db.record_alert(location_id, "heat", f"alert {i}")
        assert len(db.get_alerts(location_id, limit=3)) == 3

    def test_empty_returns_empty_list(self, location_id):
        assert db.get_alerts(location_id) == []

    def test_unknown_type_returns_empty(self, location_id):
        db.record_alert(location_id, "rain", "alert")
        assert db.get_alerts(location_id, alert_type="unknown") == []

    def test_no_location_filter_returns_all(self):
        lid1 = db.upsert_location("a", 1.0, 1.0, "UTC", "t1")
        lid2 = db.upsert_location("b", 2.0, 2.0, "UTC", "t2")
        db.record_alert(lid1, "rain", "loc1")
        db.record_alert(lid2, "wind", "loc2")
        assert len(db.get_alerts()) == 2


class TestPruneOldRecords:
    def _insert_old(self, location_id, days: int = 40):
        cutoff = db.datetime.now(timezone.utc) - timedelta(days=days)
        with db.Session(db._require_engine()) as session:
            session.add(db.Report(location_id=location_id, type="daily", message="old report", created_at=cutoff))
            session.add(db.Alert(location_id=location_id, type="rain", message="old alert", created_at=cutoff))
            session.commit()

    def test_deletes_old_reports_and_alerts(self, location_id):
        self._insert_old(location_id)
        reports_deleted, alerts_deleted = db.prune_old_records(30)
        assert reports_deleted == 1
        assert alerts_deleted == 1
        assert db.get_reports(location_id) == []
        assert db.get_alerts(location_id) == []

    def test_keeps_recent_records(self, location_id):
        db.record_report(location_id, "daily", "recent")
        db.record_alert(location_id, "rain", "recent")
        reports_deleted, alerts_deleted = db.prune_old_records(30)
        assert reports_deleted == 0
        assert alerts_deleted == 0

    def test_returns_zero_when_nothing_to_prune(self):
        assert db.prune_old_records(30) == (0, 0)


class TestGetLastReportTime:
    def test_returns_none_when_no_reports(self, location_id):
        assert db.get_last_report_time(location_id, "daily") is None

    def test_returns_timestamp_after_report(self, location_id):
        db.record_report(location_id, "daily", "morning report")
        assert db.get_last_report_time(location_id, "daily") is not None

    def test_filters_by_type(self, location_id):
        db.record_report(location_id, "quick", "quick report")
        assert db.get_last_report_time(location_id, "daily") is None

    def test_filters_by_location(self):
        lid1 = db.upsert_location("a", 1.0, 1.0, "UTC", "t1")
        lid2 = db.upsert_location("b", 2.0, 2.0, "UTC", "t2")
        db.record_report(lid1, "daily", "loc1 report")
        assert db.get_last_report_time(lid2, "daily") is None


class TestGetLastAlertTime:
    def test_returns_none_when_no_alerts(self, location_id):
        assert db.get_last_alert_time(location_id, "rain") is None

    def test_returns_timestamp_after_alert(self, location_id):
        db.record_alert(location_id, "rain", "alert")
        assert db.get_last_alert_time(location_id, "rain") is not None

    def test_returns_most_recent(self, location_id):
        db.record_alert(location_id, "rain", "first")
        db.record_alert(location_id, "rain", "second")
        assert db.get_last_alert_time(location_id, "rain") is not None

    def test_filters_by_type(self, location_id):
        db.record_alert(location_id, "rain", "rain alert")
        assert db.get_last_alert_time(location_id, "wind") is None

    def test_filters_by_location(self):
        lid1 = db.upsert_location("a", 1.0, 1.0, "UTC", "t1")
        lid2 = db.upsert_location("b", 2.0, 2.0, "UTC", "t2")
        db.record_alert(lid1, "rain", "loc1 alert")
        assert db.get_last_alert_time(lid2, "rain") is None


class TestRequireEngine:
    def test_raises_before_init(self, tmp_path):
        from app import db as db_module
        original_engine = db_module._engine
        db_module._engine = None
        try:
            with pytest.raises(RuntimeError, match="db.init_db()"):
                db_module.get_reports()
        finally:
            db_module._engine = original_engine