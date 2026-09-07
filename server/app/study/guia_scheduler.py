""""Dominar o guia" (PLANO.md): agendamento posicional, não por
calendário -- deliberadamente separado de `study/scheduler.py` (SM-2 dos
cards), sem import cruzado entre os dois.

Todo o agendamento é POR USUÁRIO: `GuiaLessonProgresso` (uma linha por
usuário+aula) e `GuiaExercicioProgresso` (uma linha por usuário+exercício)
substituem o que antes vivia direto em `Lesson`/`GuiaExercicio` -- decisão
do usuário depois que o sistema virou multiusuário (fase 19): o progresso
de uma pessoa não pode se misturar com o de outra estudando a mesma aula.
`GuiaExercicio` em si (texto, aprovação) continua compartilhado.

Dois mecanismos combinados, não redundantes:

1. **Leitner posicional** (por item): cada `GuiaExercicioProgresso` tem
   uma `caixa` (0-5) e uma `posicao_alvo`, medida em número de OUTRAS
   respostas no meio (o contador `GuiaLessonProgresso.posicao_atual`),
   nunca em dias. Acerto sobe caixa (5 = graduado, sai da mesa pra
   sempre); erro zera pra caixa 0. "Lembrei" emendado no MESMO exercício
   (`GuiaExercicioProgresso.streak_atual`) pula mais de uma caixa de uma
   vez -- pedido explícito do usuário: bater "lembrei" repetido tem que
   valer mais que um único acerto isolado, não só reagendar pro mesmo
   intervalo.
2. **Mesa de trabalho adaptativa** (agregado): só `GuiaLessonProgresso.mesa_tamanho`
   exercícios ficam `na_mesa=True` (ativos) por vez -- um novo só entra
   do backlog quando outro sai por ter graduado (ou quando o tamanho da
   mesa cresce). O tamanho da mesa respira por sequência
   (`GuiaLessonProgresso.streak_atual`), não por média: "lembrei" emendado
   abre vaga a mais a cada vez (efeito multiplicador do streak, até um
   teto), "não lembrei" emendado fecha vaga mais rápido pelo mesmo
   motivo; "quase" é neutro e zera a sequência.

`next_exercicio` nunca "esgota" de verdade: sempre devolve o item de
menor `posicao_alvo` entre os ativos -- é o loop contínuo pedido, sem
esperar calendário."""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from ..models import GuiaExercicio, GuiaExercicioProgresso, GuiaExercicioTentativa, GuiaLessonProgresso, Lesson

LEITNER_GAPS = [1, 2, 4, 7, 12]  # gap (em nº de outras respostas) por caixa 0..4; caixa 5 = graduado
CAIXA_GRADUADO = 5
LIMIAR_ACERTO_SOBE = 0.7   # "Lembrei" -- sobe de caixa
LIMIAR_ACERTO_RESETA = 0.3  # abaixo disso ("Não lembrei") -- reseta pra caixa 0
# Entre os dois limiares ("Quase") -- fica na MESMA caixa, nem avança nem
# reseta, só recalcula posicao_alvo com o gap atual (reaparece no mesmo
# ritmo de antes). Sem essa faixa neutra, "Quase" e "Não lembrei" caíam no
# mesmo "senão" e produziam exatamente o mesmo resultado -- bug real,
# reportado pelo usuário ("os botões não parecem fazer diferença"). O
# botão em si foi removido da UI depois (perdeu sentido com o streak),
# mas `grau_acerto` continua contínuo 0.0-1.0 (ver GuiaExercicioTentativa).

MESA_MINIMA = 5
MESA_MAXIMA = 30
# Teto do efeito multiplicador do streak no tamanho da mesa -- sem ele um
# streak muito longo numa sessão de estudo levaria a mesa direto pro
# MESA_MAXIMA de um salto só, pulando o "respirar aos poucos" pretendido.
MESA_STREAK_CAP = 5


def _now():
    return datetime.now(timezone.utc)


def _get_or_create_lesson_progresso(session: Session, lesson_id: int, user_id: int) -> GuiaLessonProgresso:
    progresso = session.scalar(
        select(GuiaLessonProgresso).where(
            GuiaLessonProgresso.user_id == user_id, GuiaLessonProgresso.lesson_id == lesson_id
        )
    )
    if progresso is None:
        progresso = GuiaLessonProgresso(user_id=user_id, lesson_id=lesson_id, mesa_tamanho=MESA_MINIMA)
        session.add(progresso)
        session.flush()
    return progresso


def _get_or_create_exercicio_progresso(session: Session, exercicio_id: int, user_id: int) -> GuiaExercicioProgresso:
    progresso = session.scalar(
        select(GuiaExercicioProgresso).where(
            GuiaExercicioProgresso.user_id == user_id, GuiaExercicioProgresso.exercicio_id == exercicio_id
        )
    )
    if progresso is None:
        progresso = GuiaExercicioProgresso(user_id=user_id, exercicio_id=exercicio_id)
        session.add(progresso)
        session.flush()
    return progresso


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


def _adjust_mesa_tamanho(lesson_progresso: GuiaLessonProgresso, grau_acerto: float) -> None:
    """Streak de respostas seguidas na mesma direção, medido na aula
    inteira pra este usuário (`GuiaLessonProgresso.streak_atual`), não por
    exercício -- é o tamanho da mesa que respira, não um item específico."""
    streak = lesson_progresso.streak_atual
    if grau_acerto >= LIMIAR_ACERTO_SOBE:
        streak = streak + 1 if streak >= 0 else 1
        delta = min(streak, MESA_STREAK_CAP)
        lesson_progresso.mesa_tamanho = min(MESA_MAXIMA, lesson_progresso.mesa_tamanho + delta)
    elif grau_acerto <= LIMIAR_ACERTO_RESETA:
        streak = streak - 1 if streak <= 0 else -1
        delta = min(abs(streak), MESA_STREAK_CAP)
        lesson_progresso.mesa_tamanho = max(MESA_MINIMA, lesson_progresso.mesa_tamanho - delta)
    else:
        streak = 0  # "Quase" -- neutro, zera a sequência, mesa não muda
    lesson_progresso.streak_atual = streak


def _ativos(session: Session, lesson_id: int, user_id: int) -> list[GuiaExercicioProgresso]:
    return list(
        session.scalars(
            select(GuiaExercicioProgresso)
            .join(GuiaExercicio, GuiaExercicioProgresso.exercicio_id == GuiaExercicio.id)
            .where(
                GuiaExercicio.lesson_id == lesson_id,
                GuiaExercicio.status == "aceito",
                GuiaExercicioProgresso.user_id == user_id,
                GuiaExercicioProgresso.na_mesa.is_(True),
                GuiaExercicioProgresso.dominado_em.is_(None),
            )
        )
    )


def ensure_mesa_filled(session: Session, lesson: Lesson, user_id: int) -> None:
    """Puxa exercícios do backlog (aceitos, nunca admitidos ou expulsos de
    volta, não graduados -- pra ESTE usuário) pra preencher vagas abertas
    na mesa -- nunca mais que `mesa_tamanho` simultâneos. Quando
    `mesa_tamanho` encolheu abaixo do que já está ativo, expulsa o
    excedente de volta pro backlog (mantendo caixa/histórico -- só sai da
    roda ativa, não perde progresso) -- sem isso, uma mesa que cresceu
    grande nunca voltava a ficar pequena, e o usuário nunca via repetição
    (bug real: 10 ativos com mesa_tamanho já encolhido pra 5)."""
    lesson_progresso = _get_or_create_lesson_progresso(session, lesson.id, user_id)

    ativos = _ativos(session, lesson.id, user_id)
    if len(ativos) > lesson_progresso.mesa_tamanho:
        excedente = len(ativos) - lesson_progresso.mesa_tamanho
        # expulsa os mais "distantes" (maior posicao_alvo) primeiro --
        # mantém ativos justamente os que estavam mais perto de vencer.
        ativos.sort(key=lambda p: (p.posicao_alvo if p.posicao_alvo is not None else 0), reverse=True)
        for progresso in ativos[:excedente]:
            progresso.na_mesa = False
            progresso.posicao_alvo = None
        session.flush()

    count_ativos = len(_ativos(session, lesson.id, user_id))
    while count_ativos < lesson_progresso.mesa_tamanho:
        # backlog: aceito, não órfão, e (nunca teve progresso deste
        # usuário) OU (progresso existe mas não está na mesa nem graduado).
        backlog_item = session.scalars(
            select(GuiaExercicio)
            .outerjoin(
                GuiaExercicioProgresso,
                and_(
                    GuiaExercicioProgresso.exercicio_id == GuiaExercicio.id,
                    GuiaExercicioProgresso.user_id == user_id,
                ),
            )
            .where(
                GuiaExercicio.lesson_id == lesson.id,
                GuiaExercicio.status == "aceito",
                GuiaExercicio.orfao_em.is_(None),
                or_(
                    GuiaExercicioProgresso.id.is_(None),
                    and_(
                        GuiaExercicioProgresso.na_mesa.is_(False),
                        GuiaExercicioProgresso.dominado_em.is_(None),
                    ),
                ),
            )
            .order_by(GuiaExercicio.criado_em)
            .limit(1)
        ).first()
        if backlog_item is None:
            break
        progresso = _get_or_create_exercicio_progresso(session, backlog_item.id, user_id)
        progresso.na_mesa = True
        progresso.posicao_alvo = lesson_progresso.posicao_atual
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


def next_exercicio(session: Session, lesson: Lesson, user_id: int) -> GuiaExercicio | None:
    ensure_mesa_filled(session, lesson, user_id)
    row = session.execute(
        select(GuiaExercicio)
        .join(
            GuiaExercicioProgresso,
            and_(
                GuiaExercicioProgresso.exercicio_id == GuiaExercicio.id,
                GuiaExercicioProgresso.user_id == user_id,
            ),
        )
        .where(
            GuiaExercicio.lesson_id == lesson.id,
            GuiaExercicio.status == "aceito",
            GuiaExercicioProgresso.na_mesa.is_(True),
            GuiaExercicioProgresso.dominado_em.is_(None),
        )
        .order_by(GuiaExercicioProgresso.posicao_alvo, GuiaExercicio.id)
    ).first()
    return row[0] if row else None


def submit_attempt(
    session: Session,
    exercicio: GuiaExercicio,
    user_id: int,
    *,
    resposta_texto: str | None,
    grau_acerto: float,
    confianca: str | None = None,
) -> GuiaExercicioTentativa:
    lesson = exercicio.lesson
    grau_acerto = max(0.0, min(1.0, grau_acerto))

    lesson_progresso = _get_or_create_lesson_progresso(session, lesson.id, user_id)
    exercicio_progresso = _get_or_create_exercicio_progresso(session, exercicio.id, user_id)

    tentativa = GuiaExercicioTentativa(
        exercicio_id=exercicio.id, user_id=user_id, resposta_texto=resposta_texto, grau_acerto=grau_acerto, confianca=confianca
    )
    session.add(tentativa)

    lesson_progresso.posicao_atual += 1
    result = apply_leitner(
        caixa=exercicio_progresso.caixa,
        streak=exercicio_progresso.streak_atual,
        grau_acerto=grau_acerto,
        posicao_atual=lesson_progresso.posicao_atual,
    )
    exercicio_progresso.caixa = result.caixa
    exercicio_progresso.streak_atual = result.streak
    exercicio_progresso.posicao_alvo = result.posicao_alvo
    exercicio_progresso.last_reviewed_at = _now()
    if result.dominado:
        exercicio_progresso.dominado_em = _now()
        exercicio_progresso.na_mesa = False

    _adjust_mesa_tamanho(lesson_progresso, grau_acerto)
    session.flush()
    ensure_mesa_filled(session, lesson, user_id)

    session.commit()
    return tentativa


def manual_adjust(session: Session, exercicio: GuiaExercicio, user_id: int, delta: int) -> None:
    """Botão "reforçar mais" (delta=-1) / "já sei, espaçar mais" (delta=+1)
    -- desloca `posicao_alvo` sem gravar tentativa nem mudar a caixa."""
    lesson_progresso = _get_or_create_lesson_progresso(session, exercicio.lesson_id, user_id)
    exercicio_progresso = _get_or_create_exercicio_progresso(session, exercicio.id, user_id)
    if exercicio_progresso.posicao_alvo is None:
        return
    gap = LEITNER_GAPS[min(exercicio_progresso.caixa, len(LEITNER_GAPS) - 1)]
    shift = max(1, gap // 2)
    exercicio_progresso.posicao_alvo = max(
        lesson_progresso.posicao_atual, exercicio_progresso.posicao_alvo + delta * shift
    )
    session.commit()


def set_mesa_tamanho(session: Session, lesson: Lesson, user_id: int, tamanho: int) -> None:
    """Override manual do tamanho da mesa (campo livre em /praticar) -- o
    ajuste automático em `_adjust_mesa_tamanho` respira por streak, mas
    fica limitado ao que o usuário topa esperar; sem uma saída manual a
    pessoa fica presa num tamanho que ela mesma quer mudar na hora."""
    lesson_progresso = _get_or_create_lesson_progresso(session, lesson.id, user_id)
    lesson_progresso.mesa_tamanho = max(MESA_MINIMA, min(MESA_MAXIMA, tamanho))
    ensure_mesa_filled(session, lesson, user_id)


def reset_progresso(session: Session, lesson: Lesson, user_id: int) -> None:
    """Apaga TODO o progresso deste usuário nesta aula -- caixa, streak,
    mesa e histórico de tentativas -- devolvendo ao estado "nunca
    praticada". Botão "Limpar progresso" em /praticar, com confirmação
    explícita (perde tudo, sem como desfazer). Não afeta o progresso de
    outros usuários nem o conteúdo/aprovação dos exercícios."""
    exercicio_ids = [
        row[0] for row in session.execute(select(GuiaExercicio.id).where(GuiaExercicio.lesson_id == lesson.id)).all()
    ]
    if exercicio_ids:
        session.execute(
            delete(GuiaExercicioTentativa).where(
                GuiaExercicioTentativa.user_id == user_id,
                GuiaExercicioTentativa.exercicio_id.in_(exercicio_ids),
            )
        )
        session.execute(
            delete(GuiaExercicioProgresso).where(
                GuiaExercicioProgresso.user_id == user_id,
                GuiaExercicioProgresso.exercicio_id.in_(exercicio_ids),
            )
        )
    session.execute(
        delete(GuiaLessonProgresso).where(
            GuiaLessonProgresso.user_id == user_id, GuiaLessonProgresso.lesson_id == lesson.id
        )
    )
    session.commit()


def pool_status(session: Session, lesson: Lesson, user_id: int) -> dict:
    """Números da mesa pra mostrar na tela -- sem isso o usuário não tem
    como saber quantos exercícios estão "em jogo" agora nem por que
    parecem não se repetir (pedido explícito depois do usuário notar que
    a mesa cresceu sem ele perceber)."""
    lesson_progresso = _get_or_create_lesson_progresso(session, lesson.id, user_id)
    rows = session.execute(
        select(GuiaExercicio, GuiaExercicioProgresso)
        .outerjoin(
            GuiaExercicioProgresso,
            and_(
                GuiaExercicioProgresso.exercicio_id == GuiaExercicio.id,
                GuiaExercicioProgresso.user_id == user_id,
            ),
        )
        .where(GuiaExercicio.lesson_id == lesson.id, GuiaExercicio.status == "aceito", GuiaExercicio.orfao_em.is_(None))
    ).all()
    ativos = sum(1 for _, p in rows if p is not None and p.na_mesa and p.dominado_em is None)
    dominados = sum(1 for _, p in rows if p is not None and p.dominado_em is not None)
    return {
        "ativos": ativos,
        "mesa_tamanho": lesson_progresso.mesa_tamanho,
        "dominados": dominados,
        "total": len(rows),
    }


def mastery_percent(session: Session, lesson_id: int, user_id: int) -> float | None:
    rows = session.execute(
        select(GuiaExercicio, GuiaExercicioProgresso)
        .outerjoin(
            GuiaExercicioProgresso,
            and_(
                GuiaExercicioProgresso.exercicio_id == GuiaExercicio.id,
                GuiaExercicioProgresso.user_id == user_id,
            ),
        )
        .where(
            GuiaExercicio.lesson_id == lesson_id,
            GuiaExercicio.status == "aceito",
            GuiaExercicio.orfao_em.is_(None),
        )
    ).all()
    if not rows:
        return None
    dominados = sum(1 for _, p in rows if p is not None and p.dominado_em is not None)
    return dominados / len(rows)
