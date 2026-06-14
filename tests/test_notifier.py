from unittest.mock import patch

import pytest

import notifier


class TestNotifierConfig:
    def test_adapter_base_url_matches_ntfy_base_url(self):
        assert notifier._ntfy_api.config.base_url == notifier.NTFY_BASE_URL

    def test_publish_endpoint_uses_topic(self):
        with patch.object(notifier._ntfy_api, "post") as mock_post:
            notifier.send_notification("hello")
        endpoint = mock_post.call_args[0][0]
        assert endpoint == f"/{notifier.NTFY_TOPIC}"


class TestSendNotification:
    def test_sends_correct_headers_and_body(self):
        with patch.object(notifier._ntfy_api, "post") as mock_post:
            notifier.send_notification("hello", title="T", priority="high", tags="tada")
        mock_post.assert_called_once_with(
            f"/{notifier.NTFY_TOPIC}",
            data=b"hello",
            headers={"Title": "T", "Priority": "high", "Tags": "tada"},
        )

    def test_omits_missing_headers(self):
        with patch.object(notifier._ntfy_api, "post") as mock_post:
            notifier.send_notification("hello")
        mock_post.assert_called_once_with(
            f"/{notifier.NTFY_TOPIC}",
            data=b"hello",
            headers={},
        )

    def test_raises_on_http_error(self):
        with patch.object(notifier._ntfy_api, "post", side_effect=Exception("503")):
            with pytest.raises(Exception, match="503"):
                notifier.send_notification("hello")
