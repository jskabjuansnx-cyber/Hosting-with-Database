"""
Minimal Flask keep-alive server for Railway / Render hosting.
"""
import threading
import logging
from flask import Flask
from config import PORT

logger = logging.getLogger(__name__)
app = Flask(__name__)


@app.route("/")
def index():
    return "🤖 Bot is alive!", 200


@app.route("/health")
def health():
    return {"status": "ok"}, 200


def start():
    def _run():
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

    t = threading.Thread(target=_run, daemon=True, name="keep-alive")
    t.start()
    logger.info(f"Keep-alive server started on port {PORT}")
