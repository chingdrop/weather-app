from unittest.mock import patch

from app import weather
from app.weather import compass

LAT, LON, TZ = 27.3364, -82.5307, "America/New_York"


class TestCompass:
    def test_north(self):
        assert compass(0) == "N"
        assert compass(360) == "N"

    def test_northeast(self):
        assert compass(45) == "NE"

    def test_east(self):
        assert compass(90) == "E"

    def test_south(self):
        assert compass(180) == "S"

    def test_southwest(self):
        assert compass(225) == "SW"


class TestFetchHelpers:
    def test_fetch_rain_check_weather_params(self):
        with patch("app.weather.fetch") as mock_fetch:
            mock_fetch.return_value = {}
            weather.fetch_rain_check_weather(LAT, LON, TZ)
        extra = mock_fetch.call_args[0][3]
        assert extra["forecast_days"] == 1
        assert "precipitation_probability" in extra["hourly"]
        assert "wind_gusts_10m" in extra["hourly"]
        assert "apparent_temperature" in extra["hourly"]
        assert "wind_gusts_10m" in extra["current"]
        assert "apparent_temperature" in extra["current"]

    def test_fetch_report_weather_params(self):
        with patch("app.weather.fetch") as mock_fetch:
            mock_fetch.return_value = {}
            weather.fetch_report_weather(LAT, LON, TZ)
        extra = mock_fetch.call_args[0][3]
        assert extra["forecast_days"] == 2
        assert "apparent_temperature_max" in extra["daily"]
        assert "wind_gusts_10m_max" in extra["daily"]
        assert "rain_sum" in extra["daily"]
        assert "sunrise" in extra["daily"]
        assert "sunset" in extra["daily"]
        assert "wind_gusts_10m" in extra["current"]

    def test_fetch_passes_coordinates(self):
        with patch("app.weather._weather_api") as mock_api:
            mock_api.get.return_value = {}
            weather.fetch(LAT, LON, TZ, {"forecast_days": 1})
        params = mock_api.get.call_args.kwargs["params"]
        assert params["latitude"] == LAT
        assert params["longitude"] == LON
        assert params["timezone"] == TZ