from unittest.mock import patch

import weather
from weather import compass


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
        with patch("weather.fetch") as mock_fetch:
            mock_fetch.return_value = {}
            weather.fetch_rain_check_weather()
        params = mock_fetch.call_args[0][0]
        assert params["forecast_days"] == 1
        assert "precipitation_probability" in params["hourly"]
        assert "wind_gusts_10m" in params["hourly"]
        assert "apparent_temperature" in params["hourly"]
        assert "wind_gusts_10m" in params["current"]
        assert "apparent_temperature" in params["current"]

    def test_fetch_report_weather_params(self):
        with patch("weather.fetch") as mock_fetch:
            mock_fetch.return_value = {}
            weather.fetch_report_weather()
        params = mock_fetch.call_args[0][0]
        assert params["forecast_days"] == 2
        assert "apparent_temperature_max" in params["daily"]
        assert "wind_gusts_10m_max" in params["daily"]
        assert "rain_sum" in params["daily"]
        assert "sunrise" in params["daily"]
        assert "sunset" in params["daily"]
        assert "wind_gusts_10m" in params["current"]
