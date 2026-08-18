import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# shared/ fica ao lado de server/ (fora do pacote app), não dentro dele — sem
# isso, `import shared.audio` (worker e o caminho de emergência da VPS usam)
# quebraria tanto localmente quanto no container.
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

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

# Ciclo de vida do áudio (PLANO.md): o original fica aqui só até um worker
# processar (fase 4); o mp3 comprimido fica em MEDIA_WEB_DIR para tocar no app.
MEDIA_ORIGINAL_DIR = _resolve(os.environ.get("MEDIA_ORIGINAL_DIR", "data/media/original"))
MEDIA_WEB_DIR = _resolve(os.environ.get("MEDIA_WEB_DIR", "data/media/web"))
UPLOAD_STAGING_DIR = _resolve(os.environ.get("UPLOAD_STAGING_DIR", "data/uploads"))
UPLOAD_CHUNK_MAX_BYTES = int(os.environ.get("UPLOAD_CHUNK_MAX_BYTES", str(8 * 1024 * 1024)))
# ffmpeg (fase 4) lê o áudio de qualquer um desses contêineres, então a lista é
# generosa de propósito: o gargalo real de qualidade é o Whisper, não o formato
# do arquivo. .mp4/.mov cobrem apps que gravam aula como vídeo sem querer.
UPLOAD_ALLOWED_EXTENSIONS = {
    ".m4a", ".mp3", ".wav", ".opus", ".aac", ".ogg", ".flac", ".mp4", ".mov", ".webm", ".3gp",
}

BUSY_TIMEOUT_MS = int(os.environ.get("BUSY_TIMEOUT_MS", "30000"))

# Válvula de emergência "transcrever na VPS agora" (fase 4) — CPU, modelo
# médio, mais lento e um pouco pior que o large-v3 na GPU do worker.
WHISPER_VPS_MODEL = os.environ.get("WHISPER_VPS_MODEL", "medium")
WHISPER_VPS_COMPUTE_TYPE = os.environ.get("WHISPER_VPS_COMPUTE_TYPE", "int8")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "claude-opus-5")
AI_MONTHLY_BUDGET_USD = float(os.environ.get("AI_MONTHLY_BUDGET_USD", "40"))

# Teto diário da fila de revisão (fase 7) — sem isso, sumir uma semana
# devolve uma fila impagável e você desiste dela.
REVIEW_DAILY_CAP = int(os.environ.get("REVIEW_DAILY_CAP", "40"))

SESSION_COOKIE_NAME = "estudos_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 365  # 1 ano
