from unittest.mock import MagicMock, patch

import pytest

from app import app as flask_app
from app import db as db_module
import app.startup as startup_module
from app.startup import start_scheduler
from conftest import TEST_CFG


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_scheduler():
    """Ensure no real scheduler or monitor state is left running between tests."""
    yield
    if startup_module.scheduler and startup_module.scheduler.running:
        startup_module.scheduler.shutdown(wait=False)
    startup_module.scheduler = None
    startup_module.monitors.clear()


_VALID_LOCATION = {
    "name": "Home",
    "lat": "27.3364",
    "lon": "-82.5307",
    "timezone": "America/New_York",
    "ntfy_topic": "my-topic",
}


# ---------------------------------------------------------------------------
# /setup
# ---------------------------------------------------------------------------

class TestSetupRoute:
    def test_get_renders_form_when_no_monitors(self, client):
        resp = client.get("/setup")
        assert resp.status_code == 200

    def test_get_redirects_when_monitors_already_exist(self, client, monitor):
        resp = client.get("/setup")
        assert resp.status_code == 302
        assert "/config/locations" in resp.headers["Location"]

    def test_post_creates_location_and_redirects(self, client):
        with patch("app.routes.setup.start_scheduler"), \
             patch("app.routes.setup.send_daily_report"):
            resp = client.post("/setup", data=_VALID_LOCATION)
        assert resp.status_code == 302
        assert db_module.get_location_by_name("Home") is not None

    def test_post_adds_monitor_to_startup_state(self, client):
        with patch("app.routes.setup.start_scheduler"), \
             patch("app.routes.setup.send_daily_report"):
            client.post("/setup", data=_VALID_LOCATION)
        assert "Home" in startup_module.monitors

    def test_post_invalid_form_rerenders(self, client):
        resp = client.post("/setup", data={**_VALID_LOCATION, "name": ""})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /config/locations
# ---------------------------------------------------------------------------

class TestConfigLocationsRoute:
    def test_get_renders(self, client):
        assert client.get("/config/locations").status_code == 200

    def test_get_new_renders(self, client):
        assert client.get("/config/locations/new").status_code == 200

    def test_post_new_creates_location_and_redirects(self, client):
        resp = client.post("/config/locations/new", data=_VALID_LOCATION)
        assert resp.status_code == 302
        assert db_module.get_location_by_name("Home") is not None

    def test_post_new_duplicate_name_rerenders_with_error(self, client, location_id):
        resp = client.post("/config/locations/new", data={
            **_VALID_LOCATION, "name": TEST_CFG.name,
        })
        assert resp.status_code == 200

    def test_post_new_invalid_form_rerenders(self, client):
        resp = client.post("/config/locations/new", data={**_VALID_LOCATION, "timezone": "Bad/Zone"})
        assert resp.status_code == 200

    def test_get_edit_renders_for_known_location(self, client, location_id):
        assert client.get(f"/config/locations/{TEST_CFG.name}").status_code == 200

    def test_get_edit_redirects_for_unknown_location(self, client):
        resp = client.get("/config/locations/nowhere")
        assert resp.status_code == 302

    def test_post_edit_updates_db(self, client, location_id):
        client.post(f"/config/locations/{TEST_CFG.name}", data={
            **_VALID_LOCATION, "name": TEST_CFG.name, "ntfy_topic": "updated-topic",
        })
        assert db_module.get_location_by_name(TEST_CFG.name).ntfy_topic == "updated-topic"

    def test_post_edit_updates_in_memory_monitor(self, client, monitor):
        client.post(f"/config/locations/{TEST_CFG.name}", data={
            **_VALID_LOCATION, "name": TEST_CFG.name, "ntfy_topic": "new-topic",
        })
        assert monitor.cfg.ntfy_topic == "new-topic"

    def test_post_edit_updates_threshold_alert(self, client, monitor):
        client.post(f"/config/locations/{TEST_CFG.name}", data={
            **_VALID_LOCATION, "name": TEST_CFG.name, "wind_gust_alert_mph": "99",
        })
        wind = next(a for a in monitor.threshold_alerts if a.name == "wind")
        assert wind.threshold == 99.0

    def test_delete_removes_location_from_db(self, client, location_id):
        client.post(f"/config/locations/{TEST_CFG.name}/delete")
        assert db_module.get_location_by_name(TEST_CFG.name) is None

    def test_delete_removes_monitor_from_state(self, client, monitor):
        client.post(f"/config/locations/{TEST_CFG.name}/delete")
        assert TEST_CFG.name not in startup_module.monitors

    def test_delete_unknown_location_redirects(self, client):
        resp = client.post("/config/locations/nowhere/delete")
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# /config/settings
# ---------------------------------------------------------------------------

_VALID_SETTINGS = {
    "daily_report_hour": "8",
    "evening_report_hour": "22",
    "alert_interval_min": "30",
    "db_retain_days": "60",
    "api_failure_notify_after": "5",
    "rain_prob_alert_percent": "60",
    "rain_amount_alert_in": "0.1",
    "wind_gust_alert_mph": "35",
    "heat_index_alert_f": "105",
    "frost_temp_alert_f": "32",
    "uv_index_alert": "9",
}


class TestConfigSettingsRoute:
    def test_get_renders(self, client):
        assert client.get("/config/settings").status_code == 200

    def test_post_saves_all_settings_to_db(self, client):
        client.post("/config/settings", data=_VALID_SETTINGS)
        assert db_module.get_setting("daily_report_hour") == "8"
        assert float(db_module.get_setting("wind_gust_alert_mph")) == 35.0

    def test_post_redirects_on_success(self, client):
        resp = client.post("/config/settings", data=_VALID_SETTINGS)
        assert resp.status_code == 302

    def test_post_invalid_value_rerenders(self, client):
        resp = client.post("/config/settings", data={**_VALID_SETTINGS, "daily_report_hour": "not-a-number"})
        assert resp.status_code == 200

    def test_post_missing_field_rerenders(self, client):
        incomplete = {k: v for k, v in _VALID_SETTINGS.items() if k != "uv_index_alert"}
        resp = client.post("/config/settings", data=incomplete)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /restart
# ---------------------------------------------------------------------------

class TestRestartRoute:
    def test_returns_restarting_status(self, client):
        with patch("app.routes.api.threading.Thread"):
            resp = client.post("/restart")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "restarting"

    def test_spawns_background_thread(self, client):
        with patch("app.routes.api.threading.Thread") as mock_thread:
            client.post("/restart")
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()


# ---------------------------------------------------------------------------
# start_scheduler
# ---------------------------------------------------------------------------

class TestStartScheduler:
    def test_creates_correct_number_of_jobs(self, monitor):
        with patch("app.startup.BackgroundScheduler") as mock_cls:
            mock_sched = mock_cls.return_value
            start_scheduler()
        # 3 jobs per monitor (daily, evening, alerts) + 1 prune job
        assert mock_sched.add_job.call_count == 4
        mock_sched.start.assert_called_once()

    def test_shuts_down_existing_running_scheduler(self, monitor):
        old = MagicMock()
        old.running = True
        startup_module.scheduler = old
        with patch("app.startup.BackgroundScheduler"):
            start_scheduler()
        old.shutdown.assert_called_once_with(wait=False)

    def test_skips_shutdown_when_no_existing_scheduler(self, monitor):
        startup_module.scheduler = None
        with patch("app.startup.BackgroundScheduler"):
            start_scheduler()  # should not raise

    def test_job_count_scales_with_monitor_count(self, monitor):
        lid2 = db_module.upsert_location("second", 28.0, -83.0, "UTC", "t2")
        from app.monitor import LocationMonitor
        from app.helpers import build_cfg
        loc2 = db_module.get_location_by_name("second")
        startup_module.monitors["second"] = LocationMonitor.create(lid2, build_cfg(loc2))

        try:
            with patch("app.startup.BackgroundScheduler") as mock_cls:
                mock_sched = mock_cls.return_value
                start_scheduler()
            # 2 monitors × 3 jobs + 1 prune = 7
            assert mock_sched.add_job.call_count == 7
        finally:
            startup_module.monitors.pop("second", None)