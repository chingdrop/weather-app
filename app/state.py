from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from monitor import LocationMonitor

monitors: dict[str, LocationMonitor] = {}
scheduler: BackgroundScheduler | None = None