"""Exportação do corpus inteiro (PLANO.md, fase 14): "árvore de Markdown
com aulas, transcrições, aula editada, glossário, assuntos, materiais e
cards... isso protege contra você querer sair do app, e é a diferença
entre um sistema e uma prisão." Um .zip de arquivos .md puros, sem
depender do app pra ler -- nada de HTML, nada de JS."""

import io
import zipfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..assuntos import normalize_slug
from ..models import (
    Assunto,
    AssuntoCobertura,
    CardProposal,
    Definition,
    EditedBlock,
    Lesson,
    LessonAssunto,
    Material,
    Subject,
    Term,
)


def _lesson_folder(lesson: Lesson) -> str:
    return f"{lesson.data.isoformat()}-{normalize_slug(lesson.titulo)}"


def _transcricao_md(lesson: Lesson) -> str:
    if lesson.transcript is None:
        return "# Transcrição\n\nSem transcrição.\n"
    lines = [f"# Transcrição — {lesson.titulo}\n"]
    for seg in lesson.transcript.segments:
        lines.append(f"[{seg.start_s:.1f}] {seg.text}")
    return "\n".join(lines) + "\n"


def _aula_editada_md(session: Session, lesson: Lesson) -> str:
    blocks = session.scalars(
        select(EditedBlock)
        .where(EditedBlock.lesson_id == lesson.id, EditedBlock.orfao_em.is_(None))
        .order_by(EditedBlock.ordem)
    ).all()
    if not blocks:
        return "# Aula editada\n\nAula ainda não processada.\n"
    lines = [f"# Aula editada — {lesson.titulo}\n"]
    if lesson.resumo:
        lines.append(f"## Resumo\n\n{lesson.resumo}\n")
    for b in blocks:
        lines.append(f"**[{b.tipo}]**\n\n{b.texto}\n")
    return "\n".join(lines)


def _glossario_md(session: Session) -> str:
    lines = ["# Glossário\n"]
    terms = session.scalars(select(Term).order_by(Term.rotulo)).all()
    for term in terms:
        lines.append(f"## {term.rotulo}\n")
        aliases = [a.alias for a in term.aliases]
        if aliases:
            lines.append(f"*Variantes: {', '.join(aliases)}*\n")
        definitions = [d for d in term.definitions if d.status == "ativo"]
        for d in definitions:
            origem = d.subject.sigla if d.subject else "sem matéria"
            lines.append(f"**{origem}**: {d.definicao_md}\n")
            if d.citacao_literal:
                lines.append(f"> \"{d.citacao_literal}\"\n")
    return "\n".join(lines)


def _assuntos_md(session: Session) -> str:
    lines = ["# Assuntos\n"]
    assuntos = session.scalars(select(Assunto).order_by(Assunto.titulo)).all()
    for assunto in assuntos:
        lines.append(f"## {assunto.titulo}\n")
        coberturas = session.scalars(
            select(AssuntoCobertura).where(AssuntoCobertura.assunto_id == assunto.id)
        ).all()
        for c in coberturas:
            lines.append(f"- {c.subject.sigla} — {c.status}")
        links = session.scalars(
            select(LessonAssunto).where(
                LessonAssunto.assunto_id == assunto.id, LessonAssunto.status == "aceito"
            )
        ).all()
        for link in links:
            lesson = session.get(Lesson, link.lesson_id)
            if lesson:
                lines.append(f"- aula: {lesson.titulo} ({lesson.data.isoformat()})")
        lines.append("")
    return "\n".join(lines)


def _materiais_md(session: Session) -> str:
    lines = ["# Materiais\n"]
    materiais = session.scalars(select(Material).order_by(Material.titulo)).all()
    for m in materiais:
        lines.append(f"## {m.titulo}\n")
        lines.append(f"*origem: {m.origem}*\n")
        if m.conteudo_md:
            lines.append(m.conteudo_md + "\n")
        elif m.url:
            lines.append(f"{m.url}\n")
    return "\n".join(lines)


def _cards_md(session: Session, subject: Subject, lesson_ids: list[int]) -> str:
    if not lesson_ids:
        return ""
    cards = session.scalars(
        select(CardProposal).where(CardProposal.lesson_id.in_(lesson_ids), CardProposal.status == "aceito")
    ).all()
    if not cards:
        return ""
    lines = [f"# Cards — {subject.sigla}\n"]
    for c in cards:
        lines.append(f"**P:** {c.frente}\n\n**R:** {c.verso}\n")
    return "\n".join(lines)


def build_corpus_zip(session: Session) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        subjects = session.scalars(select(Subject).order_by(Subject.nome)).all()
        for subject in subjects:
            base = f"{normalize_slug(subject.sigla)}"
            lessons = session.scalars(
                select(Lesson).where(Lesson.subject_id == subject.id).order_by(Lesson.data)
            ).all()
            for lesson in lessons:
                folder = f"{base}/aulas/{_lesson_folder(lesson)}"
                zf.writestr(f"{folder}/transcricao.md", _transcricao_md(lesson))
                zf.writestr(f"{folder}/aula-editada.md", _aula_editada_md(session, lesson))
                if lesson.guia_md:
                    zf.writestr(f"{folder}/guia.md", lesson.guia_md)

            cards_md = _cards_md(session, subject, [l.id for l in lessons])
            if cards_md:
                zf.writestr(f"{base}/cards.md", cards_md)

        zf.writestr("glossario.md", _glossario_md(session))
        zf.writestr("assuntos.md", _assuntos_md(session))
        zf.writestr("materiais.md", _materiais_md(session))

    return buf.getvalue()
