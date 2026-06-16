import pytest

import db as db_module
import main as main_module
from config import LocationConfig
from jobs import LocationMonitor

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


@pytest.fixture
def location_id():
    return db_module.upsert_location(
        name=TEST_CFG.name,
        lat=TEST_CFG.lat,
        lon=TEST_CFG.lon,
        tz_name=TEST_CFG.timezone,
        ntfy_topic=TEST_CFG.ntfy_topic,
    )


@pytest.fixture
def monitor(location_id):
    m = LocationMonitor.create(location_id, TEST_CFG)
    main_module._monitors[TEST_CFG.name] = m
    yield m
    main_module._monitors.clear()