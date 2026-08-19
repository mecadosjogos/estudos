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
    monkeypatch.setattr("sys.argv", ["main.py"])
    with (
        patch("worker.api_client.enqueue_pending_transcriptions", return_value=[]) as mock_enqueue,
        patch("worker.main.run") as mock_run,
    ):
        worker_main.main()

    mock_enqueue.assert_called_once()
    mock_run.assert_called_once_with(mode="drain", target="gpu_worker")


def test_main_does_not_enqueue_for_vps_cpu_target(monkeypatch):
    monkeypatch.setattr("sys.argv", ["main.py", "--target", "vps_cpu"])
    with (
        patch("worker.api_client.enqueue_pending_transcriptions") as mock_enqueue,
        patch("worker.main.run") as mock_run,
    ):
        worker_main.main()

    mock_enqueue.assert_not_called()
    mock_run.assert_called_once_with(mode="drain", target="vps_cpu")


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

    mock_run.assert_called_once_with(mode="drain", target="gpu_worker")
