"""Testa que uma transcrição já feita nunca é refeita numa nova tentativa.

Motivo de existir: um job real perdeu ~25 minutos de GPU porque a etapa de
envio falhou depois da transcrição, e o resultado só existia em memória —
nada tinha sido salvo em disco. worker/main.py agora grava o resultado do
Whisper assim que termina, antes de arriscar comprimir/enviar, e só apaga
o diretório de trabalho depois do envio confirmado.
"""

import json
from unittest.mock import patch

import worker.config as worker_config
import worker.main as worker_main


def _make_job(job_id=999):
    return {
        "id": job_id,
        "claim_token": "tok",
        "lesson_id": 1,
        "lesson_titulo": "Aula teste",
        "segments": [{"ordem": 1, "filename": "a.mp3", "download_url": "/x"}],
    }


def test_resume_skips_whisper_and_compress_when_already_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_config, "TMP_DIR", tmp_path)
    monkeypatch.setattr(worker_config, "ARCHIVE_DIR", tmp_path / "archive")

    job = _make_job()
    work_dir = tmp_path / f"job-{job['id']}"
    work_dir.mkdir(parents=True)
    (work_dir / "segment-001-a.mp3").write_bytes(b"fake-audio")
    (work_dir / "concatenated.wav").write_bytes(b"fake-wav")
    (work_dir / "audio.mp3").write_bytes(b"fake-mp3")
    (work_dir / "transcript.json").write_text(
        json.dumps(
            {
                "payload": {"full_text": "ola mundo", "segments": []},
                "duration_s": 5.0,
                "segment_filenames": ["segment-001-a.mp3"],
            }
        ),
        encoding="utf-8",
    )

    with (
        patch("worker.api_client.send_heartbeat"),
        patch(
            "worker.api_client.submit_result",
            return_value={"ok": True, "already_received": False},
        ) as mock_submit,
        patch("shared.transcriber.WhisperTranscriber") as mock_transcriber_cls,
        patch("shared.audio.concat_audio_files") as mock_concat,
        patch("shared.audio.compress_to_mp3") as mock_compress,
    ):
        worker_main.process_one_job(job)

    mock_transcriber_cls.assert_not_called()
    mock_concat.assert_not_called()
    mock_compress.assert_not_called()
    mock_submit.assert_called_once()
    assert mock_submit.call_args.kwargs["duration_s"] == 5.0

    # sucesso confirmado: o diretório de trabalho é limpo
    assert not work_dir.exists()


def test_transcript_is_cached_to_disk_before_risking_compress_or_send(tmp_path, monkeypatch):
    """Simula uma transcrição nova cujo envio falha — confirma que o
    Whisper não vai rodar de novo numa segunda chamada."""
    monkeypatch.setattr(worker_config, "TMP_DIR", tmp_path)
    monkeypatch.setattr(worker_config, "ARCHIVE_DIR", tmp_path / "archive")

    job = _make_job()
    work_dir = tmp_path / f"job-{job['id']}"

    fake_output = type(
        "FakeOutput",
        (),
        {
            "full_text": "ola mundo",
            "duration_s": 5.0,
            "segments": [],
        },
    )()

    def fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-audio")

    with (
        patch("worker.api_client.download_segment", side_effect=fake_download),
        patch("worker.api_client.send_heartbeat"),
        patch(
            "worker.api_client.submit_result", side_effect=RuntimeError("rede caiu")
        ) as mock_submit,
        patch("shared.audio.concat_audio_files") as mock_concat,
        patch("shared.audio.compress_to_mp3") as mock_compress,
        patch("shared.transcriber.WhisperTranscriber") as mock_transcriber_cls,
        patch("worker.main.time.sleep"),  # não espera de verdade entre retries
    ):
        mock_transcriber_cls.return_value.transcribe.return_value = fake_output

        worker_main.process_one_job(job)  # falha ao enviar, mas não propaga (é capturado)

        assert mock_transcriber_cls.call_count == 1
        assert (work_dir / "transcript.json").exists(), "transcrição precisa sobreviver à falha de envio"
        assert work_dir.exists(), "diretório não pode ser apagado quando o envio falhou"

        # segunda tentativa: acha o cache, não chama o Whisper de novo
        mock_submit.side_effect = None
        mock_submit.return_value = {"ok": True, "already_received": False}
        worker_main.process_one_job(job)

    assert mock_transcriber_cls.call_count == 1  # não subiu pra 2
    assert mock_concat.call_count == 1  # idem — só rodou na primeira tentativa
    assert not work_dir.exists()  # limpo depois do sucesso na segunda tentativa


def test_rebuild_job_uses_archive_and_never_calls_whisper(tmp_path, monkeypatch):
    """Job de reconstrução de mídia usa só o que já está arquivado localmente
    (PLANO.md, 'reconstruir mídia' depois de restaurar um backup) — não pode
    baixar nada do servidor nem rodar o Whisper de novo."""
    monkeypatch.setattr(worker_config, "TMP_DIR", tmp_path)
    monkeypatch.setattr(worker_config, "ARCHIVE_DIR", tmp_path / "archive")

    job = _make_job(job_id=42)
    lesson_dir = tmp_path / "archive" / f"lesson-{job['lesson_id']}"
    lesson_dir.mkdir(parents=True)
    (lesson_dir / "a.mp3").write_bytes(b"original arquivado")

    with (
        patch("worker.api_client.send_heartbeat"),
        patch("worker.api_client.download_segment") as mock_download,
        patch(
            "worker.api_client.submit_rebuild_result",
            return_value={"ok": True, "already_received": False},
        ) as mock_submit,
        patch("shared.transcriber.WhisperTranscriber") as mock_transcriber_cls,
        patch("shared.audio.concat_audio_files") as mock_concat,
        patch("shared.audio.compress_to_mp3") as mock_compress,
    ):
        worker_main.process_rebuild_job(job)

    mock_download.assert_not_called()
    mock_transcriber_cls.assert_not_called()
    mock_concat.assert_called_once()
    assert mock_concat.call_args.args[0] == [lesson_dir / "a.mp3"]
    mock_compress.assert_called_once()
    mock_submit.assert_called_once_with(42, claim_token="tok", mp3_path=tmp_path / "job-42" / "audio.mp3")


def test_rebuild_job_fails_clearly_when_archive_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_config, "TMP_DIR", tmp_path)
    monkeypatch.setattr(worker_config, "ARCHIVE_DIR", tmp_path / "archive")

    job = _make_job(job_id=43)

    with (
        patch("worker.api_client.send_heartbeat"),
        patch("worker.api_client.report_failure") as mock_fail,
        patch("shared.audio.concat_audio_files") as mock_concat,
    ):
        worker_main.process_rebuild_job(job)

    mock_concat.assert_not_called()
    mock_fail.assert_called_once()
    assert "archive local" in mock_fail.call_args.args[2]


def test_main_enqueues_pending_before_draining_gpu_queue(monkeypatch):
    """Modo contínuo padrão (sem --target): alterna gpu_worker/tts_guia
    sozinho -- ver worker/main.py::run, dispatch de dois alvos."""
    monkeypatch.setattr("sys.argv", ["main.py"])
    with (
        patch("worker.api_client.enqueue_pending_transcriptions", return_value=[]) as mock_enqueue,
        patch("worker.main.run") as mock_run,
    ):
        worker_main.main()

    mock_enqueue.assert_called_once()
    mock_run.assert_called_once_with(mode="drain", targets=["gpu_worker", "tts_guia"])


def test_main_does_not_enqueue_for_vps_cpu_target(monkeypatch):
    monkeypatch.setattr("sys.argv", ["main.py", "--target", "vps_cpu"])
    with (
        patch("worker.api_client.enqueue_pending_transcriptions") as mock_enqueue,
        patch("worker.main.run") as mock_run,
    ):
        worker_main.main()

    mock_enqueue.assert_not_called()
    mock_run.assert_called_once_with(mode="drain", targets=["vps_cpu"])


def test_main_keeps_draining_even_if_enqueue_check_fails(monkeypatch):
    """Etapa 0 é só uma conveniência -- se o servidor estiver fora do ar
    nesse instante, ainda vale drenar o que já está na fila."""
    monkeypatch.setattr("sys.argv", ["main.py"])
    with (
        patch(
            "worker.api_client.enqueue_pending_transcriptions",
            side_effect=RuntimeError("servidor fora do ar"),
        ),
        patch("worker.main.run") as mock_run,
    ):
        worker_main.main()

    mock_run.assert_called_once_with(mode="drain", targets=["gpu_worker", "tts_guia"])


def test_main_explicit_tts_guia_target_does_not_enqueue_transcriptions(monkeypatch):
    monkeypatch.setattr("sys.argv", ["main.py", "--target", "tts_guia"])
    with (
        patch("worker.api_client.enqueue_pending_transcriptions") as mock_enqueue,
        patch("worker.main.run") as mock_run,
    ):
        worker_main.main()

    mock_enqueue.assert_not_called()
    mock_run.assert_called_once_with(mode="drain", targets=["tts_guia"])


def test_run_skips_tts_guia_when_service_unhealthy_without_crashing(monkeypatch):
    """Achado real processando aulas de produção: se o tts-service não está
    de pé, o worker não pode travar nem derrubar o resto do loop -- só
    ignora esse alvo naquele ciclo."""
    with (
        patch("worker.tts.healthz", return_value=False) as mock_healthz,
        patch("worker.api_client.get_next_job", return_value=None) as mock_get_next_job,
    ):
        worker_main.run(mode="once", targets=["gpu_worker", "tts_guia"])

    mock_healthz.assert_called_once()
    # só tentou gpu_worker -- tts_guia foi pulado antes de perguntar ao servidor
    mock_get_next_job.assert_called_once()
    assert mock_get_next_job.call_args.args[1] == "gpu_worker"


def test_run_shuts_down_tts_service_when_draining_ends_with_tts_guia_as_target(monkeypatch):
    """Sem isso, o processo do tts-service (contexto CUDA incluso) fica
    ocupando VRAM à toa entre uma leva de aulas e a próxima -- worker
    encerra sozinho ao esvaziar a fila, sem precisar de comando manual."""
    with (
        patch("worker.tts.healthz", return_value=True),
        patch("worker.api_client.get_next_job", return_value=None),
        patch("worker.tts.shutdown") as mock_shutdown,
    ):
        worker_main.run(mode="drain", targets=["gpu_worker", "tts_guia"])

    mock_shutdown.assert_called_once()


def test_run_does_not_shutdown_tts_when_tts_guia_is_not_a_target(monkeypatch):
    with (
        patch("worker.api_client.get_next_job", return_value=None),
        patch("worker.tts.shutdown") as mock_shutdown,
    ):
        worker_main.run(mode="drain", targets=["gpu_worker"])

    mock_shutdown.assert_not_called()


def test_run_does_not_shutdown_tts_in_watch_mode(monkeypatch):
    """--watch fica de pé esperando o próximo job por natureza -- não faz
    sentido encerrar o serviço de narração só porque a fila esvaziou num
    instante."""
    calls = {"n": 0}

    def fake_get_next_job(worker_name, target):
        calls["n"] += 1
        if calls["n"] > 2:
            raise KeyboardInterrupt  # sai do loop infinito do modo watch
        return None

    with (
        patch("worker.tts.healthz", return_value=True),
        patch("worker.api_client.get_next_job", side_effect=fake_get_next_job),
        patch("worker.tts.shutdown") as mock_shutdown,
        patch("worker.main.time.sleep"),
    ):
        try:
            worker_main.run(mode="watch", targets=["gpu_worker", "tts_guia"])
        except KeyboardInterrupt:
            pass

    mock_shutdown.assert_not_called()


def test_process_tts_job_result_shuts_down_tts_in_once_mode(tmp_path, monkeypatch):
    """Modo --once também encerra o tts-service, não só o drenar padrão --
    é usado pra teste/depuração, mas não deveria deixar a GPU ocupada
    depois."""
    monkeypatch.setattr(worker_config, "TMP_DIR", tmp_path)
    job = {
        "id": 999,
        "claim_token": "tok",
        "lesson_id": 1,
        "lesson_titulo": "Aula teste",
        "guia_secoes": [{"ordem": 0, "titulo": "Intro", "corpo": "texto"}],
    }

    with (
        patch("worker.tts.healthz", return_value=True),
        patch("worker.api_client.get_next_job", return_value=job),
        patch("worker.tts.synthesize", return_value=b"audio"),
        patch("worker.api_client.send_heartbeat"),
        patch("worker.api_client.submit_tts_result", return_value={"ok": True, "already_received": False}),
        patch("shared.audio.probe_duration_s", return_value=1.0),
        patch("shared.audio.concat_audio_files"),
        patch("shared.audio.compress_to_mp3"),
        patch("worker.tts.shutdown") as mock_shutdown,
    ):
        worker_main.run(mode="once", targets=["tts_guia"])

    mock_shutdown.assert_called_once()


def _make_tts_job(job_id=500, secoes=None):
    return {
        "id": job_id,
        "claim_token": "tok",
        "lesson_id": 8,
        "lesson_titulo": "Aula 2",
        "guia_secoes": secoes
        if secoes is not None
        else [
            {"ordem": 0, "titulo": "Introdução", "corpo": "texto 1"},
            {"ordem": 1, "titulo": "Meio", "corpo": "texto 2"},
            {"ordem": 2, "titulo": "Fim", "corpo": "texto 3"},
        ],
    }


def test_tts_job_uploads_sections_that_succeeded_when_one_section_fails(tmp_path, monkeypatch):
    """Achado real processando aulas de produção (lesson 2/8 na VPS): um
    timeout numa seção jogava fora todo o resto já narrado. Agora só
    aquela seção fica sem áudio -- o job concatena as demais num mp3 só e
    é reportado como concluído, não como falha total."""
    monkeypatch.setattr(worker_config, "TMP_DIR", tmp_path)

    job = _make_tts_job()

    def fake_synthesize(texto, speaker=None):
        if "texto 2" in texto:
            raise RuntimeError("timeout")
        return b"audio-" + texto.encode()

    submitted = {}

    def fake_submit(job_id, *, claim_token, audio_path, timestamps):
        submitted["audio_path"] = audio_path
        submitted["timestamps"] = timestamps
        return {"ok": True, "already_received": False}

    with (
        patch("worker.tts.synthesize", side_effect=fake_synthesize),
        patch("worker.api_client.send_heartbeat"),
        patch("worker.api_client.submit_tts_result", side_effect=fake_submit) as mock_submit,
        patch("worker.api_client.report_failure") as mock_fail,
        patch("shared.audio.probe_duration_s", return_value=2.0),
        patch("shared.audio.make_silence") as mock_silence,
        patch("shared.audio.concat_audio_files") as mock_concat,
        patch("shared.audio.compress_to_mp3"),
    ):
        worker_main.process_tts_job(job)

    mock_fail.assert_not_called()
    mock_submit.assert_called_once()

    # seção 1 (ordem 1, "texto 2") falhou -- só 0 e 2 entram na linha do tempo
    timestamps = submitted["timestamps"]
    assert [t["ordem"] for t in timestamps] == [0, 2]
    assert timestamps[0] == {"ordem": 0, "start_s": 0.0, "end_s": 2.0}
    # seção seguinte começa depois da pausa entre seções, não colada
    assert timestamps[1]["start_s"] == 2.0 + worker_main.SILENCE_GAP_S

    mock_silence.assert_called_once()  # só 2 seções concatenadas -- precisa de 1 pausa
    concat_paths = mock_concat.call_args.args[0]
    assert len(concat_paths) == 3  # secao-0, silêncio, secao-2 -- a que falhou nunca entra

    # sucesso (mesmo que parcial): diretório de trabalho é limpo
    assert not (tmp_path / f"job-{job['id']}").exists()


def test_tts_job_reports_total_failure_only_when_every_section_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_config, "TMP_DIR", tmp_path)
    job = _make_tts_job()

    with (
        patch("worker.tts.synthesize", side_effect=RuntimeError("serviço fora do ar")),
        patch("worker.api_client.send_heartbeat"),
        patch("worker.api_client.submit_tts_result") as mock_submit,
        patch("worker.api_client.report_failure") as mock_fail,
    ):
        worker_main.process_tts_job(job)

    mock_submit.assert_not_called()
    mock_fail.assert_called_once()
    assert "nenhuma seção" in mock_fail.call_args.args[2]


def test_tts_job_resumes_without_resynthesizing_sections_already_on_disk(tmp_path, monkeypatch):
    """Job retomado (reivindicação obsoleta liberada de novo,
    `_reclaim_stale`) não refaz seções cujo mp3 já está em work_dir."""
    monkeypatch.setattr(worker_config, "TMP_DIR", tmp_path)
    job = _make_tts_job()

    work_dir = tmp_path / f"job-{job['id']}"
    work_dir.mkdir(parents=True)
    (work_dir / "secao-0.mp3").write_bytes(b"ja-narrada-antes")

    submitted = {}

    def fake_submit(job_id, *, claim_token, audio_path, timestamps):
        submitted["timestamps"] = timestamps
        return {"ok": True, "already_received": False}

    with (
        patch("worker.tts.synthesize", return_value=b"audio-novo") as mock_synth,
        patch("worker.api_client.send_heartbeat"),
        patch("worker.api_client.submit_tts_result", side_effect=fake_submit),
        patch("shared.audio.probe_duration_s", return_value=1.5),
        patch("shared.audio.make_silence"),
        patch("shared.audio.concat_audio_files") as mock_concat,
        patch("shared.audio.compress_to_mp3"),
    ):
        worker_main.process_tts_job(job)

    # só narrou as duas que faltavam -- a seção 0 não foi regenerada
    assert mock_synth.call_count == 2
    # mas as 3 (a retomada + as 2 novas) entram na linha do tempo/concatenação
    assert [t["ordem"] for t in submitted["timestamps"]] == [0, 1, 2]
    concat_paths = mock_concat.call_args.args[0]
    assert concat_paths[0] == work_dir / "secao-0.mp3"
