import atexit
import logging
import os

from dotenv import load_dotenv

load_dotenv()

_dev = os.environ.get("FLASK_DEBUG", "0") == "1"

logging.basicConfig(
    level=logging.DEBUG if _dev else logging.WARNING,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from flask import Flask

import app.state as state


def create_app() -> Flask:
    flask_app = Flask(__name__)
    flask_app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

    from app.routes.api import api_bp
    from app.routes.setup import setup_bp
    from app.routes.config import config_bp

    flask_app.register_blueprint(api_bp)
    flask_app.register_blueprint(setup_bp)
    flask_app.register_blueprint(config_bp)

    atexit.register(
        lambda: state.scheduler.shutdown(wait=False)
        if state.scheduler and state.scheduler.running else None
    )

    return flask_app


app = create_app()
