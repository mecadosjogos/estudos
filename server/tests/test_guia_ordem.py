""""Dominar o guia": a fila segue o índice do guia, não a ordem do lote
da IA -- bug real da aula 35, cujo lote veio agrupado por tipo e fez a
prática sair "todas as definições, depois todas as lacunas"."""

import json
from datetime import date

SECOES = [
    (
        "1. Retroatividade",
        "### Conceito\n\nRetroatividade é a possibilidade da lei penal alcançar fatos anteriores à vigência.\n\n"
        "### Só em benefício do réu\n\nA lei penal retroage somente em benefício do acusado, por força da Constituição.",
    ),
    (
        "2. Abolitio criminis",
        "Abolitio criminis é a lei nova que descriminaliza a conduta.\n\n"
        "Exemplo: o adultério deixou de ser crime e o carnaval de Roberto ficou impune.",
    ),
]

# Lote agrupado por tipo, como veio o da aula 35.
LOTE = [
    ("definicao", "1. Retroatividade", "O que é retroatividade?", {"resposta": "Possibilidade da lei penal alcançar fatos anteriores à vigência."}),
    ("definicao", "2. Abolitio criminis", "O que é abolitio criminis?", {"resposta": "Lei nova que descriminaliza a conduta."}),
    ("cloze", "1. Retroatividade", "A lei penal retroage somente em benefício do ______.", {"respostas": ["acusado"]}),
    ("aplicacao_caso", "2. Abolitio criminis", "Roberto cometeu adultério no carnaval. Qual conceito se aplica?", {"caso": "adultério deixou de ser crime", "conceito_correto": "abolitio criminis"}),
    ("recordacao_livre", "1. Retroatividade", "Escreva tudo que lembra da seção.", {"pontos_esperados": ["conceito"]}),
]

ORDEM_DO_GUIA = [
    "O que é retroatividade?",
    "A lei penal retroage somente em benefício do ______.",
    "Escreva tudo que lembra da seção.",
    "O que é abolitio criminis?",
    "Roberto cometeu adultério no carnaval. Qual conceito se aplica?",
]


def test_ordenar_segue_o_guia_e_mistura_os_tipos():
    from app.study.guia_ordem import ExercicioParaOrdenar, ordenar

    exercicios = [
        ExercicioParaOrdenar(i, tipo, secao, pergunta, json.dumps(gabarito))
        for i, (tipo, secao, pergunta, gabarito) in enumerate(LOTE)
    ]
    perguntas = {e.id: e.pergunta for e in exercicios}

    assert [perguntas[i] for i in ordenar(SECOES, exercicios)] == ORDEM_DO_GUIA


def test_titulo_com_outra_numeracao_ou_sem_secao_conhecida():
    """`secao_titulo` sem o número ("Abolitio criminis") ou com a numeração
    da consolidação casa do mesmo jeito; título que não existe no guia cai
    na busca pelo guia inteiro, sem ir pro fim."""
    from app.study.guia_ordem import ExercicioParaOrdenar, ordenar

    exercicios = [
        ExercicioParaOrdenar(1, "definicao", "Abolitio criminis", "O que é abolitio criminis?", "{}"),
        ExercicioParaOrdenar(2, "definicao", "Seção inventada", "Retroatividade alcança fatos anteriores?", "{}"),
    ]

    assert ordenar(SECOES, exercicios) == [2, 1]


def test_guia_antigo_sem_guia_secao_ordena_pelo_markdown():
    from app.study.guia_ordem import _secoes_do_markdown

    guia_md = "# Aula\n\n## Árvore de conhecimento\n\n- tudo\n\n## Sumário dos tópicos abordados\n\n1. x\n\n" + "\n\n".join(
        f"## {titulo}\n\n{corpo}" for titulo, corpo in SECOES
    )

    assert [t for t, _ in _secoes_do_markdown(guia_md)] == [t for t, _ in SECOES]


def test_importar_lote_agrupado_por_tipo_entra_na_mesa_na_ordem_do_guia(app_env):
    from sqlalchemy import select

    from app.ai.guia_exercicios import ingest_exercicios_manual_response
    from app.db import holder
    from app.models import GuiaExercicio, GuiaSecao, Lesson, Subject, User
    from app.study.guia_scheduler import next_exercicio, submit_attempt

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson = Lesson(subject_id=subject_id, titulo="Aula com guia", data=date(2026, 3, 12))
        lesson.guia_md = "# Guia\n\n" + "\n\n".join(f"## {t}\n\n{c}" for t, c in SECOES)
        session.add(lesson)
        session.flush()
        for ordem, (titulo, corpo) in enumerate(SECOES):
            session.add(GuiaSecao(lesson_id=lesson.id, ordem=ordem, titulo=titulo, corpo=corpo))
        session.commit()

        resposta = json.dumps(
            {
                "exercicios": [
                    {"tipo": tipo, "secao_titulo": secao, "pergunta": pergunta, "gabarito": gabarito}
                    for tipo, secao, pergunta, gabarito in LOTE
                ]
            },
            ensure_ascii=False,
        )
        ingest_exercicios_manual_response(session, lesson, resposta)

        por_ordem = session.scalars(
            select(GuiaExercicio).where(GuiaExercicio.lesson_id == lesson.id).order_by(GuiaExercicio.ordem)
        ).all()
        assert [e.pergunta for e in por_ordem] == ORDEM_DO_GUIA

        # a mesa inicial entra toda com a mesma posicao_alvo: a primeira
        # questão da tela tem que ser a primeira do guia, não a de menor id.
        user_id = session.scalar(select(User.id))
        primeira = next_exercicio(session, lesson, user_id)
        assert primeira.pergunta == ORDEM_DO_GUIA[0]
        submit_attempt(session, primeira, user_id, resposta_texto=None, grau_acerto=1.0)
        assert next_exercicio(session, lesson, user_id).pergunta == ORDEM_DO_GUIA[1]


def test_rota_reordenar_aula_existente(app_env):
    """Aula cujo lote entrou antes da ordenação (ordem nula, ids agrupados
    por tipo) é consertada pela rota, sem mexer em progresso."""
    from sqlalchemy import select

    from app.db import holder
    from app.main import app
    from app.models import GuiaExercicio, GuiaSecao, Lesson, Subject

    from starlette.testclient import TestClient

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson = Lesson(subject_id=subject_id, titulo="Aula antiga", data=date(2026, 3, 12))
        lesson.guia_md = "# Guia"
        session.add(lesson)
        session.flush()
        for ordem, (titulo, corpo) in enumerate(SECOES):
            session.add(GuiaSecao(lesson_id=lesson.id, ordem=ordem, titulo=titulo, corpo=corpo))
        for i, (tipo, secao, pergunta, gabarito) in enumerate(LOTE):
            session.add(
                GuiaExercicio(
                    lesson_id=lesson.id, deriv_key=f"k{i}", tipo=tipo, secao_titulo=secao, pergunta=pergunta,
                    gabarito_json=json.dumps(gabarito), status="aceito",
                )
            )
        session.commit()
        lesson_id = lesson.id

    client = TestClient(app)
    client.post("/login", data={"username": "admin", "senha": "admin"})
    resposta = client.post(f"/lessons/{lesson_id}/guia/exercicios-reordenar")
    assert resposta.status_code == 200
    assert resposta.json() == {"lesson_id": lesson_id, "ordenados": len(LOTE)}

    with holder.SessionLocal() as session:
        por_ordem = session.scalars(
            select(GuiaExercicio).where(GuiaExercicio.lesson_id == lesson_id).order_by(GuiaExercicio.ordem)
        ).all()
        assert [e.pergunta for e in por_ordem] == ORDEM_DO_GUIA
