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
# مكتبات Python الشائعة — module_name: pip_package_name
# None = مكتبة أساسية لا تحتاج تثبيت
TELEGRAM_MODULES = {
    # ─── Telegram frameworks ───────────────────────────────
    'telebot':              'pyTelegramBotAPI',
    'telegram':             'python-telegram-bot',
    'aiogram':              'aiogram',
    'pyrogram':             'pyrogram',
    'telethon':             'telethon',
    'tgcrypto':             'tgcrypto',
    # ─── HTTP / Web ────────────────────────────────────────
    'requests':             'requests',
    'aiohttp':              'aiohttp',
    'httpx':                'httpx',
    'flask':                'Flask',
    'fastapi':              'fastapi',
    'uvicorn':              'uvicorn',
    'django':               'Django',
    'starlette':            'starlette',
    'websockets':           'websockets',
    # ─── Data / Parsing ────────────────────────────────────
    'bs4':                  'beautifulsoup4',
    'lxml':                 'lxml',
    'pandas':               'pandas',
    'numpy':                'numpy',
    'matplotlib':           'matplotlib',
    'openpyxl':             'openpyxl',
    'xlrd':                 'xlrd',
    # ─── Database ──────────────────────────────────────────
    'sqlalchemy':           'SQLAlchemy',
    'pymongo':              'pymongo',
    'redis':                'redis',
    'psycopg2':             'psycopg2-binary',
    'motor':                'motor',
    'tortoise':             'tortoise-orm',
    # ─── Utilities ─────────────────────────────────────────
    'dotenv':               'python-dotenv',
    'yaml':                 'PyYAML',
    'toml':                 'toml',
    'dateutil':             'python-dateutil',
    'pytz':                 'pytz',
    'apscheduler':          'APScheduler',
    'schedule':             'schedule',
    'psutil':               'psutil',
    'pydantic':             'pydantic',
    'loguru':               'loguru',
    'colorama':             'colorama',
    'tqdm':                 'tqdm',
    'rich':                 'rich',
    # ─── Image / Media ─────────────────────────────────────
    'PIL':                  'Pillow',
    'cv2':                  'opencv-python',
    'qrcode':               'qrcode',
    # ─── Crypto / Security ─────────────────────────────────
    'cryptography':         'cryptography',
    'bcrypt':               'bcrypt',
    'jwt':                  'PyJWT',
    'nacl':                 'PyNaCl',
    # ─── Core Python (لا تحتاج تثبيت) ─────────────────────
    'asyncio':      None, 'json':       None, 'datetime':   None,
    'os':           None, 'sys':        None, 're':         None,
    'time':         None, 'math':       None, 'random':     None,
    'logging':      None, 'threading':  None, 'subprocess': None,
    'zipfile':      None, 'tempfile':   None, 'shutil':     None,
    'sqlite3':      None, 'atexit':     None, 'pathlib':    None,
    'collections':  None, 'itertools':  None, 'functools':  None,
    'typing':       None, 'abc':        None, 'io':         None,
    'copy':         None, 'hashlib':    None, 'hmac':       None,
    'base64':       None, 'struct':     None, 'socket':     None,
    'ssl':          None, 'urllib':     None, 'http':       None,
    'email':        None, 'html':       None, 'xml':        None,
    'csv':          None, 'configparser': None, 'argparse':  None,
    'unittest':     None, 'traceback':  None, 'inspect':    None,
    'ast':          None, 'dis':        None, 'gc':         None,
    'weakref':      None, 'contextlib': None, 'dataclasses': None,
    'enum':         None, 'string':     None, 'textwrap':   None,
    'pprint':       None, 'warnings':   None, 'signal':     None,
    'platform':     None, 'uuid':       None, 'decimal':    None,
    'fractions':    None, 'statistics': None, 'heapq':      None,
    'bisect':       None, 'array':      None, 'queue':      None,
    'multiprocessing': None, 'concurrent': None, 'asynchat': None,
    'pickle':       None, 'shelve':     None, 'dbm':        None,
    'ftplib':       None, 'imaplib':    None, 'smtplib':    None,
    'poplib':       None, 'telnetlib':  None, 'xmlrpc':     None,
}
