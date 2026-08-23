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
SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-secret-troque-isto")

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

# Sync do Drive (fase 9) — JSON da service account inteiro (não um caminho:
# a VPS não precisa de mais um arquivo de credencial pra proteger separado
# do .env) e o id da pasta raiz ("Faculdade") compartilhada com ela.
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_DRIVE_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

# Onde ficam os arquivos de material enviados à mão (PDF, foto) — origem=link
# e origem=gdoc não usam isto, só guardam URL/markdown sincronizado.
MATERIAL_FILES_DIR = _resolve(os.environ.get("MATERIAL_FILES_DIR", "data/materials"))

# Teto diário da fila de revisão (fase 7) — sem isso, sumir uma semana
# devolve uma fila impagável e você desiste dela.
REVIEW_DAILY_CAP = int(os.environ.get("REVIEW_DAILY_CAP", "40"))

# Feynman por voz (fase 13) — modelo pequeno, não o "medium" da válvula de
# emergência (WHISPER_VPS_MODEL acima): ~60s de gravação saem em poucos
# segundos até na CPU da VPS, e a precisão importa menos aqui porque a IA
# compara sentido contra a definição do professor, não usa a transcrição
# como fonte de estudo.
WHISPER_SHORT_MODEL = os.environ.get("WHISPER_SHORT_MODEL", "small")
WHISPER_SHORT_COMPUTE_TYPE = os.environ.get("WHISPER_SHORT_COMPUTE_TYPE", "int8")
FEYNMAN_AUDIO_DIR = _resolve(os.environ.get("FEYNMAN_AUDIO_DIR", "data/media/feynman"))

# Destaques em áudio (fase 15) -- clipes cortados sob demanda do mp3 já
# comprimido da aula (nunca do original, que a VPS já apagou -- fase 4),
# cacheados aqui pra não recortar de novo a cada replay.
DESTAQUES_CLIPS_DIR = _resolve(os.environ.get("DESTAQUES_CLIPS_DIR", "data/media/destaques"))

SESSION_COOKIE_NAME = "estudos_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 365  # 1 ano
