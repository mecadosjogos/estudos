"""Cliente HTTP do serviço de TTS local (tts-service/, standalone) -- não
importa torch/coqui-tts aqui, só fala HTTP com um processo separado que já
está de pé na máquina. Espelha a forma de shared/transcriber.py (wrapper
fino sobre o motor de verdade), mas sobre HTTP em vez de biblioteca
importada direto: o modelo de TTS roda no processo do tts-service, reusável
por qualquer outra coisa na máquina, não só este worker.
"""

import httpx

from . import config

_HEALTHZ_TIMEOUT_S = 5.0
_SYNTHESIZE_TIMEOUT_S = 120.0


def healthz() -> bool:
    """True se o serviço de TTS estiver de pé e respondendo. Usado pelo
    dispatch de alvo no modo contínuo (worker/main.py) pra pular o alvo
    tts_guia sem travar o resto do loop quando o serviço não está rodando."""
    try:
        resp = httpx.get(f"{config.TTS_SERVICE_URL}/healthz", timeout=_HEALTHZ_TIMEOUT_S)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def synthesize(texto: str, speaker: str | None = None) -> bytes:
    """Devolve os bytes do mp3 gerado. Levanta em caso de erro -- quem chama
    (worker/main.py::process_tts_job) trata qualquer falha aqui como falha
    do job inteiro (tudo-ou-nada, ver PLANO.md/plano desta feature), sem
    tratamento especial neste cliente."""
    resp = httpx.post(
        f"{config.TTS_SERVICE_URL}/synthesize",
        json={"texto": texto, "speaker": speaker},
        timeout=_SYNTHESIZE_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.content
