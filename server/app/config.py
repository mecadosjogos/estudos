import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

_env_file = BASE_DIR / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

ROLE = os.environ.get("ROLE", "server")
DOMAIN = os.environ.get("DOMAIN", "localhost")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", ACCESS_TOKEN or "dev-secret-troque-isto")

def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path


DATABASE_PATH = _resolve(os.environ.get("DATABASE_PATH", "data/estudos.db"))
BACKUP_DIR = _resolve(os.environ.get("BACKUP_DIR", "backups"))
BACKUP_RETENTION = int(os.environ.get("BACKUP_RETENTION", "14"))

BUSY_TIMEOUT_MS = int(os.environ.get("BUSY_TIMEOUT_MS", "30000"))

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "claude-opus-5")
AI_MONTHLY_BUDGET_USD = float(os.environ.get("AI_MONTHLY_BUDGET_USD", "40"))

SESSION_COOKIE_NAME = "estudos_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 365  # 1 ano
