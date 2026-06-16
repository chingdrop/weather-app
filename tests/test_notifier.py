from unittest.mock import patch

import pytest

import notifier


class TestNotifierConfig:
    def test_self_hosted_flag_determines_base_url(self):
        expected = "http://ntfy" if notifier.NTFY_SELF_HOSTED else "https://ntfy.sh"
        assert notifier.NTFY_BASE_URL == expected
        assert notifier._ntfy_api.config.base_url == expected


class TestSendNotification:
    def test_sends_correct_headers_and_body(self):
        with patch.object(notifier._ntfy_api, "post") as mock_post:
            notifier.send_notification("hello", topic="my-topic", title="T", priority="high", tags="tada")
        mock_post.assert_called_once_with(
            "/my-topic",
            data=b"hello",
            headers={"Title": "T", "Priority": "high", "Tags": "tada"},
        )

    def test_omits_missing_headers(self):
        with patch.object(notifier._ntfy_api, "post") as mock_post:
            notifier.send_notification("hello", topic="my-topic")
        mock_post.assert_called_once_with(
            "/my-topic",
            data=b"hello",
            headers={},
        )

    def test_uses_supplied_topic(self):
        with patch.object(notifier._ntfy_api, "post") as mock_post:
            notifier.send_notification("hello", topic="custom-topic")
        assert mock_post.call_args[0][0] == "/custom-topic"

    def test_raises_on_http_error(self):
        with patch.object(notifier._ntfy_api, "post", side_effect=Exception("503")):
            with pytest.raises(Exception, match="503"):
                notifier.send_notification("hello", topic="t")