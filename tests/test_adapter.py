import pytest
from unittest.mock import MagicMock, patch

import requests

from adapter import RestAdapter, RestAdapterConfig


@pytest.fixture
def adapter():
    return RestAdapter(RestAdapterConfig(base_url="https://example.com"))


class TestRestAdapterRequest:
    def _mock_response(self, status=200, json_data=None, text=None, content_type="application/json"):
        resp = MagicMock()
        resp.status_code = status
        resp.headers = {"Content-Type": content_type}
        resp.raise_for_status = MagicMock()
        if json_data is not None:
            resp.json.return_value = json_data
        if text is not None:
            resp.text = text
        return resp

    def test_get_returns_json(self, adapter):
        resp = self._mock_response(json_data={"key": "value"})
        with patch.object(adapter.session, "request", return_value=resp) as mock_req:
            result = adapter.get("/endpoint", params={"a": "1"})
        assert result == {"key": "value"}
        mock_req.assert_called_once()
        args, kwargs = mock_req.call_args
        assert kwargs["method"] == "GET"
        assert "endpoint" in kwargs["url"]

    def test_post_returns_bytes_for_unknown_content_type(self, adapter):
        resp = self._mock_response(content_type="application/octet-stream")
        resp.content = b"\x00\x01"
        with patch.object(adapter.session, "request", return_value=resp):
            result = adapter.post("/upload", data=b"\x00\x01")
        assert result == b"\x00\x01"

    def test_returns_text_for_text_content_type(self, adapter):
        resp = self._mock_response(content_type="text/plain")
        resp.text = "hello"
        with patch.object(adapter.session, "request", return_value=resp):
            result = adapter.get("/text")
        assert result == "hello"

    def test_raises_on_http_error(self, adapter):
        resp = self._mock_response(status=500)
        resp.raise_for_status.side_effect = requests.HTTPError("500")
        with patch.object(adapter.session, "request", return_value=resp):
            with pytest.raises(requests.HTTPError):
                adapter.get("/bad")

    def test_custom_timeout_overrides_config(self, adapter):
        resp = self._mock_response(json_data={})
        with patch.object(adapter.session, "request", return_value=resp) as mock_req:
            adapter.get("/endpoint", timeout=99.0)
        assert mock_req.call_args.kwargs["timeout"] == 99.0

    def test_default_timeout_from_config(self, adapter):
        resp = self._mock_response(json_data={})
        with patch.object(adapter.session, "request", return_value=resp) as mock_req:
            adapter.get("/endpoint")
        assert mock_req.call_args.kwargs["timeout"] == adapter.config.timeout

    def test_extra_headers_merged(self, adapter):
        resp = self._mock_response(json_data={})
        with patch.object(adapter.session, "request", return_value=resp) as mock_req:
            adapter.post("/endpoint", headers={"X-Custom": "yes"})
        sent_headers = mock_req.call_args.kwargs["headers"]
        assert sent_headers.get("X-Custom") == "yes"