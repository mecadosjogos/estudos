"""Cliente HTTP do serviço de TTS local (tts-service/, standalone) -- não
importa torch/coqui-tts aqui, só fala HTTP com um processo separado que já
está de pé na máquina. Espelha a forma de shared/transcriber.py (wrapper
fino sobre o motor de verdade), mas sobre HTTP em vez de biblioteca
importada direto: o modelo de TTS roda no processo do tts-service, reusável
por qualquer outra coisa na máquina, não só este worker.
"""

import time

import httpx

from . import config

_HEALTHZ_TIMEOUT_S = 5.0
# 120s se mostrou curto demais na prática: numa aula real, a seção mais
# longa do guia estourou esse teto com a narração já ~90% pronta (achado
# processando lesson 2/8 de produção) -- 600s dá folga generosa mesmo pra
# uma seção bem longa, sem custo nenhum quando a seção é curta (a chamada
# retorna assim que terminar, não espera o teto).
_SYNTHESIZE_TIMEOUT_S = 600.0


def healthz() -> bool:
    """True se o serviço de TTS estiver de pé e respondendo. Usado pelo
    dispatch de alvo no modo contínuo (worker/main.py) pra pular o alvo
    tts_guia sem travar o resto do loop quando o serviço não está rodando."""
    try:
        resp = httpx.get(f"{config.TTS_SERVICE_URL}/healthz", timeout=_HEALTHZ_TIMEOUT_S)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def synthesize(texto: str, speaker: str | None = None, *, attempts: int = 2) -> bytes:
    """Devolve os bytes do mp3 gerado. Tenta de novo uma vez (falha
    transiente de rede/timeout) antes de desistir -- quem chama
    (worker/main.py::process_tts_job) trata a falha final como falha só
    daquela seção, não do job inteiro (ver docstring de process_tts_job)."""
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.post(
                f"{config.TTS_SERVICE_URL}/synthesize",
                json={"texto": texto, "speaker": speaker},
                timeout=_SYNTHESIZE_TIMEOUT_S,
            )
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(2)
    raise last_exc
