""""Dominar o guia" (PLANO.md): agendamento posicional, não por
calendário -- deliberadamente separado de `study/scheduler.py` (SM-2 dos
cards), sem import cruzado entre os dois.

Dois mecanismos combinados, não redundantes:

1. **Leitner posicional** (por item): cada `GuiaExercicio` tem uma
   `caixa` (0-5) e uma `posicao_alvo`, medida em número de OUTRAS
   respostas no meio (o contador `Lesson.guia_progresso_posicao_atual`),
   nunca em dias. Acerto sobe caixa (5 = graduado, sai da mesa pra
   sempre); erro zera pra caixa 0.
2. **Mesa de trabalho adaptativa** (agregado): só `Lesson.guia_progresso_mesa_tamanho`
   exercícios ficam `na_mesa=True` (ativos) por vez -- um novo só entra
   do backlog quando outro sai por ter graduado. O tamanho da mesa
   respira pela taxa de acerto móvel das últimas ~20 respostas daquela
   aula: vai bem, abre vaga; vai mal, fecha vaga (nunca expulsa quem já
   está na mesa, só trava novas admissões).

`next_exercicio` nunca "esgota" de verdade: sempre devolve o item de
menor `posicao_alvo` entre os ativos -- é o loop contínuo pedido, sem
esperar calendário."""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GuiaExercicio, GuiaExercicioTentativa, Lesson

LEITNER_GAPS = [1, 2, 4, 7, 12]  # gap (em nº de outras respostas) por caixa 0..4; caixa 5 = graduado
CAIXA_GRADUADO = 5
LIMIAR_ACERTO_CAIXA = 0.7

MESA_MINIMA = 5
MESA_MAXIMA = 30
ROLLING_WINDOW = 20
ACERTO_ALTO = 0.85
ACERTO_BAIXO = 0.5


def _now():
    return datetime.now(timezone.utc)


@dataclass
class LeitnerResult:
    caixa: int
    posicao_alvo: int | None
    dominado: bool


def apply_leitner(*, caixa: int, grau_acerto: float, posicao_atual: int) -> LeitnerResult:
    if grau_acerto >= LIMIAR_ACERTO_CAIXA:
        nova_caixa = min(CAIXA_GRADUADO, caixa + 1)
    else:
        nova_caixa = 0

    if nova_caixa >= CAIXA_GRADUADO:
        return LeitnerResult(caixa=CAIXA_GRADUADO, posicao_alvo=None, dominado=True)

    gap = LEITNER_GAPS[nova_caixa]
    return LeitnerResult(caixa=nova_caixa, posicao_alvo=posicao_atual + gap, dominado=False)


def _rolling_accuracy(session: Session, lesson_id: int, window: int = ROLLING_WINDOW) -> float | None:
    tentativas = session.scalars(
        select(GuiaExercicioTentativa)
        .join(GuiaExercicio, GuiaExercicioTentativa.exercicio_id == GuiaExercicio.id)
        .where(GuiaExercicio.lesson_id == lesson_id)
        .order_by(GuiaExercicioTentativa.respondido_em.desc())
        .limit(window)
    ).all()
    if not tentativas:
        return None
    return sum(t.grau_acerto for t in tentativas) / len(tentativas)


def _adjust_mesa_tamanho(lesson: Lesson, rolling_acc: float | None) -> None:
    if rolling_acc is None:
        return
    if rolling_acc >= ACERTO_ALTO:
        lesson.guia_progresso_mesa_tamanho = min(MESA_MAXIMA, lesson.guia_progresso_mesa_tamanho + 1)
    elif rolling_acc < ACERTO_BAIXO:
        lesson.guia_progresso_mesa_tamanho = max(MESA_MINIMA, lesson.guia_progresso_mesa_tamanho - 1)


def ensure_mesa_filled(session: Session, lesson: Lesson) -> None:
    """Puxa exercícios do backlog (aceitos, nunca admitidos, não
    graduados) pra preencher vagas abertas na mesa -- nunca mais que
    `mesa_tamanho` simultâneos."""
    count_ativos = len(
        session.scalars(
            select(GuiaExercicio).where(
                GuiaExercicio.lesson_id == lesson.id,
                GuiaExercicio.status == "aceito",
                GuiaExercicio.na_mesa.is_(True),
                GuiaExercicio.dominado_em.is_(None),
            )
        ).all()
    )
    while count_ativos < lesson.guia_progresso_mesa_tamanho:
        backlog_item = session.scalars(
            select(GuiaExercicio)
            .where(
                GuiaExercicio.lesson_id == lesson.id,
                GuiaExercicio.status == "aceito",
                GuiaExercicio.na_mesa.is_(False),
                GuiaExercicio.dominado_em.is_(None),
                GuiaExercicio.orfao_em.is_(None),
            )
            .order_by(GuiaExercicio.criado_em)
            .limit(1)
        ).first()
        if backlog_item is None:
            break
        backlog_item.na_mesa = True
        backlog_item.posicao_alvo = lesson.guia_progresso_posicao_atual
        count_ativos += 1
        # flush a cada admissão, não só no fim: a sessão é autoflush=False
        # (db.py), então a próxima iteração desta mesma query leria a
        # linha ainda "na_mesa=False" do banco (não vê a mudança em
        # memória) e devolveria sempre o MESMO item, nunca avançando pro
        # próximo do backlog -- bug real, visto no smoke test: só o
        # primeiro exercício era admitido mesmo com vaga sobrando.
        session.flush()
    # commit, não só flush: get_session() não comita no fim da request (só
    # fecha a sessão), então uma admissão feita durante um GET (ex.:
    # next_exercicio chamado por /praticar) precisa persistir sozinha --
    # sem isso, a próxima chamada (ex.: submit_attempt no /responder
    # seguinte) veria o item ainda como "backlog" e o readmitiria, pisando
    # no posicao_alvo que acabou de ser calculado pra ele (bug real, visto
    # no smoke test: posicao_alvo virou "agora" em vez de "agora + gap").
    session.commit()


def next_exercicio(session: Session, lesson: Lesson) -> GuiaExercicio | None:
    ensure_mesa_filled(session, lesson)
    candidates = session.scalars(
        select(GuiaExercicio)
        .where(
            GuiaExercicio.lesson_id == lesson.id,
            GuiaExercicio.status == "aceito",
            GuiaExercicio.na_mesa.is_(True),
            GuiaExercicio.dominado_em.is_(None),
        )
        .order_by(GuiaExercicio.posicao_alvo, GuiaExercicio.id)
    ).first()
    return candidates


def submit_attempt(
    session: Session, exercicio: GuiaExercicio, *, resposta_texto: str | None, grau_acerto: float, confianca: str | None = None
) -> GuiaExercicioTentativa:
    lesson = exercicio.lesson
    grau_acerto = max(0.0, min(1.0, grau_acerto))

    tentativa = GuiaExercicioTentativa(
        exercicio_id=exercicio.id, resposta_texto=resposta_texto, grau_acerto=grau_acerto, confianca=confianca
    )
    session.add(tentativa)

    lesson.guia_progresso_posicao_atual += 1
    result = apply_leitner(caixa=exercicio.caixa, grau_acerto=grau_acerto, posicao_atual=lesson.guia_progresso_posicao_atual)
    exercicio.caixa = result.caixa
    exercicio.posicao_alvo = result.posicao_alvo
    exercicio.last_reviewed_at = _now()
    if result.dominado:
        exercicio.dominado_em = _now()
        exercicio.na_mesa = False

    session.flush()
    rolling_acc = _rolling_accuracy(session, lesson.id)
    _adjust_mesa_tamanho(lesson, rolling_acc)
    ensure_mesa_filled(session, lesson)

    session.commit()
    return tentativa


def manual_adjust(session: Session, exercicio: GuiaExercicio, delta: int) -> None:
    """Botão "reforçar mais" (delta=-1) / "já sei, espaçar mais" (delta=+1)
    -- desloca `posicao_alvo` sem gravar tentativa nem mudar a caixa."""
    lesson = exercicio.lesson
    if exercicio.posicao_alvo is None:
        return
    gap = LEITNER_GAPS[min(exercicio.caixa, len(LEITNER_GAPS) - 1)]
    shift = max(1, gap // 2)
    exercicio.posicao_alvo = max(lesson.guia_progresso_posicao_atual, exercicio.posicao_alvo + delta * shift)
    session.commit()


def mastery_percent(session: Session, lesson_id: int) -> float | None:
    exercicios = session.scalars(
        select(GuiaExercicio).where(
            GuiaExercicio.lesson_id == lesson_id,
            GuiaExercicio.status == "aceito",
            GuiaExercicio.orfao_em.is_(None),
        )
    ).all()
    if not exercicios:
        return None
    dominados = sum(1 for e in exercicios if e.dominado_em is not None)
    return dominados / len(exercicios)
