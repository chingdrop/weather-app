import os

from app.adapter import RestAdapter, RestAdapterConfig

NTFY_SELF_HOSTED = os.environ.get("NTFY_SELF_HOSTED", "0") == "1"
NTFY_BASE_URL = "http://ntfy" if NTFY_SELF_HOSTED else "https://ntfy.sh"

_ntfy_api = RestAdapter(RestAdapterConfig(base_url=NTFY_BASE_URL, retries=2))


def send_notification(
        message: str,
        *,
        topic: str,
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
    _ntfy_api.post(f"/{topic}", data=message.encode("utf-8"), headers=headers)
