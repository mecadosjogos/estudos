"""Serviço de TTS local, standalone -- não conhece o Estudos.

Chatterbox Multilingual v3 (Resemble AI, MIT) -- diferente do F5-TTS
(abandonado nesta troca: produzia áudio embaralhado em PT-BR mesmo depois
de eliminar toda causa de configuração, com dois checkpoints comunitários
diferentes -- ver histórico da conversa), este modelo tem um parâmetro
explícito de idioma (`language_id="pt"`), não depende só do fine-tune/
referência pra "adivinhar" o idioma. Clonagem de voz a partir de um clipe
de referência (`vozes/<nome>/ref.wav`) -- aqui não precisa de transcrição
do áudio de referência (`ref_text`), diferente do F5-TTS.

Cada voz clonada vive em `vozes/<nome>/ref.wav` -- fora do git de
propósito (`.gitignore`), é dado biométrico pessoal, nunca sobe pra VPS.

Uso: uvicorn main:app --host 127.0.0.1 --port 8100  (ou tts-service\\iniciar.ps1)
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

VOZES_DIR = Path(__file__).resolve().parent / "vozes"
DEFAULT_VOZ = "wyver"
LANGUAGE_ID = "pt"
MAX_CHUNK_CHARS = 300

app = FastAPI(title="TTS local")

_model = None


def _load_model():
    global _model
    if _model is None:
        import torch
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model = ChatterboxMultilingualTTS.from_pretrained(device=device)
    return _model


@app.on_event("startup")
def _startup():
    _load_model()


def _vozes_disponiveis() -> list[str]:
    if not VOZES_DIR.exists():
        return []
    return sorted(p.name for p in VOZES_DIR.iterdir() if (p / "ref.wav").exists())


class SynthesizeBody(BaseModel):
    texto: str
    speaker: str | None = None


@app.get("/healthz")
def healthz():
    return {"ok": _model is not None, "model": "ChatterboxMultilingualTTS"}


@app.get("/speakers")
def speakers():
    """Vozes clonadas disponíveis (pastas em vozes/, cada uma com um
    clipe de referência de verdade) -- é sempre clonagem, não tem voz
    embutida genérica."""
    return {"speakers": _vozes_disponiveis()}


def _split_into_chunks(texto: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", texto.strip()) if s]
    chunks: list[str] = []
    current = ""
    for s in sentences:
        if current and len(current) + len(s) + 1 > max_chars:
            chunks.append(current)
            current = s
        else:
            current = f"{current} {s}".strip()
    if current:
        chunks.append(current)
    return chunks or [texto]


@app.post("/synthesize")
def synthesize(body: SynthesizeBody):
    model = _load_model()
    texto = body.texto.strip()
    if not texto:
        raise HTTPException(status_code=400, detail="texto vazio")

    voz = body.speaker or DEFAULT_VOZ
    ref_wav = VOZES_DIR / voz / "ref.wav"
    if not ref_wav.exists():
        raise HTTPException(status_code=400, detail=f"voz desconhecida ou sem referência: {voz}")

    pieces = []
    for chunk in _split_into_chunks(texto):
        wav = model.generate(chunk, language_id=LANGUAGE_ID, audio_prompt_path=str(ref_wav))
        pieces.append(wav.squeeze(0).cpu().numpy())

    full = pieces[0] if len(pieces) == 1 else np.concatenate(pieces)

    tmp_dir = Path(tempfile.mkdtemp(prefix="tts-"))
    try:
        wav_path = tmp_dir / "out.wav"
        mp3_path = tmp_dir / "out.mp3"
        sf.write(wav_path, full, model.sr)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-qscale:a", "2", str(mp3_path)],
            check=True,
            capture_output=True,
        )
        data = mp3_path.read_bytes()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return Response(content=data, media_type="audio/mpeg")
