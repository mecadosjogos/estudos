"""Worker de transcrição (PLANO.md, fase 4).

Roda na máquina com GPU: pega um job da fila, baixa os segmentos de áudio,
concatena na ordem certa, transcreve com faster-whisper, comprime pra mp3,
envia o resultado e arquiva o original localmente.

Três modos: o padrão **drena a fila inteira** (processa tudo que estiver
pendente, um job por vez, e sai quando não sobrar nada) — pensado pra rodar
por um atalho de duplo clique: liga, trabalha até não ter mais nada, desliga
sozinho. `--once` processa só um job e sai (útil pra testar). `--watch` fica
rodando pra sempre, pegando job assim que aparecer.

A transcrição (a etapa cara, minutos de GPU) é salva em disco assim que
termina — antes de arriscar comprimir e enviar. Se uma dessas duas etapas
falhar depois, a próxima tentativa retoma dali sem rodar o Whisper de novo.
O diretório de trabalho só é apagado depois do envio confirmado.
"""

import argparse
import json
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from worker import api_client, config  # noqa: E402


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _format_eta(elapsed_s: float, done_s: float, total_s: float) -> str:
    if done_s <= 0:
        return "calculando..."
    rate = elapsed_s / done_s
    remaining = max(0.0, (total_s - done_s) * rate)
    return f"{int(remaining // 60)}min{int(remaining % 60):02d}s restantes"


class HeartbeatThread(threading.Thread):
    def __init__(self, job_id: int, claim_token: str):
        super().__init__(daemon=True)
        self.job_id = job_id
        self.claim_token = claim_token
        self._stop = threading.Event()

    def run(self):
        while not self._stop.wait(config.HEARTBEAT_INTERVAL_S):
            try:
                api_client.send_heartbeat(self.job_id, self.claim_token)
            except Exception as exc:  # noqa: BLE001 — heartbeat que falha não deve matar o worker
                _log(f"heartbeat falhou (seguindo mesmo assim): {exc}")

    def stop(self):
        self._stop.set()


def process_one_job(job: dict) -> None:
    from shared.audio import compress_to_mp3, concat_audio_files
    from shared.transcriber import WhisperTranscriber

    job_id = job["id"]
    claim_token = job["claim_token"]

    # Diretório fixo por job (não randômico): uma segunda tentativa do mesmo
    # job cai no mesmo lugar e encontra o que a tentativa anterior já tinha
    # calculado, em vez de começar do zero.
    work_dir = config.TMP_DIR / f"job-{job_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    transcript_cache_path = work_dir / "transcript.json"
    concatenated = work_dir / "concatenated.wav"
    mp3_path = work_dir / "audio.mp3"

    heartbeat = HeartbeatThread(job_id, claim_token)
    heartbeat.start()

    try:
        _log(f"job {job_id} — aula \"{job['lesson_titulo']}\" — {len(job['segments'])} segmento(s)")

        if transcript_cache_path.exists():
            _log("achei transcrição de uma tentativa anterior em disco — pulando download e Whisper, retomando do envio")
            cached = json.loads(transcript_cache_path.read_text(encoding="utf-8"))
            payload = cached["payload"]
            duration_s = cached["duration_s"]
            segment_paths = [work_dir / name for name in cached["segment_filenames"]]
        else:
            segment_paths = []
            for seg in job["segments"]:
                dest = work_dir / f"segment-{seg['ordem']:03d}-{seg['filename']}"
                _log(f"baixando segmento {seg['ordem']}: {seg['filename']}")
                api_client.download_segment(seg["download_url"], dest)
                segment_paths.append(dest)

            _log("concatenando segmentos...")
            concat_audio_files(segment_paths, concatenated)

            _log(f"transcrevendo com {config.WHISPER_MODEL} ({config.WHISPER_DEVICE})...")
            transcriber = WhisperTranscriber(
                model_size=config.WHISPER_MODEL,
                device=config.WHISPER_DEVICE,
                compute_type=config.WHISPER_COMPUTE_TYPE,
            )

            start_time = time.monotonic()

            def on_segment(segment_result, total_duration_s):
                elapsed = time.monotonic() - start_time
                eta = _format_eta(elapsed, segment_result.end_s, total_duration_s)
                pct = min(100, round(100 * segment_result.end_s / total_duration_s)) if total_duration_s else 0
                _log(f"  {pct}% — {eta}")

            output = transcriber.transcribe(str(concatenated), on_segment=on_segment)
            _log(f"transcrição pronta: {len(output.segments)} segmentos, {output.duration_s:.0f}s de áudio")

            duration_s = output.duration_s
            payload = {
                "full_text": output.full_text,
                "segments": [
                    {
                        "idx": s.idx,
                        "start_s": s.start_s,
                        "end_s": s.end_s,
                        "text": s.text,
                        "words": [
                            {"text": w.text, "start_s": w.start_s, "end_s": w.end_s, "probability": w.probability}
                            for w in s.words
                        ],
                    }
                    for s in output.segments
                ],
            }

            transcript_cache_path.write_text(
                json.dumps(
                    {
                        "payload": payload,
                        "duration_s": duration_s,
                        "segment_filenames": [p.name for p in segment_paths],
                    }
                ),
                encoding="utf-8",
            )
            _log("transcrição salva em disco — a partir daqui, uma nova tentativa não repete o Whisper")

        if not mp3_path.exists():
            _log("comprimindo mp3 32kbps...")
            compress_to_mp3(concatenated, mp3_path)

        _log("enviando resultado...")
        result = _send_result_with_retry(job_id, claim_token, duration_s, mp3_path, payload)
        if result.get("already_received"):
            _log("servidor já tinha esse resultado (reenvio idempotente) — ok")
        else:
            _log("resultado gravado no servidor")

        _archive_originals(job, segment_paths)
        shutil.rmtree(work_dir, ignore_errors=True)

    except Exception as exc:  # noqa: BLE001 — falha vira status "failed" no servidor, nunca some silenciosa
        _log(f"FALHOU: {exc}")
        traceback.print_exc()
        _log(f"nada em {work_dir} foi apagado — uma nova tentativa retoma daqui em vez de repetir o Whisper")
        try:
            api_client.report_failure(job_id, claim_token, str(exc))
        except Exception as report_exc:  # noqa: BLE001
            _log(f"não consegui nem reportar a falha pro servidor: {report_exc}")
    finally:
        heartbeat.stop()


def _send_result_with_retry(job_id, claim_token, duration_s, mp3_path, payload, max_attempts=5) -> dict:
    for attempt in range(1, max_attempts + 1):
        try:
            return api_client.submit_result(
                job_id,
                claim_token=claim_token,
                worker_name=config.WORKER_NAME,
                engine=f"faster-whisper-{config.WHISPER_MODEL}",
                duration_s=duration_s,
                payload=payload,
                mp3_path=mp3_path,
            )
        except Exception as exc:  # noqa: BLE001
            if attempt == max_attempts:
                raise
            wait = min(30, 2**attempt)
            _log(f"envio falhou ({exc}), tentando de novo em {wait}s (tentativa {attempt}/{max_attempts})")
            time.sleep(wait)


def _archive_originals(job: dict, segment_paths: list[Path]) -> None:
    """Move os originais baixados para archive/ local — a cópia definitiva
    depois que a VPS apaga o dela (ver ingest_result no servidor)."""
    config.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    lesson_dir = config.ARCHIVE_DIR / f"lesson-{job['lesson_id']}"
    lesson_dir.mkdir(parents=True, exist_ok=True)
    for path in segment_paths:
        dest = lesson_dir / path.name.split("-", 2)[-1]
        if path.exists():
            shutil.move(str(path), str(dest))
    _log(f"originais arquivados em {lesson_dir}")


def run(mode: str, target: str) -> None:
    if not config.ACCESS_TOKEN:
        _log("ACCESS_TOKEN não configurado no .env — o servidor vai recusar tudo")

    _log(f"worker \"{config.WORKER_NAME}\" — servidor {config.SERVER_URL} — alvo {target} — modo {mode}")

    jobs_done = 0
    while True:
        job = api_client.get_next_job(config.WORKER_NAME, target)
        if job is None:
            if mode == "watch":
                time.sleep(config.POLL_INTERVAL_S)
                continue
            _log(f"fila vazia — {jobs_done} job(s) processado(s) nesta execução, encerrando")
            return

        process_one_job(job)
        jobs_done += 1

        if mode == "once":
            return
        # "drain" e "watch" voltam pro topo do loop e pegam o próximo


def main():
    parser = argparse.ArgumentParser(description="Worker de transcrição")
    parser.add_argument(
        "--once", action="store_true", help="processa só um job e sai (útil pra testar)"
    )
    parser.add_argument(
        "--watch", action="store_true", help="roda contínuo, pegando job assim que aparecer"
    )
    parser.add_argument("--target", default="gpu_worker", choices=["gpu_worker", "vps_cpu"])
    args = parser.parse_args()

    if args.once and args.watch:
        raise SystemExit("--once e --watch são incompatíveis")

    mode = "once" if args.once else "watch" if args.watch else "drain"
    run(mode=mode, target=args.target)


if __name__ == "__main__":
    main()
