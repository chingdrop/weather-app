"""
Integration tests — require a running ntfy server.

Run with:
    RUN_INTEGRATION_TESTS=1 pytest -m integration

In the Docker Compose stack, ntfy is available at http://ntfy (internal) or
http://127.0.0.1:8080 (host). Set NTFY_BASE_URL accordingly before running.
"""
import os

import pytest
import requests

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True, scope="module")
def require_integration_env():
    if not os.environ.get("RUN_INTEGRATION_TESTS"):
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to run integration tests")


NTFY_BASE_URL = os.environ.get("NTFY_BASE_URL", "http://127.0.0.1:8080")


class TestNtfyConnection:
    def test_health_endpoint_returns_healthy(self):
        resp = requests.get(f"{NTFY_BASE_URL}/v1/health", timeout=5)
        assert resp.status_code == 200
        assert resp.json().get("healthy") is True

    def test_can_publish_to_topic(self):
        topic = os.environ.get("NTFY_TOPIC", "test-integration")
        resp = requests.post(
            f"{NTFY_BASE_URL}/{topic}",
            data=b"integration test",
            headers={"Title": "Integration Test", "Tags": "white_check_mark"},
            timeout=5,
        )
        assert resp.status_code == 200