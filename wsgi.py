from main import NTFY_TOPIC, _startup, app  # noqa: F401

if not NTFY_TOPIC:
    raise SystemExit("NTFY_TOPIC environment variable is required — copy .env.example to .env and set it")

_startup()