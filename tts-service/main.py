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

# Trecho curto e conferência de duração: o Chatterbox em PT às vezes termina
# o texto e segue "falando" -- sílabas sem sentido, que soam como símbolo
# sendo lido -- até o teto de 40 s. Medido (texto real do guia, 3 rodadas
# por variante): trechos de ~270 caracteres saíram com esse balbucio em 7 de
# 9 rodadas, frases soltas em 4 de 15. Áudio limpo sai a 15-22 caracteres
# por segundo; com balbucio, a 11 ou menos. Como o modelo nunca termina
# antes do fim do texto (ele suprime o fim até lá), áudio longo demais pro
# tamanho do texto é sempre sobra -- e gerar de novo resolve.
MAX_CHUNK_CHARS = 150
MIN_CHARS_POR_SEGUNDO = 13
FOLGA_S = 0.8
MAX_TENTATIVAS = 4

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
    # Ponto e vírgula também fecha trecho: no guia ele separa orações
    # inteiras, e uma frase com dois ";" passa fácil dos 150 caracteres.
    sentences = [s for s in re.split(r"(?<=[.!?;])\s+", texto.strip()) if s]
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


def _duracao_maxima_s(chunk: str) -> float:
    # Piso de 2 s: num título curto ("Fontes."), o silêncio de ponta pesa
    # mais que a fala e a conta por caractere acusaria sobra que não há.
    return max(2.0, len(chunk) / MIN_CHARS_POR_SEGUNDO + FOLGA_S)


def _soltar_hooks_de_atencao(model) -> None:
    """Cada `generate` do Chatterbox pendura 3 hooks novos nas camadas de
    atenção (o analisador de alinhamento) e nunca os tira: num serviço que
    narra centenas de trechos, eles se acumulam e cada passo de geração fica
    mais lento. O analisador da geração seguinte registra os dele de novo."""
    for layer in model.t3.tfmr.layers:
        layer.self_attn._forward_hooks.clear()


def _gerar_trecho(model, chunk: str, audio_prompt_path: str | None) -> np.ndarray:
    """Gera o trecho e, se sobrou fala depois do texto (duração acima do
    que o texto justifica), gera de novo. Esgotadas as tentativas, fica o
    mais curto -- o que menos balbucia."""
    limite = _duracao_maxima_s(chunk)
    melhor = None
    for _ in range(MAX_TENTATIVAS):
        _soltar_hooks_de_atencao(model)
        wav = model.generate(chunk, language_id=LANGUAGE_ID, audio_prompt_path=audio_prompt_path)
        wav = wav.squeeze(0).cpu().numpy()
        if melhor is None or len(wav) < len(melhor):
            melhor = wav
        if len(wav) / model.sr <= limite:
            break
    return melhor


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

    pieces = [
        _gerar_trecho(model, chunk, str(ref_wav) if ref_wav else None) for chunk in _split_into_chunks(texto)
    ]

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
