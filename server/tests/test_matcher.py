from datetime import date, datetime, timezone

from app.library.gdocs import DriveFile
from app.library.matcher import match_lesson, match_subject
from app.models import Lesson, Subject


def _drive_file(name="doc", modified=None, parents=None):
    return DriveFile(
        id="f1", name=name, modified_time=modified or datetime(2026, 3, 12, tzinfo=timezone.utc), parents=parents or []
    )


def _subject(**kwargs):
    return Subject(nome="Civil", sigla="TGDC", **kwargs)


def test_match_subject_by_direct_parent_folder():
    subject = _subject(drive_folder_id="folder-civil")
    drive_file = _drive_file(parents=["folder-civil"])
    assert match_subject(drive_file, [subject]) is subject


def test_match_subject_none_when_no_folder_configured():
    subject = _subject(drive_folder_id=None)
    drive_file = _drive_file(parents=["folder-civil"])
    assert match_subject(drive_file, [subject]) is None


def test_match_subject_none_when_parent_does_not_match():
    subject = _subject(drive_folder_id="folder-civil")
    drive_file = _drive_file(parents=["folder-penal"])
    assert match_subject(drive_file, [subject]) is None


def test_match_subject_does_not_match_subfolder_only_direct_parent():
    subject = _subject(drive_folder_id="folder-civil")
    drive_file = _drive_file(parents=["folder-civil-subpasta"])
    assert match_subject(drive_file, [subject]) is None


def test_match_lesson_by_date_in_filename():
    lesson_a = Lesson(subject_id=1, titulo="A", data=date(2026, 3, 12))
    lesson_b = Lesson(subject_id=1, titulo="B", data=date(2026, 3, 19))
    drive_file = _drive_file(name="2026-03-19 anotacoes.gdoc")
    assert match_lesson(drive_file, [lesson_a, lesson_b]) is lesson_b


def test_match_lesson_by_alternate_date_format_in_filename():
    lesson = Lesson(subject_id=1, titulo="A", data=date(2026, 3, 12))
    drive_file = _drive_file(name="anotacoes 12.03.2026.gdoc")
    assert match_lesson(drive_file, [lesson]) is lesson


def test_match_lesson_ambiguous_filename_date_does_not_resolve():
    lesson_a = Lesson(subject_id=1, titulo="A", data=date(2026, 3, 12))
    lesson_b = Lesson(subject_id=2, titulo="B", data=date(2026, 3, 12))
    drive_file = _drive_file(name="2026-03-12 anotacoes.gdoc")
    assert match_lesson(drive_file, [lesson_a, lesson_b]) is None


def test_match_lesson_by_modified_time_proximity_when_no_filename_date():
    lesson = Lesson(subject_id=1, titulo="A", data=date(2026, 3, 12))
    drive_file = _drive_file(name="anotacoes soltas", modified=datetime(2026, 3, 13, tzinfo=timezone.utc))
    assert match_lesson(drive_file, [lesson]) is lesson


def test_match_lesson_none_when_outside_proximity_window():
    lesson = Lesson(subject_id=1, titulo="A", data=date(2026, 3, 12))
    drive_file = _drive_file(name="anotacoes soltas", modified=datetime(2026, 3, 20, tzinfo=timezone.utc))
    assert match_lesson(drive_file, [lesson]) is None


def test_match_lesson_none_when_multiple_lessons_within_proximity():
    lesson_a = Lesson(subject_id=1, titulo="A", data=date(2026, 3, 12))
    lesson_b = Lesson(subject_id=1, titulo="B", data=date(2026, 3, 13))
    drive_file = _drive_file(name="anotacoes soltas", modified=datetime(2026, 3, 13, tzinfo=timezone.utc))
    assert match_lesson(drive_file, [lesson_a, lesson_b]) is None


def test_match_lesson_none_without_any_lessons():
    drive_file = _drive_file(name="anotacoes soltas")
    assert match_lesson(drive_file, []) is None
