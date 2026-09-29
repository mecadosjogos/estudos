"""Locução do "Dominar o guia": texto falado de cada tipo de questão, fila
`tts_exercicios` (pedido da tela, claim, upload por item, conclusão) e o
áudio só valendo enquanto bate com o texto atual da questão."""

import json
from datetime import date


def _authed_client():
    from app.main import app

    from starlette.testclient import TestClient

    client = TestClient(app)
    client.post("/login", data={"username": "admin", "senha": "admin"})
    return client


def _exercicio(tipo, pergunta, gabarito, lesson_id=0, id_=0):
    from app.models import GuiaExercicio

    return GuiaExercicio(
        id=id_,
        lesson_id=lesson_id,
        deriv_key="k",
        tipo=tipo,
        pergunta=pergunta,
        gabarito_json=json.dumps(gabarito),
        status="aceito",
    )


def _lesson_com_exercicios(session, n=2):
    from sqlalchemy import select

    from app.models import GuiaExercicio, Lesson, Subject

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
    lesson = Lesson(subject_id=subject_id, titulo="Aula com guia", data=date(2026, 3, 12))
    lesson.guia_md = "# Guia\n\n## Seção\n\nCorpo."
    session.add(lesson)
    session.flush()
    for i in range(n):
        session.add(
            GuiaExercicio(
                lesson_id=lesson.id,
                deriv_key=f"k{i}",
                tipo="definicao",
                secao_titulo="Seção",
                pergunta=f"O que é a figura {i}?",
                gabarito_json=json.dumps({"resposta": f"É a resposta {i}"}),
                status="aceito",
            )
        )
    session.commit()
    return lesson.id


# --- texto falado ------------------------------------------------------------


def test_texto_falado_por_tipo(app_env):
    from app.study.guia_locucao import texto_pergunta, texto_resposta

    cloze = _exercicio("cloze", "O ______ não é matemática.", {"respostas": ["direito penal"]})
    assert texto_pergunta(cloze) == "O lacuna não é matemática."
    # A resposta não repete a frase da pergunta -- só o que vai nas lacunas.
    assert texto_resposta(cloze) == "Resposta: direito penal."
    duas = _exercicio("cloze", "Lei ______ à época dos ______.", {"respostas": ["vigente", "fatos"]})
    assert texto_resposta(duas) == "Respostas: vigente, fatos."

    lista = _exercicio("lista_ordenada", "Os passos?", {"itens_em_ordem": ["Sanção", "Promulgação", "Publicação"]})
    assert texto_resposta(lista) == "Primeiro: Sanção. Segundo: Promulgação. Terceiro: Publicação."

    arvore = {
        "rotulo": "Interpretação",
        "filhos": [
            {"rotulo": "Quanto ao sujeito", "filhos": [{"rotulo": "Autêntica"}, {"rotulo": "Judicial"}]},
            {"rotulo": "Quanto ao resultado", "filhos": []},
        ],
    }
    hierarquia = _exercicio("hierarquia", "A árvore?", {"arvore_alvo": arvore})
    assert texto_resposta(hierarquia) == (
        "Interpretação: Quanto ao sujeito, Quanto ao resultado. Quanto ao sujeito: Autêntica, Judicial."
    )

    disc = _exercicio("discriminacao", "Diferença?", {"termo_a": "Dolo", "termo_b": "Culpa", "eixo": "Vontade"})
    assert texto_resposta(disc) == "Dolo versus Culpa. Vontade."

    caso = _exercicio(
        "aplicacao_caso",
        "Pegou a tampa da caneta. Qual conceito?",
        {"caso": "O furto (art. 155) exige lesão relevante.", "conceito_correto": "Princípio da insignificância"},
    )
    assert texto_resposta(caso) == "Princípio da insignificância. O furto (artigo 155) exige lesão relevante."

    livre = _exercicio("recordacao_livre", "Tudo sobre legalidade.", {"pontos_esperados": ["**Gênero**", "Duas espécies."]})
    assert texto_resposta(livre) == "Gênero. Duas espécies."


# --- fila e upload ----------------------------------------------------------


def test_pedido_da_tela_enfileira_uma_vez_e_nada_pendente_nao_cria_job(app_env):
    from sqlalchemy import func, select

    from app.db import holder
    from app.models import TranscriptionJob

    client = _authed_client()
    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, n=2)

    assert client.post(f"/lessons/{lesson_id}/guia/locucao").json() == {"pendentes": 4}
    assert client.post(f"/lessons/{lesson_id}/guia/locucao").json() == {"pendentes": 4}

    with holder.SessionLocal() as session:
        total = session.scalar(
            select(func.count(TranscriptionJob.id)).where(TranscriptionJob.target == "tts_exercicios")
        )
    assert total == 1

    # Tudo narrado: o pedido não cria job novo.
    claim = client.get("/api/jobs/next", params={"worker_name": "w", "target": "tts_exercicios"}).json()["job"]
    for item in claim["exercicios_audio"]:
        client.post(
            f"/api/jobs/{claim['id']}/tts-exercicio",
            data={"claim_token": claim["claim_token"], "exercicio_id": item["exercicio_id"], "parte": item["parte"], "hash": item["hash"]},
            files={"audio": ("a.mp3", b"mp3")},
        )
    client.post(
        f"/api/jobs/{claim['id']}/tts-exercicios-concluir",
        json={"claim_token": claim["claim_token"], "narrados": 4, "falhas": []},
    )
    assert client.post(f"/lessons/{lesson_id}/guia/locucao").json() == {"pendentes": 0}
    with holder.SessionLocal() as session:
        pendentes = session.scalar(
            select(func.count(TranscriptionJob.id)).where(
                TranscriptionJob.target == "tts_exercicios", TranscriptionJob.status == "pending"
            )
        )
    assert pendentes == 0


def test_claim_lista_o_que_falta_e_upload_grava_arquivo_e_hash(app_env):
    from app import config
    from app.db import holder
    from app.models import GuiaExercicio, TranscriptionJob

    client = _authed_client()
    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, n=1)

    client.post(f"/lessons/{lesson_id}/guia/locucao")
    claim = client.get("/api/jobs/next", params={"worker_name": "w", "target": "tts_exercicios"}).json()["job"]
    itens = claim["exercicios_audio"]
    assert [(i["parte"], i["texto"]) for i in itens] == [
        ("pergunta", "O que é a figura 0?"),
        ("resposta", "É a resposta 0."),
    ]

    pergunta = itens[0]
    resp = client.post(
        f"/api/jobs/{claim['id']}/tts-exercicio",
        data={"claim_token": claim["claim_token"], "exercicio_id": pergunta["exercicio_id"], "parte": "pergunta", "hash": pergunta["hash"]},
        files={"audio": ("a.mp3", b"voz da pergunta")},
    )
    assert resp.json() == {"ok": True, "descartado": False}

    audio = config.GUIA_AUDIO_DIR / f"lesson-{lesson_id}" / "exercicios" / f"{pergunta['exercicio_id']}-pergunta.mp3"
    assert audio.read_bytes() == b"voz da pergunta"
    with holder.SessionLocal() as session:
        assert session.get(GuiaExercicio, pergunta["exercicio_id"]).audio_pergunta_hash == pergunta["hash"]

    # Concluir com item faltando e algo narrado: reenfileira o resto sozinho.
    client.post(
        f"/api/jobs/{claim['id']}/tts-exercicios-concluir",
        json={"claim_token": claim["claim_token"], "narrados": 1, "falhas": []},
    )
    with holder.SessionLocal() as session:
        assert session.get(TranscriptionJob, claim["id"]).status == "done"
    segundo = client.get("/api/jobs/next", params={"worker_name": "w", "target": "tts_exercicios"}).json()["job"]
    assert [i["parte"] for i in segundo["exercicios_audio"]] == ["resposta"]


def test_concluir_sem_nada_narrado_nao_reenfileira(app_env):
    from sqlalchemy import func, select

    from app.db import holder
    from app.models import TranscriptionJob

    client = _authed_client()
    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, n=1)

    client.post(f"/lessons/{lesson_id}/guia/locucao")
    claim = client.get("/api/jobs/next", params={"worker_name": "w", "target": "tts_exercicios"}).json()["job"]
    client.post(
        f"/api/jobs/{claim['id']}/tts-exercicios-concluir",
        json={"claim_token": claim["claim_token"], "narrados": 0, "falhas": ["1-pergunta", "1-resposta"]},
    )
    with holder.SessionLocal() as session:
        job = session.get(TranscriptionJob, claim["id"])
        assert job.status == "done" and "1-pergunta" in job.error
        assert session.scalar(select(func.count(TranscriptionJob.id)).where(TranscriptionJob.status == "pending")) == 0

    # reenvio idempotente
    again = client.post(
        f"/api/jobs/{claim['id']}/tts-exercicios-concluir",
        json={"claim_token": claim["claim_token"], "narrados": 0, "falhas": []},
    )
    assert again.json() == {"ok": True, "already_received": True}


def test_upload_com_claim_invalido_da_409(app_env):
    from app.db import holder

    client = _authed_client()
    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, n=1)

    client.post(f"/lessons/{lesson_id}/guia/locucao")
    claim = client.get("/api/jobs/next", params={"worker_name": "w", "target": "tts_exercicios"}).json()["job"]
    item = claim["exercicios_audio"][0]
    resp = client.post(
        f"/api/jobs/{claim['id']}/tts-exercicio",
        data={"claim_token": "outro", "exercicio_id": item["exercicio_id"], "parte": "pergunta", "hash": item["hash"]},
        files={"audio": ("a.mp3", b"mp3")},
    )
    assert resp.status_code == 409


def test_questao_editada_descarta_upload_e_invalida_audio(app_env):
    from app.db import holder
    from app.models import GuiaExercicio

    client = _authed_client()
    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, n=1)

    client.post(f"/lessons/{lesson_id}/guia/locucao")
    claim = client.get("/api/jobs/next", params={"worker_name": "w", "target": "tts_exercicios"}).json()["job"]
    pergunta, resposta = claim["exercicios_audio"]

    def subir(item):
        return client.post(
            f"/api/jobs/{claim['id']}/tts-exercicio",
            data={"claim_token": claim["claim_token"], "exercicio_id": item["exercicio_id"], "parte": item["parte"], "hash": item["hash"]},
            files={"audio": ("a.mp3", b"mp3")},
        ).json()

    assert subir(pergunta)["descartado"] is False
    audio_url = f"/lessons/{lesson_id}/guia/exercicios/{pergunta['exercicio_id']}/audio/pergunta.mp3"
    assert client.get(audio_url).status_code == 200

    # A questão muda no meio do lote: o áudio já subido fica velho e o que
    # chega depois (narrado do texto antigo) é descartado.
    with holder.SessionLocal() as session:
        exercicio = session.get(GuiaExercicio, pergunta["exercicio_id"])
        exercicio.pergunta = "Pergunta reescrita?"
        exercicio.gabarito_json = json.dumps({"resposta": "Outra resposta"})
        session.commit()

    assert subir(resposta)["descartado"] is True
    assert client.get(audio_url).status_code == 404


# --- tela de prática ------------------------------------------------------


def test_pratica_so_entrega_url_de_audio_em_dia(app_env):
    from app.db import holder

    client = _authed_client()
    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, n=1)

    page = client.get(f"/lessons/{lesson_id}/guia/praticar").text
    assert 'data-pergunta-url=""' in page
    assert 'data-pergunta-texto="O que é a figura 0?"' in page
    assert 'id="praticar-conteudo"' in page
    assert "/static/guia_praticar.js" in page
    # Sem áudio nenhum na aula, a narração não dá pra escolher.
    assert 'data-narracao-disponivel="0"' in page
    assert 'value="chatterbox" disabled' in page

    client.post(f"/lessons/{lesson_id}/guia/locucao")
    claim = client.get("/api/jobs/next", params={"worker_name": "w", "target": "tts_exercicios"}).json()["job"]
    item = claim["exercicios_audio"][0]
    client.post(
        f"/api/jobs/{claim['id']}/tts-exercicio",
        data={"claim_token": claim["claim_token"], "exercicio_id": item["exercicio_id"], "parte": "pergunta", "hash": item["hash"]},
        files={"audio": ("a.mp3", b"mp3")},
    )

    page = client.get(f"/lessons/{lesson_id}/guia/praticar").text
    assert f'data-pergunta-url="/lessons/{lesson_id}/guia/exercicios/{item["exercicio_id"]}/audio/pergunta.mp3?v={item["hash"]}"' in page
    assert 'data-resposta-url=""' in page
    assert 'data-narracao-disponivel="1"' in page
    assert 'value="chatterbox" disabled' not in page


def test_rota_do_audio_rejeita_parte_desconhecida(app_env):
    from app.db import holder

    client = _authed_client()
    with holder.SessionLocal() as session:
        lesson_id = _lesson_com_exercicios(session, n=1)

    assert client.get(f"/lessons/{lesson_id}/guia/exercicios/1/audio/outra.mp3").status_code == 404
