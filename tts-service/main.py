"""Serviço de TTS local, standalone -- não conhece o Estudos.

Carrega o XTTS v2 (Coqui) uma vez no início e mantém em memória (GPU). Não
tem nenhum conceito do app Estudos aqui dentro (nada de aula, guia, job) --
é só "texto entra, mp3 sai", pra qualquer script na máquina poder chamar via
HTTP, não só o worker de transcrição do Estudos.

Uso: uvicorn main:app --host 127.0.0.1 --port 8100  (ou tts-service\\iniciar.ps1)
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
LANGUAGE = "pt"

app = FastAPI(title="TTS local")

_tts = None


def _load_model():
    global _tts
    if _tts is None:
        from TTS.api import TTS

        _tts = TTS(MODEL_NAME).to("cuda")
    return _tts


@app.on_event("startup")
def _startup():
    _load_model()


class SynthesizeBody(BaseModel):
    texto: str
    speaker: str | None = None


@app.get("/healthz")
def healthz():
    return {"ok": _tts is not None, "model": MODEL_NAME}


@app.get("/speakers")
def speakers():
    """Vozes embutidas disponíveis sem precisar de wav de referência --
    lista vazia significa que este modelo/versão não expõe speaker embutido
    nenhum (aí `POST /synthesize` exigiria clonar voz, fora do escopo de
    hoje)."""
    tts = _load_model()
    return {"speakers": list(getattr(tts, "speakers", None) or [])}


@app.post("/synthesize")
def synthesize(body: SynthesizeBody):
    tts = _load_model()
    texto = body.texto.strip()
    if not texto:
        raise HTTPException(status_code=400, detail="texto vazio")

    available = list(getattr(tts, "speakers", None) or [])
    speaker = body.speaker or (available[0] if available else None)
    if speaker is not None and available and speaker not in available:
        raise HTTPException(status_code=400, detail=f"speaker desconhecido: {speaker}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="tts-"))
    try:
        wav_path = tmp_dir / "out.wav"
        mp3_path = tmp_dir / "out.mp3"
        tts.tts_to_file(text=texto, speaker=speaker, language=LANGUAGE, file_path=str(wav_path))
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-qscale:a", "2", str(mp3_path)],
            check=True,
            capture_output=True,
        )
        data = mp3_path.read_bytes()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return Response(content=data, media_type="audio/mpeg")
