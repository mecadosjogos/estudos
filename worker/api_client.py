"""Cliente HTTP do worker para a API de jobs do servidor. Autentica com o
mesmo token de acesso via `Authorization: Bearer` — o worker não tem
navegador para trocar o token por cookie (ver auth.require_session_or_token
no servidor)."""

from pathlib import Path

import httpx

from . import config


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.ACCESS_TOKEN}"}


def enqueue_pending_transcriptions() -> list[dict]:
    """Etapa 0 do RUNBOOK.md: pergunta pro servidor quais aulas têm áudio
    ainda sem transcrição (fora da matéria LIXO) e enfileira. Mecânico,
    sem IA -- roda sozinho antes do worker drenar a fila."""
    response = httpx.post(
        f"{config.SERVER_URL}/api/jobs/enqueue-pending-transcriptions",
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["enqueued"]


def get_next_job(worker_name: str, target: str = "gpu_worker") -> dict | None:
    response = httpx.get(
        f"{config.SERVER_URL}/api/jobs/next",
        params={"worker_name": worker_name, "target": target},
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["job"]


def download_segment(download_url: str, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream(
        "GET", f"{config.SERVER_URL}{download_url}", headers=_headers(), timeout=120
    ) as response:
        response.raise_for_status()
        with dest_path.open("wb") as f:
            for chunk in response.iter_bytes(1024 * 1024):
                f.write(chunk)


def send_heartbeat(job_id: int, claim_token: str) -> None:
    httpx.post(
        f"{config.SERVER_URL}/api/jobs/{job_id}/heartbeat",
        json={"claim_token": claim_token},
        headers=_headers(),
        timeout=30,
    ).raise_for_status()


def submit_result(
    job_id: int,
    *,
    claim_token: str,
    worker_name: str,
    engine: str,
    duration_s: float,
    payload: dict,
    mp3_path: Path,
) -> dict:
    import json

    # payload vai como arquivo, não como campo de formulário comum: uma aula
    # de verdade tem milhares de segmentos com timestamp por palavra, e o
    # Starlette limita campo de formulário a 1MB -- só arquivo escapa desse
    # teto (bug real: só apareceu com uma aula de ~2h, nunca nos testes com
    # aula de segundos).
    with mp3_path.open("rb") as f:
        response = httpx.post(
            f"{config.SERVER_URL}/api/jobs/{job_id}/result",
            headers=_headers(),
            data={
                "claim_token": claim_token,
                "worker_name": worker_name,
                "engine": engine,
                "duration_s": str(duration_s),
            },
            files={
                "audio": (mp3_path.name, f, "audio/mpeg"),
                "payload": ("payload.json", json.dumps(payload).encode("utf-8"), "application/json"),
            },
            timeout=600,
        )
    response.raise_for_status()
    return response.json()


def submit_rebuild_result(job_id: int, *, claim_token: str, mp3_path: Path) -> dict:
    with mp3_path.open("rb") as f:
        response = httpx.post(
            f"{config.SERVER_URL}/api/jobs/{job_id}/rebuild-result",
            headers=_headers(),
            data={"claim_token": claim_token},
            files={"audio": (mp3_path.name, f, "audio/mpeg")},
            timeout=600,
        )
    response.raise_for_status()
    return response.json()


def submit_tts_result(
    job_id: int, *, claim_token: str, audio_path: Path, timestamps: list[dict]
) -> dict:
    """`audio_path`: mp3 único da aula inteira (seções concatenadas).
    `timestamps`: lista de `{"ordem", "start_s", "end_s"}`, uma entrada por
    seção que narrou com sucesso -- seção que falhou simplesmente não
    entra na lista."""
    import json

    with audio_path.open("rb") as f:
        response = httpx.post(
            f"{config.SERVER_URL}/api/jobs/{job_id}/tts-result",
            headers=_headers(),
            data={"claim_token": claim_token, "timestamps": json.dumps(timestamps)},
            files={"audio": (audio_path.name, f, "audio/mpeg")},
            timeout=600,
        )
    response.raise_for_status()
    return response.json()


def report_failure(job_id: int, claim_token: str, error: str) -> None:
    httpx.post(
        f"{config.SERVER_URL}/api/jobs/{job_id}/fail",
        json={"claim_token": claim_token, "error": error},
        headers=_headers(),
        timeout=30,
    ).raise_for_status()
