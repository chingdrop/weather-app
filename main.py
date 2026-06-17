import os

from app import app
from app.startup import startup

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    startup()
    app.run(host=host, port=port, debug=debug, use_reloader=False)