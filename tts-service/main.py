"""Serviço de TTS local, standalone -- não conhece o Estudos.

Chatterbox Multilingual v3 (Resemble AI, MIT) -- diferente do F5-TTS
(abandonado nesta troca: produzia áudio embaralhado em PT-BR mesmo depois
de eliminar toda causa de configuração, com dois checkpoints comunitários
diferentes -- ver histórico do projeto), este modelo tem um parâmetro
explícito de idioma (`language_id="pt"`), não depende só do fine-tune/
referência pra "adivinhar" o idioma.

Usa a **voz embutida padrão** do próprio modelo (`conds.pt`, baixada junto
com os pesos) -- sem clonagem, por decisão explícita do usuário (nenhum
dado de voz pessoal envolvido). `POST /synthesize` aceita opcionalmente um
`speaker` apontando pra `vozes/<nome>/ref.wav` se algum dia fizer sentido
clonar de novo, mas isso é o caminho não-padrão, não o de hoje.
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


def _vozes_clonadas_disponiveis() -> list[str]:
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
    """Voz padrão embutida do modelo é sempre o default (não listada aqui
    por não precisar de arquivo nenhum) -- isto lista só vozes clonadas
    extras configuradas em vozes/, se alguma existir."""
    return {"speakers": _vozes_clonadas_disponiveis(), "padrao": "embutida (Chatterbox), sem clonagem"}


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

    # Sem `speaker`, usa a voz embutida padrão do modelo (audio_prompt_path
    # None -- Chatterbox já vem com um `conds.pt` pronto, não precisa de
    # referência nenhuma). Só clona se um `speaker` nomeado for pedido
    # explicitamente e tiver referência configurada em vozes/.
    ref_wav = None
    if body.speaker:
        candidate = VOZES_DIR / body.speaker / "ref.wav"
        if not candidate.exists():
            raise HTTPException(status_code=400, detail=f"voz desconhecida ou sem referência: {body.speaker}")
        ref_wav = candidate

    pieces = []
    for chunk in _split_into_chunks(texto):
        wav = model.generate(chunk, language_id=LANGUAGE_ID, audio_prompt_path=str(ref_wav) if ref_wav else None)
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
