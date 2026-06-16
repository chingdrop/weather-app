import pytest

import db as db_module


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    db_file = tmp_path / "test.db"
    original = db_module.DB_PATH
    db_module.DB_PATH = str(db_file)
    db_module.init_db()
    yield
    db_module.DB_PATH = original