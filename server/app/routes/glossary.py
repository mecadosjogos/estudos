"""Glossário -- global, atravessa matérias e semestres (PLANO.md, fase
11): lista de termos, página do termo, e as ferramentas de correção
(fundir, renomear, separar, variantes) -- mesmo padrão de `assuntos.py`,
a segunda aplicação da mesma ideia global/datado."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_session
from ..db import get_session
from ..glossary.merge import find_or_create_term, merge_terms, separate_definition
from ..models import Definition, Term, TermAlias, TermPin

router = APIRouter(prefix="/termos", dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _get_term_or_404(session: Session, term_id: int) -> Term:
    term = session.get(Term, term_id)
    if term is None:
        raise HTTPException(status_code=404, detail="termo não encontrado")
    return term


@router.get("")
def list_termos(
    request: Request,
    q: str = "",
    ordenar: str = "alfabetica",
    pendentes: bool = False,
    session: Session = Depends(get_session),
):
    if pendentes:
        # Fila de propostas de todas as aulas num lugar só -- "limpar em
        # lote depois de uma semana de aulas" (PLANO.md), sem entrar
        # aula por aula na tela de aprovação de cada uma.
        pendentes_rows = session.scalars(
            select(Definition).where(Definition.status == "proposto").order_by(Definition.criado_em.desc())
        ).all()
        return templates.TemplateResponse(
            request, "termos.html", {"pendentes_rows": pendentes_rows, "pendentes": True, "q": q, "ordenar": ordenar}
        )

    stmt = select(Term)
    if q.strip():
        stmt = stmt.where(Term.rotulo.ilike(f"%{q.strip()}%"))
    terms = session.scalars(stmt).all()

    counts = dict(
        session.execute(
            select(Definition.term_id, func.count(Definition.id))
            .where(Definition.status == "ativo", Definition.term_id.is_not(None))
            .group_by(Definition.term_id)
        ).all()
    )

    if ordenar == "recentes":
        terms = sorted(terms, key=lambda t: t.criado_em, reverse=True)
    elif ordenar == "definicoes":
        terms = sorted(terms, key=lambda t: counts.get(t.id, 0), reverse=True)
    else:
        terms = sorted(terms, key=lambda t: t.rotulo.lower())

    return templates.TemplateResponse(
        request,
        "termos.html",
        {"terms": terms, "counts": counts, "pendentes": False, "q": q, "ordenar": ordenar},
    )


@router.get("/{term_id}")
def termo_detail(request: Request, term_id: int, session: Session = Depends(get_session)):
    term = _get_term_or_404(session, term_id)

    definitions = session.scalars(
        select(Definition)
        .where(Definition.term_id == term_id, Definition.status == "ativo")
        .order_by(Definition.criado_em)
    ).all()

    pins = {
        pin.subject_id: pin.definition_id
        for pin in session.scalars(select(TermPin).where(TermPin.term_id == term_id))
    }

    outros = session.scalars(select(Term).where(Term.id != term_id).order_by(Term.rotulo)).all()

    return templates.TemplateResponse(
        request,
        "termo_detail.html",
        {"term": term, "definitions": definitions, "pins": pins, "outros": outros},
    )


@router.post("/{term_id}/renomear")
def renomear_termo(term_id: int, rotulo: str = Form(...), session: Session = Depends(get_session)):
    """Só troca o rótulo, não o slug -- mesma regra do assunto: propostas
    futuras da IA com a grafia antiga continuam casando com este termo."""
    term = _get_term_or_404(session, term_id)
    term.rotulo = rotulo.strip() or term.rotulo
    session.commit()
    return RedirectResponse(url=f"/termos/{term_id}", status_code=303)


@router.post("/{term_id}/destacar")
def alternar_destacar(term_id: int, destacar: bool = Form(...), session: Session = Depends(get_session)):
    """O "botão por verbete pra parar de destacar" (PLANO.md): o termo
    continua no glossário e na busca, só some do texto corrido."""
    term = _get_term_or_404(session, term_id)
    term.destacar = destacar
    session.commit()
    return RedirectResponse(url=f"/termos/{term_id}", status_code=303)


@router.post("/{term_id}/fundir")
def fundir_termo(term_id: int, target_id: int = Form(...), session: Session = Depends(get_session)):
    _get_term_or_404(session, term_id)
    _get_term_or_404(session, target_id)
    merge_terms(session, source_id=term_id, target_id=target_id)
    session.commit()
    return RedirectResponse(url=f"/termos/{target_id}", status_code=303)


@router.post("/{term_id}/variantes")
def adicionar_variante(term_id: int, alias: str = Form(...), session: Session = Depends(get_session)):
    """Nada de stemmer -- lista explícita de variantes de flexão (PLANO.md:
    "negócio jurídico"/"negócios jurídicos"), casadas em fronteira de
    palavra por glossary/matcher.py."""
    term = _get_term_or_404(session, term_id)
    alias = alias.strip()
    if alias:
        ja_existe = session.scalar(select(TermAlias.id).where(TermAlias.alias == alias))
        if ja_existe is None:
            session.add(TermAlias(term_id=term.id, alias=alias))
            session.commit()
    return RedirectResponse(url=f"/termos/{term_id}", status_code=303)


@router.post("/{term_id}/variantes/{alias_id}/remover")
def remover_variante(term_id: int, alias_id: int, session: Session = Depends(get_session)):
    alias = session.get(TermAlias, alias_id)
    if alias is None or alias.term_id != term_id:
        raise HTTPException(status_code=404, detail="variante não encontrada")
    session.delete(alias)
    session.commit()
    return RedirectResponse(url=f"/termos/{term_id}", status_code=303)


@router.post("/criar")
def criar_termo(
    termo: str = Form(...),
    definicao_md: str = Form(...),
    citacao_literal: str = Form(""),
    subject_id: int | None = Form(None),
    session: Session = Depends(get_session),
):
    """Criação na mão (PLANO.md: "você também pode selecionar qualquer
    texto no app e criar um verbete"). Nasce direto "ativo", sem
    deriv_key -- não há nada da IA aqui pra reconciliar depois."""
    term = find_or_create_term(session, termo)
    definition = Definition(
        term_id=term.id,
        subject_id=subject_id or None,
        definicao_md=definicao_md.strip(),
        citacao_literal=citacao_literal.strip() or None,
        status="ativo",
        origem="manual",
    )
    session.add(definition)
    session.commit()
    return RedirectResponse(url=f"/termos/{term.id}", status_code=303)


@router.post("/{term_id}/definitions/{definition_id}/editar")
def editar_definicao(
    term_id: int,
    definition_id: int,
    definicao_md: str = Form(...),
    session: Session = Depends(get_session),
):
    definition = session.get(Definition, definition_id)
    if definition is None or definition.term_id != term_id:
        raise HTTPException(status_code=404, detail="definição não encontrada")
    definition.definicao_md = definicao_md.strip()
    definition.editado_em = datetime.now(timezone.utc)
    session.commit()
    return RedirectResponse(url=f"/termos/{term_id}", status_code=303)


@router.post("/{term_id}/definitions/{definition_id}/descartar")
def descartar_definicao(term_id: int, definition_id: int, session: Session = Depends(get_session)):
    """Some do termo sem apagar as outras (PLANO.md)."""
    definition = session.get(Definition, definition_id)
    if definition is None or definition.term_id != term_id:
        raise HTTPException(status_code=404, detail="definição não encontrada")
    definition.status = "descartado"
    session.commit()
    return RedirectResponse(url=f"/termos/{term_id}", status_code=303)


@router.post("/{term_id}/definitions/{definition_id}/separar")
def separar_definicao(
    term_id: int,
    definition_id: int,
    novo_termo: str = Form(...),
    session: Session = Depends(get_session),
):
    """O oposto de fundir: "quando duas coisas viraram um termo só por
    engano" (PLANO.md)."""
    definition = session.get(Definition, definition_id)
    if definition is None or definition.term_id != term_id:
        raise HTTPException(status_code=404, detail="definição não encontrada")
    separate_definition(session, definition_id, novo_termo)
    session.commit()
    return RedirectResponse(url=f"/termos/{term_id}", status_code=303)


@router.post("/{term_id}/fixar")
def fixar_preferencia(
    term_id: int,
    subject_id: int = Form(...),
    definition_id: int = Form(...),
    session: Session = Depends(get_session),
):
    """"Você pode fixar a preferência para uma matéria quando quiser
    resolver na mão" (PLANO.md) -- sobrepõe a ordenação heurística."""
    _get_term_or_404(session, term_id)
    pin = session.scalar(select(TermPin).where(TermPin.term_id == term_id, TermPin.subject_id == subject_id))
    if pin is None:
        session.add(TermPin(term_id=term_id, subject_id=subject_id, definition_id=definition_id))
    else:
        pin.definition_id = definition_id
    session.commit()
    return RedirectResponse(url=f"/termos/{term_id}", status_code=303)


@router.post("/{term_id}/desfixar")
def desfixar_preferencia(term_id: int, subject_id: int = Form(...), session: Session = Depends(get_session)):
    pin = session.scalar(select(TermPin).where(TermPin.term_id == term_id, TermPin.subject_id == subject_id))
    if pin is not None:
        session.delete(pin)
        session.commit()
    return RedirectResponse(url=f"/termos/{term_id}", status_code=303)
