from datetime import date, timedelta

from app.study.scheduler import apply_sm2


def test_sm2_first_correct_review_schedules_for_tomorrow():
    result = apply_sm2(ease_factor=2.5, interval_days=0, repetitions=0, quality=4, today=date(2026, 3, 1))
    assert result.interval_days == 1
    assert result.repetitions == 1
    assert result.due_date == date(2026, 3, 2)


def test_sm2_second_correct_review_jumps_to_six_days():
    result = apply_sm2(ease_factor=2.5, interval_days=1, repetitions=1, quality=4, today=date(2026, 3, 1))
    assert result.interval_days == 6
    assert result.repetitions == 2


def test_sm2_third_correct_review_multiplies_by_ease_factor():
    result = apply_sm2(ease_factor=2.5, interval_days=6, repetitions=2, quality=4, today=date(2026, 3, 1))
    assert result.interval_days == 15  # round(6 * 2.5)
    assert result.repetitions == 3


def test_sm2_failed_review_resets_repetitions_and_goes_to_tomorrow():
    result = apply_sm2(ease_factor=2.3, interval_days=15, repetitions=3, quality=1, today=date(2026, 3, 1))
    assert result.repetitions == 0
    assert result.interval_days == 1
    assert result.due_date == date(2026, 3, 2)


def test_sm2_ease_factor_never_drops_below_1_3():
    ease = 1.3
    for _ in range(10):
        result = apply_sm2(ease_factor=ease, interval_days=1, repetitions=0, quality=0, today=date(2026, 3, 1))
        ease = result.ease_factor
    assert ease >= 1.3


def test_sm2_easy_quality_grows_ease_factor():
    result = apply_sm2(ease_factor=2.5, interval_days=6, repetitions=2, quality=5, today=date(2026, 3, 1))
    assert result.ease_factor > 2.5


def _make_card(session, subject_sigla, titulo, frente="F", verso="V", status="aceito", due_date=None):
    from sqlalchemy import select

    from app.models import CardProposal, Lesson, Subject

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == subject_sigla))
    lesson = Lesson(subject_id=subject_id, titulo=titulo, data=date(2026, 3, 1))
    session.add(lesson)
    session.flush()

    card = CardProposal(
        lesson_id=lesson.id, deriv_key=f"card:{titulo}:{frente}", frente=frente, verso=verso,
        start_s=0.0, end_s=5.0, status=status, due_date=due_date or date(2026, 3, 1),
    )
    session.add(card)
    session.commit()
    return card.id


def test_submit_review_updates_card_and_logs(app_env):
    from app.db import holder
    from app.models import CardProposal, ReviewLog
    from app.study.scheduler import submit_review

    with holder.SessionLocal() as session:
        card_id = _make_card(session, "TGDC", "Aula 1")
        card = session.get(CardProposal, card_id)

        log = submit_review(session, card, confianca="tenho_certeza", shortcut=3, today=date(2026, 3, 1))

        assert log.qualidade == 4
        assert log.acertou is True
        assert card.repetitions == 1
        assert card.due_date == date(2026, 3, 2)

    with holder.SessionLocal() as session:
        logs = session.query(ReviewLog).filter_by(card_id=card_id).all()
        assert len(logs) == 1
        assert logs[0].confianca == "tenho_certeza"


def test_build_daily_queue_interleaves_subjects(app_env):
    from app.db import holder
    from app.study.scheduler import build_daily_queue

    with holder.SessionLocal() as session:
        for i in range(3):
            _make_card(session, "TGDC", f"Civil {i}", frente=f"civil-{i}")
        for i in range(3):
            _make_card(session, "TGC", f"Penal {i}", frente=f"penal-{i}")

        queue, in_recovery = build_daily_queue(session, daily_cap=40, today=date(2026, 3, 1))

        assert len(queue) == 6
        assert in_recovery is False
        subjects_sequence = [c.lesson.subject.sigla for c in queue]
        # não pode vir todo TGDC primeiro e todo TGC depois
        assert subjects_sequence != ["TGDC"] * 3 + ["TGC"] * 3


def test_build_daily_queue_respects_daily_cap_and_triggers_recovery(app_env):
    from app.db import holder
    from app.models import CardProposal
    from app.study.scheduler import build_daily_queue

    with holder.SessionLocal() as session:
        for i in range(10):
            _make_card(session, "TGDC", f"Aula {i}", frente=f"f{i}")

        queue, in_recovery = build_daily_queue(session, daily_cap=4, today=date(2026, 3, 1))

        assert len(queue) == 4
        assert in_recovery is True

    with holder.SessionLocal() as session:
        # o resto não pode continuar todo vencendo hoje — foi redistribuído
        overdue_today = session.query(CardProposal).filter(
            CardProposal.status == "aceito", CardProposal.due_date <= date(2026, 3, 1)
        ).count()
        assert overdue_today == 4


def test_build_daily_queue_prioritizes_oldest_due_date_first(app_env):
    from app.db import holder
    from app.study.scheduler import build_daily_queue

    with holder.SessionLocal() as session:
        old_id = _make_card(session, "TGDC", "Antiga", frente="antiga", due_date=date(2026, 2, 1))
        _make_card(session, "TGDC", "Recente", frente="recente", due_date=date(2026, 3, 1))

        queue, _ = build_daily_queue(session, daily_cap=1, today=date(2026, 3, 1))

        assert len(queue) == 1
        assert queue[0].id == old_id


def test_pending_cards_are_never_included_in_the_queue(app_env):
    from app.db import holder
    from app.study.scheduler import build_daily_queue

    with holder.SessionLocal() as session:
        _make_card(session, "TGDC", "Pendente", frente="p", status="pendente")

        queue, _ = build_daily_queue(session, daily_cap=40, today=date(2026, 3, 1))

        assert queue == []


def test_calibration_report_reflects_real_accuracy_per_confidence_level(app_env):
    from app.db import holder
    from app.models import CardProposal
    from app.study.scheduler import calibration_report, submit_review

    with holder.SessionLocal() as session:
        card_id = _make_card(session, "TGDC", "Aula calibração")
        card = session.get(CardProposal, card_id)

        # "tenho certeza" errando 1 de 2 — má calibração
        submit_review(session, card, confianca="tenho_certeza", shortcut=1, today=date(2026, 3, 1))
        submit_review(session, card, confianca="tenho_certeza", shortcut=3, today=date(2026, 3, 2))

        report = calibration_report(session)

    assert report["tenho_certeza"]["total"] == 2
    assert report["tenho_certeza"]["acertos"] == 1
    assert report["tenho_certeza"]["taxa_acerto"] == 0.5
    assert report["chutei"]["total"] == 0
    assert report["chutei"]["taxa_acerto"] is None


def test_exam_mode_orders_by_weakness(app_env):
    from sqlalchemy import select

    from app.db import holder
    from app.models import CardProposal, Subject
    from app.study.scheduler import exam_mode_queue, submit_review

    with holder.SessionLocal() as session:
        strong_id = _make_card(session, "TGDC", "Forte", frente="forte")
        weak_id = _make_card(session, "TGDC", "Fraca", frente="fraca")
        never_seen_id = _make_card(session, "TGDC", "Nunca vista", frente="nunca")

        strong = session.get(CardProposal, strong_id)
        weak = session.get(CardProposal, weak_id)
        for _ in range(3):
            submit_review(session, strong, confianca="tenho_certeza", shortcut=3, today=date(2026, 3, 1))
        submit_review(session, weak, confianca="chutei", shortcut=1, today=date(2026, 3, 1))

        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        ordered = exam_mode_queue(session, subject_id)

        ordered_ids = [c.id for c in ordered]
        # nunca vista e fraca vêm antes da forte
        assert ordered_ids.index(strong_id) > ordered_ids.index(weak_id)
        assert ordered_ids.index(strong_id) > ordered_ids.index(never_seen_id)
