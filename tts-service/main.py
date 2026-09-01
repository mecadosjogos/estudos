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
    """`ok` reflete se o modelo está carregado na VRAM agora -- fica
    `false` depois de um `/unload` até a próxima síntese recarregar
    sozinha. O serviço em si (o processo) continua de pé de qualquer
    jeito, só o modelo é que entra/sai da GPU."""
    return {"ok": _model is not None, "model": "ChatterboxMultilingualTTS"}


@app.post("/unload")
def unload():
    """Libera o modelo da VRAM -- chamado pelo worker quando termina de
    drenar a fila de narração (modo contínuo padrão, sem --watch), pra não
    deixar a GPU ocupada à toa entre uma leva e a próxima. Próxima
    chamada a /synthesize recarrega sozinha (paga o custo de novo, mas só
    quando realmente for usar)."""
    global _model
    was_loaded = _model is not None
    if was_loaded:
        _model = None
        import gc

        import torch

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    return {"ok": True, "liberado": was_loaded}


@app.post("/shutdown")
def shutdown():
    """Encerra o processo inteiro -- diferente de `/unload`, que só larga o
    modelo e mantém o processo (e o contexto CUDA) vivo pra recarregar
    rápido depois. O contexto CUDA (kernels do cuDNN/cuBLAS, cache do
    alocador do PyTorch) só é liberado quando o processo termina de
    verdade -- `del`/`empty_cache()` não alcança isso, então mesmo depois
    de um `/unload` sobra ~1-1.5GB preso na GPU enquanto o processo segue
    de pé (achado real, GPU RTX 4070). Pedido explícito do usuário: já que
    o worker (`worker/main.py::_shutdown_tts_if_relevant`) chama isto como
    último passo antes de ficar ocioso, vale devolver a GPU por completo
    em vez de só descarregar o modelo -- o preço é que a próxima narração
    precisa de `tts-service\\iniciar.ps1` rodando de novo (o processo não
    fica mais de pé esperando)."""
    import os
    import threading
    import time

    def _exit():
        time.sleep(0.3)  # dá tempo da resposta HTTP sair antes do processo morrer
        os._exit(0)

    threading.Thread(target=_exit, daemon=True).start()
    return {"ok": True}


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
