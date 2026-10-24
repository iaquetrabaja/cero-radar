import os
from pathlib import Path
from cero.market import PROFILE

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env()
DATA = Path(os.environ.get('CERO_DATA_DIR',str(ROOT / 'data')))
DATA.mkdir(parents=True,exist_ok=True)
DB_PATH = DATA / 'cero.db'

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_BUDGET_EUR = max(0, min(3.0, float(os.environ.get("GEMINI_DAILY_BUDGET_EUR", "3"))))
BUDGET_TIMEZONE = os.environ.get('BUDGET_TIMEZONE') or PROFILE['timezone']
GEMINI_MODEL = "gemini-2.5-flash-lite"
AMAZON_ASSOCIATE_TAG = os.environ.get('AMAZON_ASSOCIATE_TAG','')
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
