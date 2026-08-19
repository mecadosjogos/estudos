import json
from datetime import date

from starlette.testclient import TestClient


def _authed_client():
    from app.main import app

    client = TestClient(app)
    client.get("/?k=test-token")
    return client


def _make_lesson_with_segments(session, segments):
    """segments: lista de (texto, lista_de_probabilidades)."""
    from sqlalchemy import select

    from app.models import AudioSegment, Lesson, Subject, Transcript, TranscriptSegment

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
    lesson = Lesson(subject_id=subject_id, titulo="Aula", data=date(2026, 3, 12))
    session.add(lesson)
    session.flush()

    session.add(AudioSegment(
        lesson_id=lesson.id, ordem=1, original_filename="a.m4a",
        storage_path="/tmp/x", size_bytes=10, status="complete",
    ))

    transcript = Transcript(
        lesson_id=lesson.id, engine="e", worker_name="w",
        full_text=" ".join(t for t, _ in segments), duration_s=float(len(segments) * 10),
    )
    session.add(transcript)
    session.flush()

    for i, (text, probs) in enumerate(segments):
        words = [{"text": w, "start_s": 0.0, "end_s": 1.0, "probability": p} for w, p in zip(text.split(), probs)]
        session.add(TranscriptSegment(
            transcript_id=transcript.id, idx=i, start_s=float(i * 10), end_s=float(i * 10 + 8),
            text=text, words_json=json.dumps(words),
        ))
    session.commit()
    return lesson.id, transcript.id


def test_confidence_helpers_flag_low_probability_segments(app_env):
    from app.db import holder
    from app.models import TranscriptSegment
    from app.transcript_confidence import is_low_confidence_segment, segment_confidence

    with holder.SessionLocal() as session:
        lesson_id, _ = _make_lesson_with_segments(session, [
            ("trecho confiavel", [0.95, 0.9]),
            ("trecho duvidoso", [0.2, 0.1]),
        ])
        segs = session.query(TranscriptSegment).order_by(TranscriptSegment.idx).all()

        assert segment_confidence(segs[0]) > 0.9
        assert not is_low_confidence_segment(segs[0])

        assert segment_confidence(segs[1]) < 0.5
        assert is_low_confidence_segment(segs[1])


def test_confidence_helpers_segment_without_words_is_not_flagged(app_env):
    from app.models import TranscriptSegment
    from app.transcript_confidence import is_low_confidence_segment, segment_confidence

    segment = TranscriptSegment(transcript_id=1, idx=0, start_s=0.0, end_s=1.0, text="x", words_json="[]")
    assert segment_confidence(segment) is None
    assert not is_low_confidence_segment(segment)


def _seg(idx, start_s, text, probability=0.95):
    from app.models import TranscriptSegment

    words = [{"text": w, "start_s": start_s, "end_s": start_s + 0.5, "probability": probability} for w in text.split()]
    return TranscriptSegment(
        transcript_id=1, idx=idx, start_s=start_s, end_s=start_s + 1.0, text=text, words_json=json.dumps(words)
    )


def test_has_recent_repeat_flags_identical_text_within_window():
    from app.transcript_confidence import has_recent_repeat

    segments = [
        _seg(0, 0.0, "desta feita."),
        _seg(1, 5.0, "algo diferente"),
        _seg(2, 10.0, "desta feita."),
    ]
    assert has_recent_repeat(segments, 0)
    assert has_recent_repeat(segments, 2)
    assert not has_recent_repeat(segments, 1)


def test_has_recent_repeat_ignores_matches_outside_window():
    from app.transcript_confidence import has_recent_repeat

    segments = [
        _seg(0, 0.0, "desta feita."),
        _seg(1, 100.0, "desta feita."),
    ]
    assert not has_recent_repeat(segments, 0, window_s=30.0)
    assert not has_recent_repeat(segments, 1, window_s=30.0)


def test_has_recent_repeat_is_case_and_whitespace_insensitive():
    from app.transcript_confidence import has_recent_repeat

    segments = [_seg(0, 0.0, "Desta Feita."), _seg(1, 2.0, "  desta feita.  ")]
    assert has_recent_repeat(segments, 0)


def test_is_suspicious_segment_catches_high_confidence_repeat_loop():
    """O caso real que motivou isso: seis trechos com a mesma palavra,
    cada um com probabilidade individual razoável (o modelo "confiante"
    reforçando o próprio erro) -- só a probabilidade não pega, a
    repetição pega."""
    from app.transcript_confidence import is_low_confidence_segment, is_suspicious_segment

    segments = [_seg(i, i * 0.5, "será", probability=0.8) for i in range(6)]
    assert not is_low_confidence_segment(segments[0])  # confiança "alta" isolada
    assert is_suspicious_segment(segments, 0)  # mas a repetição denuncia


def test_is_suspicious_segment_leaves_normal_text_alone():
    from app.transcript_confidence import is_suspicious_segment

    segments = [
        _seg(0, 0.0, "primeira frase real", probability=0.95),
        _seg(1, 5.0, "segunda frase diferente", probability=0.95),
    ]
    assert not is_suspicious_segment(segments, 0)
    assert not is_suspicious_segment(segments, 1)


def test_transcript_page_marks_low_confidence_segments(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id, _ = _make_lesson_with_segments(session, [
            ("trecho confiavel", [0.95, 0.9]),
            ("trecho duvidoso", [0.2, 0.1]),
        ])

    response = client.get(f"/lessons/{lesson_id}/transcricao")
    assert response.status_code == 200
    assert "segment-low-confidence" in response.text
    assert "baixa confiança" in response.text
    assert response.text.count('class="segment-edit-btn') == 2  # editável, ainda não aprovada


def test_edit_segment_updates_text_and_recomposes_full_text(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Lesson, TranscriptSegment

    with holder.SessionLocal() as session:
        lesson_id, transcript_id = _make_lesson_with_segments(session, [
            ("trecho errado", [0.9, 0.9]),
            ("segundo trecho", [0.9, 0.9]),
        ])
        segment_id = session.scalar(
            select(TranscriptSegment.id).where(
                TranscriptSegment.transcript_id == transcript_id, TranscriptSegment.idx == 0
            )
        )

    response = client.post(
        f"/lessons/{lesson_id}/transcricao/segments/{segment_id}", data={"texto": "trecho corrigido"}
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "text": "trecho corrigido"}

    with holder.SessionLocal() as session:
        segment = session.get(TranscriptSegment, segment_id)
        assert segment.text == "trecho corrigido"
        assert segment.editado_em is not None

        lesson = session.get(Lesson, lesson_id)
        assert lesson.transcript.full_text == "trecho corrigido segundo trecho"


def test_edit_segment_rejects_empty_text(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import TranscriptSegment

    with holder.SessionLocal() as session:
        lesson_id, transcript_id = _make_lesson_with_segments(session, [("trecho", [0.9])])
        segment_id = session.scalar(
            select(TranscriptSegment.id).where(TranscriptSegment.transcript_id == transcript_id)
        )

    response = client.post(f"/lessons/{lesson_id}/transcricao/segments/{segment_id}", data={"texto": "   "})
    assert response.status_code == 400


def test_approve_then_reopen_transcript(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import Transcript

    with holder.SessionLocal() as session:
        lesson_id, _ = _make_lesson_with_segments(session, [("trecho", [0.9])])

    approve = client.post(f"/lessons/{lesson_id}/transcricao/aprovar", follow_redirects=True)
    assert approve.status_code == 200
    assert "revisado" in approve.text
    assert "Reabrir revisão" in approve.text

    with holder.SessionLocal() as session:
        transcript = session.scalar(select(Transcript).where(Transcript.lesson_id == lesson_id))
        assert transcript.aprovado_em is not None

    reopen = client.post(f"/lessons/{lesson_id}/transcricao/reabrir", follow_redirects=True)
    assert reopen.status_code == 200
    assert "Aprovar transcrição" in reopen.text

    with holder.SessionLocal() as session:
        transcript = session.scalar(select(Transcript).where(Transcript.lesson_id == lesson_id))
        assert transcript.aprovado_em is None


def test_edit_segment_blocked_after_approval(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import TranscriptSegment

    with holder.SessionLocal() as session:
        lesson_id, transcript_id = _make_lesson_with_segments(session, [("trecho", [0.9])])
        segment_id = session.scalar(
            select(TranscriptSegment.id).where(TranscriptSegment.transcript_id == transcript_id)
        )

    client.post(f"/lessons/{lesson_id}/transcricao/aprovar")

    response = client.post(
        f"/lessons/{lesson_id}/transcricao/segments/{segment_id}", data={"texto": "tentando editar"}
    )
    assert response.status_code == 409

    with holder.SessionLocal() as session:
        segment = session.get(TranscriptSegment, segment_id)
        assert segment.text == "trecho"


def test_retranscribe_blocked_after_approval_gpu_and_vps(app_env):
    client = _authed_client()
    from app.db import holder

    with holder.SessionLocal() as session:
        lesson_id, _ = _make_lesson_with_segments(session, [("trecho", [0.9])])

    client.post(f"/lessons/{lesson_id}/transcricao/aprovar")

    gpu = client.post(f"/lessons/{lesson_id}/iniciar-transcricao")
    assert gpu.status_code == 409

    vps = client.post(f"/lessons/{lesson_id}/transcrever-na-vps")
    assert vps.status_code == 409


def test_retranscribe_allowed_after_reopen(app_env):
    client = _authed_client()
    from sqlalchemy import select

    from app.db import holder
    from app.models import TranscriptionJob

    with holder.SessionLocal() as session:
        lesson_id, _ = _make_lesson_with_segments(session, [("trecho", [0.9])])

    client.post(f"/lessons/{lesson_id}/transcricao/aprovar")
    client.post(f"/lessons/{lesson_id}/transcricao/reabrir")

    response = client.post(f"/lessons/{lesson_id}/iniciar-transcricao", follow_redirects=True)
    assert response.status_code == 200

    with holder.SessionLocal() as session:
        jobs = session.scalars(
            select(TranscriptionJob).where(TranscriptionJob.lesson_id == lesson_id)
        ).all()
        assert len(jobs) == 1
