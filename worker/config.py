import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

_env_file = BASE_DIR / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

SERVER_URL = os.environ.get("SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")
WORKER_NAME = os.environ.get("WORKER_NAME", "worker-sem-nome")

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "large-v3")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cuda")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "float16")

POLL_INTERVAL_S = float(os.environ.get("WORKER_POLL_INTERVAL_S", "10"))
HEARTBEAT_INTERVAL_S = float(os.environ.get("WORKER_HEARTBEAT_INTERVAL_S", "60"))

# Serviço de TTS local (tts-service/, standalone) -- processo separado nesta
# mesma máquina, não o servidor Estudos. Só usado pelo alvo tts_guia.
TTS_SERVICE_URL = os.environ.get("TTS_SERVICE_URL", "http://127.0.0.1:8100").rstrip("/")

TMP_DIR = BASE_DIR / "worker" / "tmp"
ARCHIVE_DIR = BASE_DIR / "archive"
