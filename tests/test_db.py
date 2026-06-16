import sqlite3

import db


class TestInitDb:
    def test_creates_weather_events_table(self):
        with sqlite3.connect(db.DB_PATH) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='weather_events'"
            ).fetchone()
        assert row is not None

    def test_idempotent(self):
        db.init_db()
        db.init_db()


class TestRecordEvent:
    def test_inserts_row(self):
        db.record_event("daily_report", "Hello world")
        events = db.get_events()
        assert len(events) == 1
        assert events[0]["type"] == "daily_report"
        assert events[0]["message"] == "Hello world"
        assert events[0]["created_at"] is not None

    def test_multiple_events(self):
        db.record_event("rain_alert", "Rain incoming")
        db.record_event("wind_alert", "Wind incoming")
        assert len(db.get_events()) == 2


class TestGetEvents:
    def test_returns_most_recent_first(self):
        db.record_event("daily_report", "first")
        db.record_event("daily_report", "second")
        events = db.get_events()
        assert events[0]["message"] == "second"
        assert events[1]["message"] == "first"

    def test_filter_by_type(self):
        db.record_event("daily_report", "report")
        db.record_event("rain_alert", "alert")
        events = db.get_events(event_type="rain_alert")
        assert len(events) == 1
        assert events[0]["type"] == "rain_alert"

    def test_limit(self):
        for i in range(5):
            db.record_event("quick_report", f"msg {i}")
        assert len(db.get_events(limit=3)) == 3

    def test_empty_returns_empty_list(self):
        assert db.get_events() == []

    def test_unknown_type_filter_returns_empty(self):
        db.record_event("daily_report", "report")
        assert db.get_events(event_type="unknown_type") == []