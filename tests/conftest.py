import pytest

from app import db as db_module
import app.startup as startup_module
from app.monitor import LocationConfig
from app.monitor import LocationMonitor

TEST_CFG = LocationConfig(
    name="test",
    lat=27.3364,
    lon=-82.5307,
    timezone="America/New_York",
    ntfy_topic="test-topic",
)


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    db_file = tmp_path / "test.db"
    original_path = db_module.DB_PATH
    original_engine = db_module._engine
    db_module.DB_PATH = str(db_file)
    db_module._engine = None
    db_module.init_db()
    yield
    db_module.DB_PATH = original_path
    db_module._engine = original_engine
    startup_module.monitors.clear()


@pytest.fixture
def location_id():
    return db_module.upsert_location(
        name=TEST_CFG.name,
        lat=TEST_CFG.lat,
        lon=TEST_CFG.lon,
        timezone=TEST_CFG.timezone,
        ntfy_topic=TEST_CFG.ntfy_topic,
    )


@pytest.fixture
def monitor(location_id):
    m = LocationMonitor.create(location_id, TEST_CFG)
    startup_module.monitors[TEST_CFG.name] = m
    yield m
    startup_module.monitors.clear()