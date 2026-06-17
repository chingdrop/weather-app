import pytest

from app import db as db_module
from app.helpers import (
    build_cfg, get_settings, parse_location_form,
    DAILY_REPORT_HOUR, EVENING_REPORT_HOUR, ALERT_INTERVAL_MIN,
)
from app.jobs import DB_RETAIN_DAYS
from app.monitor import (
    LocationConfig, LocationMonitor,
    RAIN_PROB_ALERT_PERCENT, UV_INDEX_ALERT, WIND_GUST_ALERT_MPH,
)


# ---------------------------------------------------------------------------
# get_settings
# ---------------------------------------------------------------------------

class TestGetSettings:
    def test_returns_module_defaults_when_db_empty(self):
        s = get_settings()
        assert s["daily_report_hour"] == DAILY_REPORT_HOUR
        assert s["evening_report_hour"] == EVENING_REPORT_HOUR
        assert s["alert_interval_min"] == ALERT_INTERVAL_MIN
        assert s["db_retain_days"] == DB_RETAIN_DAYS
        assert s["rain_prob_alert_percent"] == float(RAIN_PROB_ALERT_PERCENT)
        assert s["uv_index_alert"] == UV_INDEX_ALERT

    def test_db_value_overrides_default(self):
        db_module.set_setting("daily_report_hour", "9")
        assert get_settings()["daily_report_hour"] == 9

    def test_multiple_overrides(self):
        db_module.set_setting("alert_interval_min", "30")
        db_module.set_setting("wind_gust_alert_mph", "25")
        s = get_settings()
        assert s["alert_interval_min"] == 30
        assert s["wind_gust_alert_mph"] == 25.0

    def test_all_expected_keys_present(self):
        expected = {
            "daily_report_hour", "evening_report_hour", "alert_interval_min",
            "db_retain_days", "api_failure_notify_after",
            "rain_prob_alert_percent", "rain_amount_alert_in",
            "wind_gust_alert_mph", "heat_index_alert_f",
            "frost_temp_alert_f", "uv_index_alert",
        }
        assert set(get_settings().keys()) == expected


# ---------------------------------------------------------------------------
# build_cfg
# ---------------------------------------------------------------------------

class TestBuildCfg:
    def _loc(self, **overrides):
        db_module.upsert_location(
            name="test", lat=27.0, lon=-82.0,
            timezone="America/New_York", ntfy_topic="test-topic",
            **overrides,
        )
        return db_module.get_location_by_name("test")

    def test_returns_location_config_with_correct_identity(self):
        cfg = build_cfg(self._loc())
        assert isinstance(cfg, LocationConfig)
        assert cfg.name == "test"
        assert cfg.lat == 27.0

    def test_uses_global_default_when_no_per_location_override(self):
        cfg = build_cfg(self._loc())
        assert cfg.rain_prob_alert_percent == float(RAIN_PROB_ALERT_PERCENT)

    def test_per_location_value_takes_precedence(self):
        cfg = build_cfg(self._loc(rain_prob_alert_percent=75.0))
        assert cfg.rain_prob_alert_percent == 75.0

    def test_db_global_setting_overrides_module_default(self):
        db_module.set_setting("rain_prob_alert_percent", "60")
        cfg = build_cfg(self._loc())
        assert cfg.rain_prob_alert_percent == 60.0

    def test_per_location_value_overrides_db_global_setting(self):
        db_module.set_setting("rain_prob_alert_percent", "60")
        cfg = build_cfg(self._loc(rain_prob_alert_percent=80.0))
        assert cfg.rain_prob_alert_percent == 80.0

    def test_uv_index_is_int(self):
        cfg = build_cfg(self._loc())
        assert isinstance(cfg.uv_index_alert, int)


# ---------------------------------------------------------------------------
# parse_location_form
# ---------------------------------------------------------------------------

class TestParseLocationForm:
    def _form(self, **overrides):
        data = {
            "name": "Home",
            "lat": "27.3364",
            "lon": "-82.5307",
            "timezone": "America/New_York",
            "ntfy_topic": "my-topic",
        }
        data.update(overrides)
        return data

    def test_valid_form_parses_correctly(self):
        result = parse_location_form(self._form())
        assert result["name"] == "Home"
        assert result["lat"] == 27.3364
        assert result["lon"] == -82.5307
        assert result["timezone"] == "America/New_York"
        assert result["ntfy_topic"] == "my-topic"

    def test_missing_name_raises(self):
        with pytest.raises(ValueError, match="Name is required"):
            parse_location_form(self._form(name=""))

    def test_whitespace_only_name_raises(self):
        with pytest.raises(ValueError, match="Name is required"):
            parse_location_form(self._form(name="   "))

    def test_non_numeric_lat_raises(self):
        with pytest.raises(ValueError):
            parse_location_form(self._form(lat="not-a-number"))

    def test_lat_too_high_raises(self):
        with pytest.raises(ValueError, match="Latitude"):
            parse_location_form(self._form(lat="91"))

    def test_lat_too_low_raises(self):
        with pytest.raises(ValueError, match="Latitude"):
            parse_location_form(self._form(lat="-91"))

    def test_lon_too_high_raises(self):
        with pytest.raises(ValueError, match="Longitude"):
            parse_location_form(self._form(lon="181"))

    def test_missing_timezone_raises(self):
        with pytest.raises(ValueError, match="Timezone is required"):
            parse_location_form(self._form(timezone=""))

    def test_invalid_timezone_raises(self):
        with pytest.raises(ValueError, match="Unknown timezone"):
            parse_location_form(self._form(timezone="Not/Valid"))

    def test_missing_ntfy_topic_raises(self):
        with pytest.raises(ValueError, match="NTFY topic is required"):
            parse_location_form(self._form(ntfy_topic=""))

    def test_optional_thresholds_are_none_when_blank(self):
        result = parse_location_form(self._form())
        assert result["rain_prob_alert_percent"] is None
        assert result["rain_amount_alert_in"] is None
        assert result["wind_gust_alert_mph"] is None
        assert result["heat_index_alert_f"] is None
        assert result["frost_temp_alert_f"] is None
        assert result["uv_index_alert"] is None

    def test_optional_thresholds_parsed_when_provided(self):
        result = parse_location_form(self._form(
            rain_prob_alert_percent="75",
            wind_gust_alert_mph="35",
            uv_index_alert="9",
        ))
        assert result["rain_prob_alert_percent"] == 75.0
        assert result["wind_gust_alert_mph"] == 35.0
        assert result["uv_index_alert"] == 9


# ---------------------------------------------------------------------------
# LocationMonitor.create — threshold resolution
# ---------------------------------------------------------------------------

class TestLocationMonitorCreate:
    def _cfg(self, **overrides):
        return LocationConfig(
            name="test", lat=27.0, lon=-82.0,
            timezone="America/New_York", ntfy_topic="test-topic",
            **overrides,
        )

    def test_uses_module_default_when_cfg_has_no_threshold(self):
        monitor = LocationMonitor.create(1, self._cfg())
        wind = next(a for a in monitor.threshold_alerts if a.name == "wind")
        assert wind.threshold == WIND_GUST_ALERT_MPH

    def test_uses_cfg_threshold_when_set(self):
        monitor = LocationMonitor.create(1, self._cfg(wind_gust_alert_mph=25.0))
        wind = next(a for a in monitor.threshold_alerts if a.name == "wind")
        assert wind.threshold == 25.0

    def test_all_alert_types_created(self):
        monitor = LocationMonitor.create(1, self._cfg())
        names = {a.name for a in monitor.threshold_alerts}
        assert names == {"wind", "heat", "frost"}

    def test_all_alerts_includes_rain_and_thresholds(self):
        monitor = LocationMonitor.create(1, self._cfg())
        assert len(monitor.all_alerts) == 4  # rain + wind + heat + frost