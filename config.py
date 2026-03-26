import os
from dotenv import load_dotenv

load_dotenv()

# ─── Telegram ───────────────────────────────────────────────
BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
OWNER_ID    = int(os.getenv("OWNER_ID", "0"))
YOUR_USERNAME = os.getenv("YOUR_USERNAME", "@P_X_24")
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "https://t.me/Raven_xx24")
WELCOME_PHOTO = os.getenv("WELCOME_PHOTO", "")  # رابط صورة الترحيب

# ─── Database ───────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/bot.db")

# ─── Paths ──────────────────────────────────────────────────
BASE_DIR        = os.path.abspath(os.path.dirname(__file__))
SCRIPTS_DIR     = os.path.join(BASE_DIR, "scripts")
LOGS_DIR        = os.path.join(BASE_DIR, "logs")

DATA_DIR = os.path.join(BASE_DIR, "data")

os.makedirs(SCRIPTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR,    exist_ok=True)
os.makedirs(DATA_DIR,    exist_ok=True)

# ─── Limits ─────────────────────────────────────────────────
FREE_FILE_LIMIT  = int(os.getenv("FREE_FILE_LIMIT",  "1"))  # مجاني: ملف واحد فقط
PAID_FILE_LIMIT  = int(os.getenv("PAID_FILE_LIMIT",  "15")) # مدفوع: قابل للتعديل
ADMIN_FILE_LIMIT = 999
MAX_PROCESSES    = int(os.getenv("MAX_PROCESSES",    "50"))
SCRIPT_TIMEOUT   = int(os.getenv("SCRIPT_TIMEOUT",  "0"))   # 0 = no timeout

# ─── Security ───────────────────────────────────────────────
DANGEROUS_PATTERNS = [
    r"os\.system\s*\(",
    r"subprocess\.call\s*\(\s*['\"]rm\s+-rf",
    r"shutil\.rmtree\s*\(\s*['\"/]",
    r"open\s*\(\s*['\"]\/etc",
    r"__import__\s*\(\s*['\"]os['\"]",
    r"eval\s*\(",
    r"exec\s*\(",
]

# ─── Keep-Alive ─────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 8080))

# ─── Auto Package Installation ──────────────────────────────
TELEGRAM_MODULES = {
    'telebot': 'pyTelegramBotAPI',
    'telegram': 'python-telegram-bot',
    'python_telegram_bot': 'python-telegram-bot',
    'aiogram': 'aiogram',
    'pyrogram': 'pyrogram',
    'telethon': 'telethon',
    'bs4': 'beautifulsoup4',
    'requests': 'requests',
    'pillow': 'Pillow',
    'cv2': 'opencv-python',
    'yaml': 'PyYAML',
    'dotenv': 'python-dotenv',
    'dateutil': 'python-dateutil',
    'pandas': 'pandas',
    'numpy': 'numpy',
    'flask': 'Flask',
    'django': 'Django',
    'sqlalchemy': 'SQLAlchemy',
    'psutil': 'psutil',
    'apscheduler': 'apscheduler',
    'pytz': 'pytz',
    'requests': 'requests',
    'bs4': 'beautifulsoup4',
    'numpy': 'numpy',
    'pandas': 'pandas',
    'matplotlib': 'matplotlib',
    'PIL': 'Pillow',
    'dotenv': 'python-dotenv',
    'aiohttp': 'aiohttp',
    'redis': 'redis',
    'pymongo': 'pymongo',
    'mysql': 'mysql-connector-python',
    'psycopg2': 'psycopg2-binary',
    'telebot': 'pyTelegramBotAPI',
    'pyrogram': 'pyrogram',
    'tgcrypto': 'tgcrypto',
    'flask': 'Flask',
    'fastapi': 'fastapi',
    'uvicorn': 'uvicorn',
    'bcrypt': 'bcrypt',
    'cryptography': 'cryptography',
    'yaml': 'pyyaml',
    'dateutil': 'python-dateutil',
    # Core modules (no installation needed)
    'asyncio': None, 'json': None, 'datetime': None, 'os': None,
    'sys': None, 're': None, 'time': None, 'math': None,
    'random': None, 'logging': None, 'threading': None,
    'subprocess': None, 'zipfile': None, 'tempfile': None,
    'shutil': None, 'sqlite3': None, 'atexit': None
}
