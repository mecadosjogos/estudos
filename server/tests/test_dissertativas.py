"""Dissertativas pelo guia (PLANO.md, fase 13b), de ponta a ponta: o
navegador pede uma questão, a "máquina" (simulada aqui chamando as rotas
/api/ia-local com o token) gera, a pessoa responde com confiança, o juiz
dá um veredito por ponto (com citação conferida), o redator escreve o
feedback, e a pedagogia (pistas graduais, versão melhorada trancada,
reescrita v1 -> v2, espaçamento, discordância) vale no servidor."""

import json
from datetime import date, datetime, timedelta, timezone

from starlette.testclient import TestClient

MAQUINA = {"Authorization": "Bearer test-token"}

RESPOSTA_V1 = (
    "A posse de João se caracteriza pelo corpus, que é o contato físico com o relógio. "
    "Ele usa o relógio todos os dias. Por isso ele é possuidor."
)

SECOES = [
    ("Conceito de posse", "Definição: posse é o exercício de fato de algum dos poderes inerentes à propriedade."),
    ("Elementos da posse", "O corpus é o elemento objetivo, o poder físico sobre a coisa. O animus é o elemento "
     "subjetivo, a intenção de ter a coisa como sua. Savigny exige os dois; Ihering, só o corpus."),
    ("Posse de boa-fé", "É de boa-fé a posse quando o possuidor ignora o vício que impede a aquisição da coisa."),
]


def _client():
    from app.main import app

    return TestClient(app)


def _authed_client():
    client = _client()
    client.post("/login", data={"username": "admin", "senha": "admin"})
    return client


def _lesson_com_guia(session) -> int:
    from sqlalchemy import select

    from app.models import GuiaSecao, Lesson, Subject

    subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
    lesson = Lesson(
        subject_id=subject_id, titulo="Posse", data=date(2026, 3, 12),
        guia_md="# Posse", guia_titulo="Posse no Código Civil",
        guia_arvore_json=json.dumps([{"rotulo": "Posse", "filhos": [{"rotulo": "Elementos", "filhos": []}]}]),
        guia_gerado_em=datetime(2026, 3, 13, tzinfo=timezone.utc),
    )
    session.add(lesson)
    session.flush()
    for i, (titulo, corpo) in enumerate(SECOES, start=1):
        session.add(GuiaSecao(lesson_id=lesson.id, ordem=i, titulo=titulo, corpo=corpo))
    session.commit()
    return lesson.id


def _setup():
    from app.db import holder

    with holder.SessionLocal() as session:
        return _lesson_com_guia(session)


def _maquina_pega():
    job = _client().get("/api/ia-local/next", params={"worker_name": "pc"}, headers=MAQUINA).json()["job"]
    assert job is not None, "a máquina esperava um job na fila"
    return job


def _maquina_responde(job, respostas: dict, modelo="qwen3.5-4b"):
    resp = _client().post(
        f"/api/ia-local/{job['id']}/resultado",
        json={
            "claim_token": job["claim_token"],
            "respostas": [{"id": k, "conteudo": v} for k, v in respostas.items()],
            "motor": "local", "modelo": modelo, "segundos_total": 12.5, "tokens_por_s": 14.0,
        },
        headers=MAQUINA,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


QUESTAO = {
    "tipo": "caso",
    "enunciado": "João acha um relógio perdido e passa a usá-lo como se fosse dele. Ele é possuidor? Fundamente.",
    "criterio_texto": "Identifique os elementos da posse e aplique-os ao caso de João, concluindo se há posse.",
    "rubrica": [
        {"ponto": "O corpus é o poder físico sobre a coisa", "secao": 2, "pista": "Pense no contato com a coisa."},
        {"ponto": "O animus é a intenção de ter a coisa como sua", "secao": 2, "pista": "E a vontade de João?"},
        {"ponto": "A posse de quem ignora o vício é de boa-fé", "secao": 3, "pista": "João sabia que era de outro?"},
    ],
    "resposta_modelo": (
        "João é possuidor. A posse exige o corpus, que é o poder físico sobre a coisa, e o animus, que é a "
        "intenção de ter a coisa como sua: João usa o relógio (corpus) e age como dono (animus). Como ignora o "
        "vício que impede a aquisição, sua posse é de boa-fé."
    ),
}


def _gerar_questao(client, lesson_id) -> dict:
    estado = client.get(f"/lessons/{lesson_id}/dissertativas/estado.json").json()
    assert estado["modo"] == "gerando"
    job = _maquina_pega()
    assert job["tipo"] == "dissertativa_gerar"
    _maquina_responde(job, {"questao": QUESTAO})
    estado = client.get(f"/lessons/{lesson_id}/dissertativas/estado.json").json()
    assert estado["modo"] == "questao"
    return estado["questao"]


def _veredito(trecho, veredito, falta=""):
    return {"trecho_da_resposta": trecho, "veredito": veredito, "o_que_falta": falta}


def _estrutura():
    c = lambda t, a: {"trecho_da_resposta": t, "atende": a}  # noqa: E731
    return {
        "identificou_problema": c("A posse de João se caracteriza", True),
        "usou_conceito_do_material": c("corpus, que é o contato físico com o relógio", True),
        "aplicou_ao_caso": c("Ele usa o relógio todos os dias", True),
        "concluiu": c("frase que não existe na resposta", True),
    }


def _feedback(**extra):
    base = {
        "leitura_da_confianca": "Você marcou seguro e cobriu 1 de 3.",
        "prioridades": [{"ponto_idx": 1, "por_que_importa": "Sem animus não há posse para Savigny.",
                          "sugestao": "Releia a seção 2 e explique a intenção de João.", "secao": 2}],
        "demais_sugestoes": ["Feche com uma conclusão explícita."],
        "pontos_fortes": [
            {"trecho": "corpus, que é o contato físico com o relógio", "por_que_funciona": "define o elemento"},
            {"trecho": "um elogio a algo que você não escreveu", "por_que_funciona": "bajulação"},
        ],
        "fora_do_material": [],
        "estrutura_comentario": "Faltou fechar.",
        "evolucao": [],
        "proximo_passo": "Monte um quadro corpus x animus.",
        "versao_melhorada": "A posse exige corpus e animus...",
        "mensagem_final": "Resposta incompleta: só o corpus apareceu.",
    }
    base.update(extra)
    return base


def _corrigir_v1(client, questao, confianca=4):
    resp = client.post(
        f"/dissertativas/{questao['id']}/responder.json",
        json={"resposta_texto": RESPOSTA_V1, "confianca": confianca, "autoavaliacao_texto": "acho que faltou algo"},
    )
    assert resp.status_code == 200, resp.text
    tentativa = resp.json()["tentativa"]
    assert tentativa["status"] == "julgando"

    job = _maquina_pega()
    # Pode ter uma pré-geração na fila também -- a correção passa na frente.
    assert job["tipo"] == "dissertativa_julgar"
    _maquina_responde(job, {
        "ponto-0": _veredito("corpus, que é o contato físico com o relógio", "coberto"),
        "ponto-1": _veredito("João tinha a intenção de dono", "parcial", "falta o animus"),  # não está na resposta
        "ponto-2": _veredito("", "ausente", "falta a boa-fé"),
        "estrutura": _estrutura(),
    })
    rejulgar = _maquina_pega()
    assert rejulgar["tipo"] == "dissertativa_julgar"
    assert [c["id"] for c in rejulgar["chamadas"]] == ["ponto-1"]
    _maquina_responde(rejulgar, {"ponto-1": _veredito("de novo uma frase inventada", "coberto")})

    redigir = _maquina_pega()
    assert redigir["tipo"] == "dissertativa_redigir"
    _maquina_responde(redigir, {"feedback": _feedback()})
    return tentativa["id"], redigir


def test_estado_sem_guia(app_env):
    from app.db import holder
    from app.models import Lesson, Subject
    from sqlalchemy import select

    with holder.SessionLocal() as session:
        subject_id = session.scalar(select(Subject.id).where(Subject.sigla == "TGDC"))
        lesson = Lesson(subject_id=subject_id, titulo="Sem guia", data=date(2026, 3, 12))
        session.add(lesson)
        session.commit()
        lesson_id = lesson.id
    assert _authed_client().get(f"/lessons/{lesson_id}/dissertativas/estado.json").json()["modo"] == "sem_guia"


def test_geracao_usa_o_guia_e_nao_entrega_a_rubrica(app_env):
    lesson_id = _setup()
    client = _authed_client()
    client.get(f"/lessons/{lesson_id}/dissertativas/estado.json")
    job = _client().get("/api/ia-local/next", params={"worker_name": "pc"}, headers=MAQUINA).json()["job"]
    prompt = job["chamadas"][0]["prompt"]
    assert "Seção 1: Conceito de posse" in prompt
    assert "Posse no Código Civil" in prompt  # visão geral do guia
    _maquina_responde(job, {"questao": QUESTAO})

    estado = client.get(f"/lessons/{lesson_id}/dissertativas/estado.json")
    corpo = estado.text
    questao = estado.json()["questao"]
    assert questao["criterio_texto"].startswith("Identifique")
    assert questao["total_pontos"] == 3
    # A rubrica e as pistas não vão pro navegador antes da resposta.
    assert "animus é a intenção" not in corpo
    assert "E a vontade de João" not in corpo


def test_responder_exige_confianca(app_env):
    lesson_id = _setup()
    client = _authed_client()
    questao = _gerar_questao(client, lesson_id)
    resp = client.post(f"/dissertativas/{questao['id']}/responder.json", json={"resposta_texto": "x", "confianca": 9})
    assert resp.status_code == 400
    resp = client.post(f"/dissertativas/{questao['id']}/responder.json", json={"resposta_texto": "   ", "confianca": 2})
    assert resp.status_code == 400


def test_julgamento_compartilha_prefixo_e_tem_um_ponto_por_chamada(app_env):
    lesson_id = _setup()
    client = _authed_client()
    questao = _gerar_questao(client, lesson_id)
    client.post(f"/dissertativas/{questao['id']}/responder.json", json={"resposta_texto": RESPOSTA_V1, "confianca": 3})
    job = _maquina_pega()
    ids = [c["id"] for c in job["chamadas"]]
    assert ids == ["ponto-0", "ponto-1", "ponto-2", "estrutura"]
    prefixos = {c["sistema"] + c["prompt"].split("TAREFA:")[0] for c in job["chamadas"]}
    assert len(prefixos) == 1  # mesmo prefixo -> cache de prefixo do llama-server
    assert "RESPOSTA DO ESTUDANTE:\n" + RESPOSTA_V1 in job["chamadas"][0]["prompt"]
    assert "Elementos da posse" in job["chamadas"][0]["prompt"]  # material da seção-fonte


def test_fluxo_completo_com_citacao_conferida(app_env):
    lesson_id = _setup()
    client = _authed_client()
    questao = _gerar_questao(client, lesson_id)
    attempt_id, redigir = _corrigir_v1(client, questao)

    prompt_redigir = redigir["chamadas"][0]["prompt"]
    assert "CONFIANÇA QUE O ESTUDANTE DECLAROU ANTES DE ENVIAR: seguro" in prompt_redigir
    assert "acho que faltou algo" in prompt_redigir
    assert "não verificado" in prompt_redigir

    t = client.get(f"/dissertativas/attempts/{attempt_id}.json").json()["tentativa"]
    assert t["status"] == "avaliado"
    vereditos = [p["veredito"] for p in t["pontos"]]
    assert vereditos == ["coberto", "nao_verificado", "ausente"]
    assert t["cobertura"]["soma"] == 1.0 and t["cobertura"]["total"] == 3
    # Elogio sem trecho real some (anti-bajulação).
    assert [p["trecho"] for p in t["feedback"]["pontos_fortes"]] == ["corpus, que é o contato físico com o relógio"]
    # Estrutura: "concluiu" citou algo que não existe -> não conta.
    estrutura = {e["campo"]: e["atende"] for e in t["estrutura"]}
    assert estrutura["concluiu"] is False and estrutura["identificou_problema"] is True
    assert t["modelo"] == "qwen3.5-4b"


def test_pistas_graduais_e_versao_melhorada_trancada(app_env):
    lesson_id = _setup()
    client = _authed_client()
    questao = _gerar_questao(client, lesson_id)
    attempt_id, _ = _corrigir_v1(client, questao)

    t = client.get(f"/dissertativas/attempts/{attempt_id}.json").json()["tentativa"]
    ausente = t["pontos"][2]
    assert "ponto" not in ausente and "pista" not in ausente
    assert "versao_melhorada" not in t["feedback"]
    assert t["feedback"]["versao_melhorada_liberada"] is False

    niveis = []
    for _ in range(3):
        t = client.post(f"/dissertativas/attempts/{attempt_id}/pista/2").json()["tentativa"]
        niveis.append(t["pontos"][2])
    assert niveis[0]["pista"] == "João sabia que era de outro?" and "secao_html" not in niveis[0]
    assert "boa-fé" in niveis[1]["secao_html"] and "ponto" not in niveis[1]
    assert niveis[2]["ponto"] == "A posse de quem ignora o vício é de boa-fé"

    assert client.post(f"/dissertativas/attempts/{attempt_id}/revelar-modelo", json={}).status_code == 403


def test_desisto_revela_e_volta_pra_caixa_zero(app_env):
    from app.db import holder
    from app.models import DissertativaProgresso

    lesson_id = _setup()
    client = _authed_client()
    questao = _gerar_questao(client, lesson_id)
    attempt_id, _ = _corrigir_v1(client, questao)
    t = client.post(f"/dissertativas/attempts/{attempt_id}/revelar-modelo", json={"desisto": True}).json()["tentativa"]
    assert t["feedback"]["versao_melhorada"].startswith("A posse exige")
    with holder.SessionLocal() as session:
        progresso = session.query(DissertativaProgresso).one()
        assert progresso.caixa == 0


def test_reescrita_v2_compara_com_v1_e_libera_versao_melhorada(app_env):
    from app.db import holder
    from app.models import DissertativaProgresso

    lesson_id = _setup()
    client = _authed_client()
    questao = _gerar_questao(client, lesson_id)
    v1_id, _ = _corrigir_v1(client, questao)
    with holder.SessionLocal() as session:
        antes = session.query(DissertativaProgresso).one().proxima_revisao_em

    v2_texto = RESPOSTA_V1 + " Além disso, ele tem animus, a intenção de ter o relógio como seu."
    resp = client.post(
        f"/dissertativas/{questao['id']}/responder.json",
        json={"resposta_texto": v2_texto, "confianca": 3, "tentativa_anterior_id": v1_id, "sugestoes_escolhidas": [0]},
    )
    v2 = resp.json()["tentativa"]
    assert v2["versao"] == 2

    job = _maquina_pega()
    _maquina_responde(job, {
        "ponto-0": _veredito("corpus, que é o contato físico com o relógio", "coberto"),
        "ponto-1": _veredito("ele tem animus, a intenção de ter o relógio como seu", "coberto"),
        "ponto-2": _veredito("", "ausente"),
        "estrutura": _estrutura(),
    })
    redigir = _maquina_pega()
    prompt = redigir["chamadas"][0]["prompt"]
    assert "TENTATIVA ANTERIOR" in prompt
    assert "Releia a seção 2 e explique a intenção de João." in prompt  # a sugestão escolhida
    _maquina_responde(redigir, {"feedback": _feedback(evolucao=[{"ponto_idx": 1, "antes": "parcial", "depois": "coberto"}])})

    t2 = client.get(f"/dissertativas/attempts/{v2['id']}.json").json()["tentativa"]
    assert t2["feedback"]["evolucao"][0]["depois"] == "coberto"
    assert t2["feedback"]["versao_melhorada_liberada"] is True
    # A v1, agora reescrita, também libera.
    t1 = client.get(f"/dissertativas/attempts/{v1_id}.json").json()["tentativa"]
    assert t1["feedback"]["versao_melhorada"].startswith("A posse exige")
    # Reescrever não mexe no espaçamento (só a v1 conta).
    with holder.SessionLocal() as session:
        assert session.query(DissertativaProgresso).one().proxima_revisao_em == antes


def test_discordancia_vira_exemplo_de_calibracao(app_env):
    lesson_id = _setup()
    client = _authed_client()
    questao = _gerar_questao(client, lesson_id)
    attempt_id, _ = _corrigir_v1(client, questao)

    resp = client.post(
        f"/dissertativas/attempts/{attempt_id}/discordo",
        json={"ponto_idx": 0, "veredito_usuario": "parcial", "comentario": "só citei, não expliquei"},
    )
    assert resp.json()["tentativa"]["pontos"][0]["discordado"] is True

    client.post(f"/dissertativas/{questao['id']}/responder.json", json={"resposta_texto": RESPOSTA_V1, "confianca": 2})
    job = _maquina_pega()
    assert "discordou do avaliador" in job["chamadas"][0]["sistema"]
    assert "só citei, não expliquei" in job["chamadas"][0]["sistema"]


def test_questao_vencida_volta_antes_de_questao_nova(app_env):
    from app.db import holder
    from app.models import DissertativaProgresso

    lesson_id = _setup()
    client = _authed_client()
    questao = _gerar_questao(client, lesson_id)
    _corrigir_v1(client, questao)

    # A pré-geração já deixou uma questão nova pronta?
    pre = _client().get("/api/ia-local/next", params={"worker_name": "pc"}, headers=MAQUINA).json()["job"]
    if pre is not None:
        assert pre["tipo"] == "dissertativa_gerar"
        _maquina_responde(pre, {"questao": {**QUESTAO, "enunciado": "Outra questão: Ana achou um relógio e o vendeu sem saber de quem era. Há boa-fé?"}})

    estado = client.get(f"/lessons/{lesson_id}/dissertativas/estado.json").json()
    assert estado["questao"]["motivo"] == "nova"

    with holder.SessionLocal() as session:
        progresso = session.query(DissertativaProgresso).one()
        progresso.proxima_revisao_em = datetime.now(timezone.utc) - timedelta(hours=1)
        session.commit()
    estado = client.get(f"/lessons/{lesson_id}/dissertativas/estado.json").json()
    assert estado["questao"]["id"] == questao["id"]
    assert estado["questao"]["motivo"] == "revisao"


def test_resposta_invalida_da_maquina_vira_erro_e_da_pra_tentar_de_novo(app_env):
    lesson_id = _setup()
    client = _authed_client()
    questao = _gerar_questao(client, lesson_id)
    attempt_id = client.post(
        f"/dissertativas/{questao['id']}/responder.json", json={"resposta_texto": RESPOSTA_V1, "confianca": 1}
    ).json()["tentativa"]["id"]
    job = _maquina_pega()
    _maquina_responde(job, {"ponto-0": {"lixo": True}})
    t = client.get(f"/dissertativas/attempts/{attempt_id}.json").json()["tentativa"]
    assert t["status"] == "erro"
    assert "formato" in t["erro"]

    t = client.post(f"/dissertativas/attempts/{attempt_id}/tentar-de-novo").json()["tentativa"]
    assert t["status"] == "julgando"
    assert _maquina_pega()["tipo"] == "dissertativa_julgar"


def test_resultado_repetido_nao_processa_duas_vezes(app_env):
    lesson_id = _setup()
    client = _authed_client()
    client.get(f"/lessons/{lesson_id}/dissertativas/estado.json")
    job = _maquina_pega()
    assert _maquina_responde(job, {"questao": QUESTAO})["already_received"] is False
    assert _maquina_responde(job, {"questao": QUESTAO})["already_received"] is True

    from app.db import holder
    from app.models import DissertativaQuestion

    with holder.SessionLocal() as session:
        assert session.query(DissertativaQuestion).count() == 1


def test_questao_legada_fica_so_leitura(app_env):
    from app.db import holder
    from app.models import DissertativaQuestion

    with holder.SessionLocal() as session:
        q = DissertativaQuestion(enunciado="Questão antiga sobre posse.", rubrica_json=json.dumps(["corpus", "animus"]))
        session.add(q)
        session.commit()
        qid = q.id
    client = _authed_client()
    resp = client.get(f"/dissertativas/{qid}")
    assert resp.status_code == 200
    assert "Questão antiga sobre posse." in resp.text
    assert "corpus" in resp.text
    assert client.post(f"/dissertativas/{qid}/responder.json", json={"resposta_texto": "x", "confianca": 2}).status_code == 400
    assert "Questão antiga" in client.get("/dissertativas").text


def test_pagina_da_aula_aponta_pra_pratica(app_env):
    lesson_id = _setup()
    from app.db import holder
    from app.models import Transcript

    with holder.SessionLocal() as session:
        session.add(Transcript(lesson_id=lesson_id, engine="e", worker_name="w", full_text="x", duration_s=1.0))
        session.commit()
    client = _authed_client()
    assert f"/lessons/{lesson_id}/dissertativas" in client.get(f"/lessons/{lesson_id}").text
    pagina = client.get(f"/lessons/{lesson_id}/dissertativas")
    assert pagina.status_code == 200
    assert "ditado.js" in pagina.text
    assert "Posse" in client.get("/dissertativas").text


def test_calibracao_mostra_superconfianca(app_env):
    lesson_id = _setup()
    client = _authed_client()
    questao = _gerar_questao(client, lesson_id)
    _corrigir_v1(client, questao, confianca=4)  # "seguro", cobriu 1 de 3
    pagina = client.get("/dissertativas/calibracao").text
    assert "superconfiante" in pagina


def test_texto_que_entrega_ponto_nao_revelado_fica_escondido(app_env):
    """O modelo local tende a escrever a resposta pronta nas sugestões --
    isso atropelaria as pistas graduais. O servidor esconde o texto até o
    ponto ser revelado."""
    lesson_id = _setup()
    client = _authed_client()
    questao = _gerar_questao(client, lesson_id)
    client.post(f"/dissertativas/{questao['id']}/responder.json", json={"resposta_texto": RESPOSTA_V1, "confianca": 2})
    _maquina_responde(_maquina_pega(), {
        "ponto-0": _veredito("corpus, que é o contato físico com o relógio", "coberto"),
        "ponto-1": _veredito("", "ausente"),
        "ponto-2": _veredito("", "ausente"),
        "estrutura": _estrutura(),
    })
    vazando = "Escreva que a posse de quem ignora o vício é de boa-fé."
    _maquina_responde(_maquina_pega(), {"feedback": _feedback(
        prioridades=[{"ponto_idx": 2, "por_que_importa": "x", "sugestao": vazando, "secao": 3}],
        proximo_passo="Lembre que o animus é a intenção de ter a coisa como sua.",
    )})

    t = client.get("/dissertativas/attempts/1.json").json()["tentativa"]
    assert vazando not in json.dumps(t, ensure_ascii=False)
    assert t["feedback"]["prioridades"][0]["sugestao"] is None
    assert t["feedback"]["prioridades"][0]["sugestao_escondida_ponto"] == 2
    assert t["feedback"]["proximo_passo"] is None and t["feedback"]["escondidos"]["proximo_passo"] == 1

    for _ in range(3):
        t = client.post("/dissertativas/attempts/1/pista/2").json()["tentativa"]
    assert t["feedback"]["prioridades"][0]["sugestao"] == vazando
    assert t["feedback"]["proximo_passo"] is None  # o ponto 1 continua escondido


def test_criterio_que_entrega_a_rubrica_vira_generico(app_env):
    lesson_id = _setup()
    client = _authed_client()
    client.get(f"/lessons/{lesson_id}/dissertativas/estado.json")
    vazando = {**QUESTAO, "criterio_texto": "Explique que o animus é a intenção de ter a coisa como sua."}
    _maquina_responde(_maquina_pega(), {"questao": vazando})
    questao = client.get(f"/lessons/{lesson_id}/dissertativas/estado.json").json()["questao"]
    assert "animus" not in questao["criterio_texto"]
    assert questao["criterio_texto"].startswith("Identifique a questão jurídica")



def test_resposta_certa_vem_com_a_questao_e_entra_na_correcao(app_env):
    """A resposta certa é gerada junto com a questão e serve de referência
    pro juiz (evita o modelo local fugir do assunto) -- mas só aparece pra
    pessoa depois da correção, atrás de um clique."""
    from app.db import holder
    from app.models import DissertativaProgresso

    lesson_id = _setup()
    client = _authed_client()
    questao = _gerar_questao(client, lesson_id)
    assert "resposta_modelo" not in json.dumps(questao)  # nada antes de responder
    client.post(f"/dissertativas/{questao['id']}/responder.json", json={"resposta_texto": RESPOSTA_V1, "confianca": 3})
    julgar = _maquina_pega()
    assert "RESPOSTA DE REFERÊNCIA" in julgar["chamadas"][0]["prompt"]
    assert "age como dono (animus)" in julgar["chamadas"][0]["prompt"]
    _maquina_responde(julgar, {
        "ponto-0": _veredito("corpus, que é o contato físico com o relógio", "coberto"),
        "ponto-1": _veredito("", "ausente"), "ponto-2": _veredito("", "ausente"), "estrutura": _estrutura(),
    })
    redigir = _maquina_pega()
    assert "RESPOSTA DE REFERÊNCIA" in redigir["chamadas"][0]["prompt"]
    _maquina_responde(redigir, {"feedback": _feedback()})

    t = client.get("/dissertativas/attempts/1.json").json()["tentativa"]
    assert t["resposta_certa_existe"] is True and t["resposta_certa"] is None
    assert t["resposta_certa_sem_custo"] is False
    with holder.SessionLocal() as session:
        session.query(DissertativaProgresso).one().caixa = 2
        session.commit()
    t = client.post("/dissertativas/attempts/1/resposta-certa").json()["tentativa"]
    assert t["resposta_certa"].startswith("João é possuidor")
    with holder.SessionLocal() as session:
        assert session.query(DissertativaProgresso).one().caixa == 0  # abrir antes de reescrever = desistência


def test_fila_mostra_correcao_e_nao_prende_a_tela(app_env):
    lesson_id = _setup()
    client = _authed_client()
    questao = _gerar_questao(client, lesson_id)
    client.post(f"/dissertativas/{questao['id']}/responder.json", json={"resposta_texto": RESPOSTA_V1, "confianca": 3})

    # A tela já pode seguir: o estado não fica preso na correção.
    estado = client.get(f"/lessons/{lesson_id}/dissertativas/estado.json").json()
    assert estado["modo"] in ("questao", "gerando")

    fila = client.get(f"/lessons/{lesson_id}/dissertativas/fila.json").json()
    assert fila["correcoes"][0]["estado"] == "na_fila"
    assert fila["correcoes"][0]["posicao"] == 0  # correção passa na frente da pré-geração
    assert fila["geracao"]["posicao"] >= 1

    job = _maquina_pega()
    assert job["tipo"] == "dissertativa_julgar"
    fila = client.get(f"/lessons/{lesson_id}/dissertativas/fila.json").json()
    assert fila["correcoes"][0]["estado"] == "em_correcao"

    _maquina_responde(job, {
        "ponto-0": _veredito("corpus, que é o contato físico com o relógio", "coberto"),
        "ponto-1": _veredito("", "ausente"), "ponto-2": _veredito("", "ausente"), "estrutura": _estrutura(),
    })
    _maquina_responde(_maquina_pega(), {"feedback": _feedback()})
    fila = client.get(f"/lessons/{lesson_id}/dissertativas/fila.json").json()
    c = fila["correcoes"][0]
    assert c["estado"] == "corrigida" and c["vista"] is False and c["cobertura"]["total"] == 3
    client.get(f"/dissertativas/attempts/{c['attempt_id']}.json?marcar_vista=1")
    assert client.get(f"/lessons/{lesson_id}/dissertativas/fila.json").json()["correcoes"][0]["vista"] is True


def test_lote_do_claude_entra_no_banco(app_env):
    lesson_id = _setup()
    client = _authed_client()
    pacote = client.get(f"/lessons/{lesson_id}/dissertativas/pacote-claude.md?n=2")
    assert pacote.status_code == 200
    assert "Seção 3: Posse de boa-fé" in pacote.text and "resposta_modelo" in pacote.text

    lote = {"questoes": [{**QUESTAO, "secoes": [2, 3]}]}
    resp = client.post(
        f"/lessons/{lesson_id}/dissertativas/importar",
        content=("Aqui está:\n```json\n" + json.dumps(lote, ensure_ascii=False) + "\n```").encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    assert resp.status_code == 200, resp.text
    from app.db import holder
    from app.models import DissertativaQuestion

    with holder.SessionLocal() as session:
        q = session.query(DissertativaQuestion).one()
        assert q.origem == "claude" and q.resposta_modelo.startswith("João é possuidor")
    estado = client.get(f"/lessons/{lesson_id}/dissertativas/estado.json").json()
    assert estado["questao"]["origem"] == "claude"

    ruim = {"questoes": [{**QUESTAO, "secoes": [9]}]}
    resp = client.post(f"/lessons/{lesson_id}/dissertativas/importar", content=json.dumps(ruim).encode())
    assert resp.status_code == 400 and "seção" in resp.json()["detail"]
