""""Dominar o guia" (PLANO.md): agendamento posicional, não por
calendário -- deliberadamente separado de `study/scheduler.py` (SM-2 dos
cards), sem import cruzado entre os dois.

Dois mecanismos combinados, não redundantes:

1. **Leitner posicional** (por item): cada `GuiaExercicio` tem uma
   `caixa` (0-5) e uma `posicao_alvo`, medida em número de OUTRAS
   respostas no meio (o contador `Lesson.guia_progresso_posicao_atual`),
   nunca em dias. Acerto sobe caixa (5 = graduado, sai da mesa pra
   sempre); erro zera pra caixa 0. "Lembrei" emendado no MESMO exercício
   (`GuiaExercicio.streak_atual`) pula mais de uma caixa de uma vez --
   pedido explícito do usuário: bater "lembrei" repetido tem que valer
   mais que um único acerto isolado, não só reagendar pro mesmo intervalo.
2. **Mesa de trabalho adaptativa** (agregado): só `Lesson.guia_progresso_mesa_tamanho`
   exercícios ficam `na_mesa=True` (ativos) por vez -- um novo só entra
   do backlog quando outro sai por ter graduado (ou quando o tamanho da
   mesa cresce). O tamanho da mesa respira por sequência (`Lesson.guia_progresso_streak_atual`),
   não por média: "lembrei" emendado abre vaga a mais a cada vez (efeito
   multiplicador do streak, até um teto), "não lembrei" emendado fecha
   vaga mais rápido pelo mesmo motivo; "quase" é neutro e zera a
   sequência. Substituiu uma versão anterior por média móvel de acerto
   que ficava presa no meio (nem 0.85 nem <0.5) sempre que a taxa de
   acerto era só "razoável" -- a mesa nunca crescia mesmo com exercícios
   de sobra no backlog.

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
LIMIAR_ACERTO_SOBE = 0.7   # "Lembrei" -- sobe de caixa
LIMIAR_ACERTO_RESETA = 0.3  # abaixo disso ("Não lembrei") -- reseta pra caixa 0
# Entre os dois limiares ("Quase") -- fica na MESMA caixa, nem avança nem
# reseta, só recalcula posicao_alvo com o gap atual (reaparece no mesmo
# ritmo de antes). Sem essa faixa neutra, "Quase" e "Não lembrei" caíam no
# mesmo "senão" e produziam exatamente o mesmo resultado -- bug real,
# reportado pelo usuário ("os botões não parecem fazer diferença").

MESA_MINIMA = 5
MESA_MAXIMA = 30
# Teto do efeito multiplicador do streak no tamanho da mesa -- sem ele um
# streak muito longo numa sessão de estudo levaria a mesa direto pro
# MESA_MAXIMA de um salto só, pulando o "respirar aos poucos" pretendido.
MESA_STREAK_CAP = 5


def _now():
    return datetime.now(timezone.utc)


@dataclass
class LeitnerResult:
    caixa: int
    posicao_alvo: int | None
    dominado: bool
    streak: int


def apply_leitner(*, caixa: int, streak: int, grau_acerto: float, posicao_atual: int) -> LeitnerResult:
    if grau_acerto >= LIMIAR_ACERTO_SOBE:
        # "Lembrei" emendado (streak >= 1 antes desta resposta) pula mais
        # de uma caixa de uma vez -- efeito multiplicador pedido pelo
        # usuário: 2º "lembrei" seguido pula 2, 3º pula 3, etc.
        nova_streak = streak + 1 if streak >= 0 else 1
        nova_caixa = min(CAIXA_GRADUADO, caixa + nova_streak)
    elif grau_acerto <= LIMIAR_ACERTO_RESETA:
        nova_streak = 0
        nova_caixa = 0
    else:
        nova_streak = 0  # "Quase" -- neutro, nem sobe nem reseta, e zera a sequência
        nova_caixa = caixa

    if nova_caixa >= CAIXA_GRADUADO:
        return LeitnerResult(caixa=CAIXA_GRADUADO, posicao_alvo=None, dominado=True, streak=nova_streak)

    gap = LEITNER_GAPS[nova_caixa]
    return LeitnerResult(caixa=nova_caixa, posicao_alvo=posicao_atual + gap, dominado=False, streak=nova_streak)


def _adjust_mesa_tamanho(lesson: Lesson, grau_acerto: float) -> None:
    """Streak de respostas seguidas na mesma direção, medido na aula
    inteira (`Lesson.guia_progresso_streak_atual`), não por exercício --
    é o tamanho da mesa que respira, não um item específico."""
    streak = lesson.guia_progresso_streak_atual
    if grau_acerto >= LIMIAR_ACERTO_SOBE:
        streak = streak + 1 if streak >= 0 else 1
        delta = min(streak, MESA_STREAK_CAP)
        lesson.guia_progresso_mesa_tamanho = min(MESA_MAXIMA, lesson.guia_progresso_mesa_tamanho + delta)
    elif grau_acerto <= LIMIAR_ACERTO_RESETA:
        streak = streak - 1 if streak <= 0 else -1
        delta = min(abs(streak), MESA_STREAK_CAP)
        lesson.guia_progresso_mesa_tamanho = max(MESA_MINIMA, lesson.guia_progresso_mesa_tamanho - delta)
    else:
        streak = 0  # "Quase" -- neutro, zera a sequência, mesa não muda
    lesson.guia_progresso_streak_atual = streak


def _ativos(session: Session, lesson_id: int) -> list[GuiaExercicio]:
    return list(
        session.scalars(
            select(GuiaExercicio).where(
                GuiaExercicio.lesson_id == lesson_id,
                GuiaExercicio.status == "aceito",
                GuiaExercicio.na_mesa.is_(True),
                GuiaExercicio.dominado_em.is_(None),
            )
        )
    )


def ensure_mesa_filled(session: Session, lesson: Lesson) -> None:
    """Puxa exercícios do backlog (aceitos, nunca admitidos, não
    graduados) pra preencher vagas abertas na mesa -- nunca mais que
    `mesa_tamanho` simultâneos. Quando `mesa_tamanho` encolheu abaixo do
    que já está ativo, expulsa o excedente de volta pro backlog (mantendo
    caixa/histórico -- só sai da roda ativa, não perde progresso) --
    sem isso, uma mesa que cresceu grande nunca voltava a ficar pequena,
    e o usuário nunca via repetição (bug real: 10 ativos com
    mesa_tamanho já encolhido pra 5)."""
    ativos = _ativos(session, lesson.id)
    if len(ativos) > lesson.guia_progresso_mesa_tamanho:
        excedente = len(ativos) - lesson.guia_progresso_mesa_tamanho
        # expulsa os mais "distantes" (maior posicao_alvo) primeiro --
        # mantém ativos justamente os que estavam mais perto de vencer.
        ativos.sort(key=lambda e: (e.posicao_alvo if e.posicao_alvo is not None else 0), reverse=True)
        for exercicio in ativos[:excedente]:
            exercicio.na_mesa = False
            exercicio.posicao_alvo = None
        session.flush()

    count_ativos = len(_ativos(session, lesson.id))
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
    result = apply_leitner(
        caixa=exercicio.caixa,
        streak=exercicio.streak_atual,
        grau_acerto=grau_acerto,
        posicao_atual=lesson.guia_progresso_posicao_atual,
    )
    exercicio.caixa = result.caixa
    exercicio.streak_atual = result.streak
    exercicio.posicao_alvo = result.posicao_alvo
    exercicio.last_reviewed_at = _now()
    if result.dominado:
        exercicio.dominado_em = _now()
        exercicio.na_mesa = False

    _adjust_mesa_tamanho(lesson, grau_acerto)
    session.flush()
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


def set_mesa_tamanho(session: Session, lesson: Lesson, tamanho: int) -> None:
    """Override manual do tamanho da mesa (botões 5/10/15 em /praticar) --
    o ajuste automático em `_adjust_mesa_tamanho` só respira 1 de cada vez
    e fica preso entre os limiares (0.5 a 0.85 de acerto não move nada),
    então sem uma saída manual o usuário fica travado num tamanho pequeno
    mesmo tendo mais exercícios aceitos esperando no backlog."""
    lesson.guia_progresso_mesa_tamanho = max(MESA_MINIMA, min(MESA_MAXIMA, tamanho))
    ensure_mesa_filled(session, lesson)


def pool_status(session: Session, lesson: Lesson) -> dict:
    """Números da mesa pra mostrar na tela -- sem isso o usuário não tem
    como saber quantos exercícios estão "em jogo" agora nem por que
    parecem não se repetir (pedido explícito depois do usuário notar que
    a mesa cresceu sem ele perceber)."""
    exercicios = session.scalars(
        select(GuiaExercicio).where(
            GuiaExercicio.lesson_id == lesson.id, GuiaExercicio.status == "aceito", GuiaExercicio.orfao_em.is_(None)
        )
    ).all()
    ativos = sum(1 for e in exercicios if e.na_mesa and e.dominado_em is None)
    dominados = sum(1 for e in exercicios if e.dominado_em is not None)
    return {
        "ativos": ativos,
        "mesa_tamanho": lesson.guia_progresso_mesa_tamanho,
        "dominados": dominados,
        "total": len(exercicios),
    }


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
