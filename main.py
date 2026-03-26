"""
Entry point — initialises DB, starts keep-alive, registers handlers, runs bot.
"""
import logging
import signal
import sys

from telegram.ext import Application

import database as db
import runner
import keep_alive
from config import BOT_TOKEN, OWNER_ID
from handlers import user, files, admin
from utils.cleaner import run_system_cleanup

# ─── Logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ─── Startup / Shutdown ─────────────────────────────────────

async def on_startup(app: Application):
    logger.info("Bot starting up...")
    runner.restore_running_scripts()
    logger.info("Bot ready.")


async def on_shutdown(app: Application):
    logger.info("Bot shutting down — stopping all scripts...")
    runner.stop_all()


# ─── Main ───────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN is not set. Exiting.")
        sys.exit(1)
    if not OWNER_ID:
        logger.critical("OWNER_ID is not set. Exiting.")
        sys.exit(1)

    # Init DB
    db.init_db(OWNER_ID)

    # Keep-alive server (Railway / Render)
    keep_alive.start()

    # Build application
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    # Register handlers (order matters — admin before generic text)
    admin.register(app)
    files.register(app)
    user.register(app)

    # Schedule background cleanup system (Disk and RAM saver for Free Tiers)
    # Runs every 5 hours (18000 seconds), starts 1 hour (3600 seconds) after boot.
    app.job_queue.run_repeating(run_system_cleanup, interval=18000, first=3600)

    # Graceful shutdown on SIGTERM (Railway sends this)
    def _handle_signal(sig, frame):
        logger.info(f"Received signal {sig}. Stopping...")
        runner.stop_all()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    logger.info("Starting polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
