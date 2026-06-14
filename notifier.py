import os

from adapter import RestAdapter, RestAdapterConfig

NTFY_BASE_URL = os.environ.get("NTFY_BASE_URL", "https://ntfy.sh")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

_ntfy_api = RestAdapter(RestAdapterConfig(base_url=NTFY_BASE_URL, retries=2))


def send_notification(
        message: str,
        title: str | None = None,
        priority: str | None = None,
        tags: str | None = None,
) -> None:
    headers = {}
    if title:
        headers["Title"] = title
    if priority:
        headers["Priority"] = priority
    if tags:
        headers["Tags"] = tags
    _ntfy_api.post(f"/{NTFY_TOPIC}", data=message.encode("utf-8"), headers=headers)