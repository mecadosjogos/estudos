"""Dissertativa pelo guia, corrigida pela IA local (PLANO.md, fase 13b).

Substitui o fluxo da fase 13 (questão tirada da transcrição, ponte manual
de colar JSON). Três passadas, cada uma um job em `ai/fila_local.py` que o
ouvinte na máquina com GPU executa:

1. GERAR -- a partir de 1 a 3 seções do GUIA da aula, uma questão que cobra
   raciocínio, com o "o que a questão pede" (mostrado antes de escrever) e
   uma rubrica de 3 a 6 pontos verificáveis, cada um com a seção de origem e
   uma pista que ajuda a lembrar sem entregar.
2. JULGAR -- UMA chamada por ponto da rubrica, mais uma de estrutura. O juiz
   copia o trecho da resposta ANTES de dar o veredito (coberto / parcial /
   ausente), e o servidor confere se o trecho existe (`ai/citacoes.py`).
   Trecho inventado -> julga aquele ponto de novo uma vez -> se continuar,
   "não verificado". Todas as chamadas compartilham o mesmo prefixo (regras,
   material, enunciado, resposta) e só a TAREFA no fim muda: o llama-server
   reaproveita o cache do prefixo e só o primeiro ponto paga o prefill.
3. REDIGIR -- o feedback pedagógico, escrito a partir dos vereditos já
   conferidos: o redator não julga de novo, só ensina.

Por que o guia como fonte, se o princípio do projeto é "a aula editada é
leitura, nunca fonte": aqui a correção é declaradamente contra O MATERIAL
(o que foi dado), não contra a lei -- decisão do usuário, registrada no
PLANO.md. O guia já é o material que se estuda; a dissertativa treina
escrever sobre ele. Mesmo precedente do "Dominar o guia".

Sem nota numérica (decisão da fase 13 que continua valendo): o que se
mostra é "X de Y pontos".
"""

import json
from datetime import datetime, timezone

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    DISSERTATIVA_CONFIANCAS,
    AiCall,
    DissertativaAttempt,
    DissertativaDiscordancia,
    DissertativaQuestion,
    GuiaSecao,
    IaLocalJob,
    Lesson,
)
from . import fila_local
from .citacoes import entrega_o_ponto, trecho_existe
from .pipeline import ProcessingError
from .schemas import (
    DissertativaFeedbackOut,
    DissertativaQuestionGuiaOut,
    DissertativasLoteOut,
    EstruturaOut,
    VereditoPontoOut,
)

MAX_CHARS_POR_SECAO = 6000
MAX_CHARS_SECOES_ALVO = 12000
# Seção curta demais rende questão rasa: junta com a seguinte até aqui.
CHARS_MINIMOS_ALVO = 1500
MAX_SECOES_ALVO = 3
MAX_EXEMPLOS_CALIBRACAO = 3
# Uma rodada de re-julgamento pros pontos com citação que não conferiu.
MAX_RODADAS_REJULGAMENTO = 1

VALOR_VEREDITO = {"coberto": 1.0, "parcial": 0.5, "ausente": 0.0, "nao_verificado": 0.0}

ROTULOS_ESTRUTURA = {
    "identificou_problema": "identificou o problema",
    "usou_conceito_do_material": "usou o conceito do material",
    "aplicou_ao_caso": "aplicou ao caso",
    "concluiu": "concluiu",
}


# --- guia: seções, visão geral ------------------------------------------------


def secoes_da_aula(session: Session, lesson_id: int) -> list[GuiaSecao]:
    return list(
        session.scalars(select(GuiaSecao).where(GuiaSecao.lesson_id == lesson_id).order_by(GuiaSecao.ordem)).all()
    )


def _numerar(secoes: list[GuiaSecao]) -> dict[int, GuiaSecao]:
    """Número da seção (1..N) como aparece na página do guia -- a âncora
    `#secao-N` de guia.html é a posição, não `GuiaSecao.ordem`."""
    return {i: s for i, s in enumerate(secoes, start=1)}


def _arvore_em_texto(nos: list[dict], nivel: int = 0) -> list[str]:
    linhas = []
    for no in nos:
        linhas.append("  " * nivel + "- " + str(no.get("rotulo", "")).strip())
        linhas.extend(_arvore_em_texto(no.get("filhos") or [], nivel + 1))
    return linhas


def visao_geral_do_guia(lesson: Lesson, secoes: list[GuiaSecao]) -> str:
    partes = [f"Título: {lesson.guia_titulo or lesson.titulo}"]
    if lesson.guia_arvore_json:
        try:
            arvore = json.loads(lesson.guia_arvore_json)
        except ValueError:
            arvore = []
        if arvore:
            partes.append("Árvore de conhecimento:\n" + "\n".join(_arvore_em_texto(arvore)))
    partes.append("Seções:\n" + "\n".join(f"{n}. {s.titulo}" for n, s in _numerar(secoes).items()))
    texto = "\n\n".join(partes)
    return texto[:3000]


def texto_das_secoes(numeradas: list[tuple[int, GuiaSecao]]) -> str:
    blocos = []
    total = 0
    for numero, secao in numeradas:
        corpo = secao.corpo.strip()[:MAX_CHARS_POR_SECAO]
        bloco = f"### Seção {numero}: {secao.titulo}\n{corpo}"
        if total + len(bloco) > MAX_CHARS_SECOES_ALVO and blocos:
            break
        blocos.append(bloco)
        total += len(bloco)
    return "\n\n".join(blocos)


def normalizar_rubrica(rubrica_json: str) -> list[dict]:
    """Legado (fase 13) guarda `list[str]`; o fluxo pelo guia guarda
    `[{ponto, secao, pista}]`. Quem lê recebe sempre a forma nova."""
    try:
        itens = json.loads(rubrica_json)
    except ValueError:
        return []
    normal = []
    for item in itens:
        if isinstance(item, str):
            normal.append({"ponto": item, "secao": None, "pista": ""})
        else:
            normal.append({"ponto": item.get("ponto", ""), "secao": item.get("secao"), "pista": item.get("pista", "")})
    return normal


def secoes_fonte(session: Session, question: DissertativaQuestion) -> list[tuple[int, GuiaSecao]]:
    """As seções de onde a questão saiu, no guia ATUAL da aula. Casadas por
    título (e, na falta, pelo número): o guia é recriado a cada
    reprocessamento, então o id não serve."""
    if question.lesson_id is None:
        return []
    numeradas = _numerar(secoes_da_aula(session, question.lesson_id))
    por_titulo = {s.titulo.strip().lower(): (n, s) for n, s in numeradas.items()}
    guardadas = json.loads(question.secoes_json or "[]")
    achadas = []
    for ref in guardadas:
        par = por_titulo.get(str(ref.get("titulo", "")).strip().lower())
        if par is None and ref.get("numero") in numeradas:
            par = (ref["numero"], numeradas[ref["numero"]])
        if par is not None and par not in achadas:
            achadas.append(par)
    return achadas


def escolher_secoes_alvo(
    session: Session, lesson: Lesson, secao_numero: int | None = None
) -> list[tuple[int, GuiaSecao]]:
    numeradas = _numerar(secoes_da_aula(session, lesson.id))
    if not numeradas:
        raise ProcessingError("esta aula ainda não tem guia estruturado — processe a aula antes")

    if secao_numero is not None:
        if secao_numero not in numeradas:
            raise ProcessingError(f"a seção {secao_numero} não existe no guia desta aula")
        inicio = secao_numero
    else:
        # A seção menos usada pelas questões que já existem, pra variar o
        # que se treina; empate fica com a primeira (determinístico).
        uso = {n: 0 for n in numeradas}
        existentes = session.scalars(
            select(DissertativaQuestion.secoes_json).where(
                DissertativaQuestion.lesson_id == lesson.id, DissertativaQuestion.fonte == "guia"
            )
        ).all()
        titulos = {s.titulo.strip().lower(): n for n, s in numeradas.items()}
        for secoes_json in existentes:
            for ref in json.loads(secoes_json or "[]"):
                n = titulos.get(str(ref.get("titulo", "")).strip().lower())
                if n is not None:
                    uso[n] += 1
        inicio = min(uso, key=lambda n: (uso[n], n))

    escolhidas = [(inicio, numeradas[inicio])]
    tamanho = len(numeradas[inicio].corpo)
    proximo = inicio + 1
    while tamanho < CHARS_MINIMOS_ALVO and proximo in numeradas and len(escolhidas) < MAX_SECOES_ALVO:
        escolhidas.append((proximo, numeradas[proximo]))
        tamanho += len(numeradas[proximo].corpo)
        proximo += 1
    return escolhidas


# --- prompts --------------------------------------------------------------------

CRITERIO_GENERICO = (
    "Identifique a questão jurídica em jogo, fundamente com o conteúdo do material, "
    "aplique aos fatos do enunciado e feche com uma conclusão clara."
)

# Campos do feedback que aparecem ANTES de a pessoa abrir as pistas. Se algum
# repete o conteúdo de um ponto que ela não cobriu, fica escondido até esse
# ponto ser revelado -- ver `_marcar_vazamentos`.
CAMPOS_VISIVEIS = ("leitura_da_confianca", "estrutura_comentario", "proximo_passo", "mensagem_final")

INSTRUCOES_GERAR = """Você cria questões dissertativas de Direito para um estudante treinar para a prova, a partir do GUIA DE ESTUDO da aula (o material abaixo).

Regras:
1. A questão cobra RACIOCÍNIO com o conteúdo do material: um caso concreto curto para resolver, uma comparação entre dois institutos, a explicação do porquê de uma regra, ou uma crítica fundamentada. Nunca "o que é X?" nem "defina X".
2. Tudo o que a resposta precisa conter tem de estar NO MATERIAL. Não exija lei, artigo, doutrina ou jurisprudência que o material não traga (se o material cita um artigo, pode exigir).
3. enunciado: 2 a 4 frases, no estilo de prova. Se for caso, dê nomes e fatos concretos.
4. criterio_texto: 1 ou 2 frases dizendo O QUE a resposta deve FAZER, em operações genéricas, SEM nomear o conceito, o instituto ou o autor que responde à questão.
   Errado (entrega a resposta): "Explique como o poder econômico, segundo Bobbio, explica a conduta de João."
   Certo: "Identifique qual forma de poder está em jogo, fundamente com o material e aplique aos fatos, concluindo sobre a conduta de João."
5. rubrica: de 3 a 6 pontos que uma resposta completa precisa conter. Cada ponto é UMA ideia verificável (dá para dizer sim ou não se a resposta tem), escrita como afirmação do conteúdo esperado. Em "secao", o número da seção do material de onde o ponto sai.
6. pista de cada ponto: uma pergunta ou direção que ajude o estudante a lembrar, SEM dizer a resposta (por exemplo: "Pense no que o possuidor precisa ter além do contato físico com a coisa.").
7. tipo: "caso", "comparacao", "explicacao" ou "critica".
8. resposta_modelo: a RESPOSTA CERTA, como um bom aluno escreveria na prova — 2 a 4 parágrafos que cobrem TODOS os pontos da rubrica, identificam o problema, fundamentam com o material, aplicam aos fatos e concluem. Só com conteúdo do material.

Escreva em português do Brasil. Devolva só o JSON."""

INSTRUCOES_AVALIADOR = """Você avalia a resposta de um estudante a uma questão dissertativa de Direito. A avaliação é SÓ contra o MATERIAL abaixo (seções do guia de estudo da aula) — não contra a lei, a doutrina ou o que você sabe por fora. Você faz UMA tarefa por vez, descrita no fim, em TAREFA.

Regras gerais:
- Primeiro copie o trecho da resposta que serve de evidência, com as palavras do próprio estudante (cópia literal e curta: uma frase ou parte dela). Só depois decida. Se não há trecho, deixe "".
- Seja rigoroso e justo: sinônimo ou paráfrase correta conta; menção vaga que não mostra entendimento é "parcial"; ideia errada ou ausente é "ausente".
- Não premie texto longo por ser longo.
- Se houver RESPOSTA DE REFERÊNCIA, use-a para entender o que uma resposta completa contém — mas quem manda é o MATERIAL: se as duas divergirem, vale o material. O estudante NÃO precisa usar as palavras da referência; ideia equivalente e correta conta como coberta."""

TAREFA_PONTO = """TAREFA: avaliar se a resposta contém este ponto da rubrica:
«{ponto}»

- veredito "coberto": a ideia está na resposta, correta e completa.
- "parcial": aparece, mas incompleta, imprecisa ou sem a explicação necessária.
- "ausente": não aparece, ou aparece errada.
- o_que_falta: se parcial ou ausente, diga em 1 frase o que falta, nos termos do material; se coberto, "".

Responda só o JSON."""

TAREFA_ESTRUTURA = """TAREFA: avaliar a ESTRUTURA da resposta em 4 critérios. Para cada um, primeiro o trecho da resposta que mostra o critério, depois "atende" (true ou false):
- identificou_problema: identifica a questão jurídica que o enunciado pede.
- usou_conceito_do_material: fundamenta com um conceito ou instituto do material (não só opinião).
- aplicou_ao_caso: aplica o conceito aos fatos ou à situação do enunciado (em questão de explicação ou crítica: desenvolve o raciocínio em vez de só enunciar).
- concluiu: fecha com uma conclusão clara que responde ao enunciado.

Responda só o JSON."""

INSTRUCOES_REDIGIR = """Você é um professor-mentor de Direito escrevendo o retorno de uma dissertativa para um estudante, com um objetivo: que ele APRENDA e escreva melhor na próxima vez — não só saber como foi. A correção ponto a ponto JÁ FOI FEITA (abaixo, em AVALIAÇÃO): não reavalie, ensine a partir dela. Tudo contra o MATERIAL (guia da aula), nunca contra conteúdo de fora.

Regras:
- Fale com o estudante em segunda pessoa ("você"), em tom gentil, direto e específico. Nada de elogio genérico ("muito bem!", "ótima resposta") nem de exagero.
- leitura_da_confianca: 1 frase comparando a confiança que ele declarou ANTES com o resultado (por exemplo: marcou "seguro" e cobriu 2 de 5 → sinal para desconfiar dessa sensação neste tema; marcou "inseguro" e cobriu quase tudo → sabe mais do que acha).
- prioridades: no máximo 3, as que mais melhorariam a resposta, da mais importante para a menos. Para cada uma: ponto_idx (o número do ponto na AVALIAÇÃO, ou -1 se for de estrutura), por_que_importa (por que isso pesa numa prova de Direito), sugestao, secao (número da seção).
  A sugestao diz O QUE FAZER, como ação, e aponta a seção — mas NUNCA diz o conteúdo que faltou: o estudante vai descobrir sozinho, com pistas. Não nomeie o conceito, o instituto nem a conclusão que faltaram.
  Errado (entrega o ponto): "Escreva que o caso envolve o poder econômico, pois João cedeu em troca de dinheiro."
  Certo: "Releia a seção 1 e identifique qual das formas de poder descritas ali explica por que João cedeu — depois diga isso com o nome do conceito."
- demais_sugestoes: outras melhorias menores e curtas (0 a 3).
- pontos_fortes: só o que a resposta realmente fez bem, cada um com o trecho LITERAL da resposta e por que funciona. Se não houver, lista vazia.
- fora_do_material: afirmações da resposta que não estão no material (não é necessariamente erro; lembre que na prova o que conta é o que foi dado em aula). Lista vazia se não houver.
- estrutura_comentario: 1 ou 2 frases sobre a organização (identificar o problema → conceito do material → aplicação → conclusão), a partir da avaliação de estrutura.
- evolucao: SÓ se houver TENTATIVA ANTERIOR: para cada ponto que mudou, antes → depois, em poucas palavras. Senão, lista vazia.
- proximo_passo: UMA ação concreta para o próximo estudo deste tema.
- versao_melhorada: reescreva a resposta DO ESTUDANTE (mesma voz e estrutura, aproveitando o que estava certo) incorporando o que faltou, só com conteúdo do material. Tamanho de resposta de prova (1 a 3 parágrafos). Não copie a RESPOSTA DE REFERÊNCIA: ela é outra resposta; a versão melhorada é a DESTE estudante, melhorada.
- mensagem_final: 1 ou 2 frases, específica e honesta. Se a resposta está fraca, diga com clareza e gentileza; se está boa, diga o que a torna boa.

Escreva em português do Brasil. Devolva só o JSON."""


def _schema(modelo: type[BaseModel]) -> dict:
    return modelo.model_json_schema()


def _chamada(
    id_: str, rotulo: str, sistema: str, prompt: str, schema: type[BaseModel], temperatura: float, max_tokens: int
) -> dict:
    """`rotulo` é o que o ouvinte mostra como etapa enquanto roda esta
    chamada ("julgando ponto 2 de 5") -- ele não sabe o que é juiz nem
    redator, só repassa."""
    return {
        "id": id_,
        "rotulo": rotulo,
        "sistema": sistema,
        "prompt": prompt,
        "schema": _schema(schema),
        "temperatura": temperatura,
        "max_tokens": max_tokens,
    }


# --- 1. gerar --------------------------------------------------------------------


def job_de_geracao_ativo(session: Session, lesson_id: int) -> IaLocalJob | None:
    return session.scalar(
        select(IaLocalJob).where(
            IaLocalJob.lesson_id == lesson_id,
            IaLocalJob.tipo == "dissertativa_gerar",
            IaLocalJob.status.in_(["pending", "claimed"]),
        )
    )


def enfileirar_geracao(
    session: Session, lesson: Lesson, *, secao_numero: int | None = None, user_id: int | None = None
) -> IaLocalJob:
    """Idempotente sem seção escolhida: se já há uma geração pendente pra
    aula, devolve ela em vez de empilhar outra."""
    if secao_numero is None:
        ativo = job_de_geracao_ativo(session, lesson.id)
        if ativo is not None:
            return ativo

    todas = secoes_da_aula(session, lesson.id)
    alvo = escolher_secoes_alvo(session, lesson, secao_numero)
    existentes = session.scalars(
        select(DissertativaQuestion.enunciado)
        .where(DissertativaQuestion.lesson_id == lesson.id, DissertativaQuestion.fonte == "guia")
        .order_by(DissertativaQuestion.criado_em.desc())
        .limit(5)
    ).all()
    evitar = ""
    if existentes:
        evitar = "\n\nQUESTÕES QUE JÁ EXISTEM PARA ESTA AULA (não repita, crie outra):\n" + "\n".join(
            f"- {e}" for e in existentes
        )

    prompt = (
        f"GUIA DA AULA (visão geral):\n{visao_geral_do_guia(lesson, todas)}\n\n"
        f"SEÇÕES-FONTE (a questão sai daqui; use estes números em \"secao\"):\n{texto_das_secoes(alvo)}"
        f"{evitar}"
    )
    meta = {
        "secoes": [{"numero": n, "titulo": s.titulo} for n, s in alvo],
        "guia_gerado_em": lesson.guia_gerado_em.isoformat() if lesson.guia_gerado_em else None,
    }
    return fila_local.criar_job(
        session,
        tipo="dissertativa_gerar",
        chamadas=[_chamada("questao", "criando a questão", INSTRUCOES_GERAR, prompt, DissertativaQuestionGuiaOut, 0.7, 3000)],
        meta=meta,
        lesson_id=lesson.id,
        user_id=user_id,
    )


def _processar_geracao(session: Session, job: IaLocalJob, respostas: dict) -> None:
    meta = json.loads(job.payload_json)["meta"]
    try:
        saida = DissertativaQuestionGuiaOut.model_validate(respostas["questao"])
    except (KeyError, ValidationError) as exc:
        raise ProcessingError(f"a questão gerada não veio no formato esperado: {exc}") from exc

    lesson = session.get(Lesson, job.lesson_id)
    ai_call = _registrar_ai_call(session, job, respostas)
    guia_ref = meta.get("guia_gerado_em")
    question = _criar_questao(
        session, lesson, saida, meta["secoes"],
        origem=f"local:{job.modelo}" if job.motor != "claude_cli" else "claude",
        guia_ref=datetime.fromisoformat(guia_ref) if guia_ref else None,
        ai_call_id=ai_call.id,
    )
    job.question_id = question.id


def _criar_questao(
    session: Session, lesson: Lesson, saida: DissertativaQuestionGuiaOut, secoes: list[dict], *,
    origem: str, guia_ref: datetime | None, ai_call_id: int | None,
) -> DissertativaQuestion:
    """Grava uma questão gerada -- pela IA local ou pelo lote do Claude --
    com as mesmas regras: seção da rubrica tem de ser uma das seções-fonte,
    e o "o que a questão pede" não pode entregar um ponto da rubrica."""
    numeros_validos = [s["numero"] for s in secoes]
    rubrica = []
    for p in saida.rubrica:
        secao = p.secao if p.secao in numeros_validos else numeros_validos[0]
        rubrica.append({"ponto": p.ponto.strip(), "secao": secao, "pista": p.pista.strip()})

    criterio = saida.criterio_texto.strip()
    if any(entrega_o_ponto(criterio, p["ponto"]) for p in rubrica):
        # O "o que a questão pede" aparece ANTES de escrever: se ele já nomeia
        # o conteúdo de um ponto da rubrica, a questão fica respondida pela
        # própria instrução. Troca por uma instrução só de operações.
        criterio = CRITERIO_GENERICO

    question = DissertativaQuestion(
        subject_id=lesson.subject_id,
        lesson_id=lesson.id,
        fonte="guia",
        tipo=saida.tipo,
        enunciado=saida.enunciado.strip(),
        criterio_texto=criterio,
        rubrica_json=json.dumps(rubrica, ensure_ascii=False),
        secoes_json=json.dumps(secoes, ensure_ascii=False),
        guia_gerado_em_ref=guia_ref,
        resposta_modelo=saida.resposta_modelo.strip(),
        origem=origem,
        ai_call_id=ai_call_id,
    )
    session.add(question)
    session.flush()
    return question


# --- 1b. lote pelo Claude (/gerar-dissertativas, só quando o usuário pede) ----------

INSTRUCOES_LOTE = """Você vai criar {n} questões dissertativas para o banco de treino desta aula, a partir do GUIA abaixo (todas as seções). Cada questão segue exatamente as regras de uma questão individual:

""" + INSTRUCOES_GERAR.split("\n\n", 1)[1].rsplit("\n\nEscreva em português do Brasil.", 1)[0] + """

Regras do lote:
- Cubra seções DIFERENTES do guia, priorizando as que ainda não têm questão (lista no fim). Em "secoes", os números (1 a 3) das seções de onde a questão sai; a "secao" de cada ponto da rubrica tem de ser uma delas.
- Varie os tipos (caso, comparação, explicação, crítica).
- Não repita nem parafraseie as questões que já existem.

Escreva em português do Brasil. Devolva só o JSON, no schema do fim."""


def pacote_para_claude(session: Session, lesson: Lesson, n: int = 5) -> str:
    numeradas = _numerar(secoes_da_aula(session, lesson.id))
    if not numeradas:
        raise ProcessingError("esta aula ainda não tem guia estruturado — processe a aula antes")
    existentes = session.scalars(
        select(DissertativaQuestion).where(DissertativaQuestion.lesson_id == lesson.id, DissertativaQuestion.fonte == "guia")
    ).all()
    uso = {n_: 0 for n_ in numeradas}
    titulos = {s.titulo.strip().lower(): n_ for n_, s in numeradas.items()}
    for q in existentes:
        for ref in json.loads(q.secoes_json or "[]"):
            n_ = titulos.get(str(ref.get("titulo", "")).strip().lower())
            if n_ is not None:
                uso[n_] += 1
    secoes_texto = "\n\n".join(f"### Seção {n_}: {s.titulo}\n{s.corpo.strip()}" for n_, s in numeradas.items())
    ja = "\n".join(f"- {q.enunciado}" for q in existentes) or "(nenhuma)"
    cobertura = "\n".join(f"- seção {n_} ({numeradas[n_].titulo}): {uso[n_]} questão(ões)" for n_ in numeradas)
    schema = json.dumps(DissertativasLoteOut.model_json_schema(), ensure_ascii=False, indent=2)
    return (
        f"# Gerar {n} dissertativas: {lesson.guia_titulo or lesson.titulo} (aula {lesson.id})\n\n"
        f"{INSTRUCOES_LOTE.format(n=n)}\n\n"
        f"GUIA DA AULA (visão geral):\n{visao_geral_do_guia(lesson, list(numeradas.values()))}\n\n"
        f"SEÇÕES DO GUIA:\n{secoes_texto}\n\n"
        f"QUESTÕES QUE JÁ EXISTEM (não repita):\n{ja}\n\n"
        f"COBERTURA ATUAL POR SEÇÃO:\n{cobertura}\n\n"
        f"SCHEMA DE SAÍDA:\n{schema}\n"
    )


def importar_lote(session: Session, lesson: Lesson, texto: str) -> list[DissertativaQuestion]:
    """Recebe a resposta do Claude (JSON puro ou cercado de conversa) e grava
    as questões com `origem="claude"`. Tudo ou nada: se uma questão não
    valida, nenhuma entra (o erro diz qual)."""
    from .parse import parse_pasted_response

    try:
        lote = DissertativasLoteOut.model_validate(parse_pasted_response(texto))
    except (ValueError, ValidationError) as exc:
        raise ProcessingError(f"o lote não veio no formato esperado: {exc}") from exc
    numeradas = _numerar(secoes_da_aula(session, lesson.id))
    if not numeradas:
        raise ProcessingError("esta aula ainda não tem guia estruturado — processe a aula antes")

    ai_call = AiCall(
        lesson_id=lesson.id, tipo_acao="dissertativa_gerar", via="claude_code", modelo="claude",
        custo_usd=0.0, raw_response_json=lote.model_dump_json(),
    )
    session.add(ai_call)
    session.flush()
    criadas = []
    for i, q in enumerate(lote.questoes, start=1):
        invalidas = [n_ for n_ in q.secoes if n_ not in numeradas]
        if invalidas:
            session.rollback()
            raise ProcessingError(f"questão {i}: seção(ões) {invalidas} não existem no guia (vai de 1 a {len(numeradas)})")
        secoes = [{"numero": n_, "titulo": numeradas[n_].titulo} for n_ in q.secoes]
        criadas.append(_criar_questao(
            session, lesson, q, secoes, origem="claude", guia_ref=lesson.guia_gerado_em, ai_call_id=ai_call.id,
        ))
    session.commit()
    return criadas


# --- 2. julgar -------------------------------------------------------------------


def _bloco_calibracao(session: Session, user_id: int | None, tipo: str | None) -> str:
    """Até 3 discordâncias recentes da pessoa (preferindo o mesmo tipo de
    questão) viram referência de rigor no prompt do juiz -- a mão humana
    corrigindo o avaliador, que a pesquisa aponta como o que mais melhora
    feedback de IA."""
    if user_id is None:
        return ""
    linhas = session.execute(
        select(DissertativaDiscordancia, DissertativaAttempt, DissertativaQuestion)
        .join(DissertativaAttempt, DissertativaAttempt.id == DissertativaDiscordancia.attempt_id)
        .join(DissertativaQuestion, DissertativaQuestion.id == DissertativaAttempt.question_id)
        .where(DissertativaDiscordancia.user_id == user_id)
        .order_by((DissertativaQuestion.tipo == tipo).desc(), DissertativaDiscordancia.criado_em.desc())
        .limit(MAX_EXEMPLOS_CALIBRACAO)
    ).all()
    if not linhas:
        return ""
    exemplos = []
    for disc, attempt, question in linhas:
        rubrica = normalizar_rubrica(question.rubrica_json)
        ponto = rubrica[disc.ponto_idx]["ponto"] if 0 <= disc.ponto_idx < len(rubrica) else "?"
        trecho = ""
        vereditos = json.loads(attempt.vereditos_json or "{}").get("pontos", [])
        if 0 <= disc.ponto_idx < len(vereditos):
            trecho = vereditos[disc.ponto_idx].get("trecho", "")
        linha = f"- Ponto «{ponto}» | a resposta dizia: «{trecho or '(nada)'}» | o avaliador disse \"{disc.veredito_modelo}\" | o correto era \"{disc.veredito_usuario}\""
        if disc.comentario:
            linha += f" ({disc.comentario})"
        exemplos.append(linha)
    return (
        "\n\nCorreções anteriores em que o estudante discordou do avaliador — use como referência de rigor:\n"
        + "\n".join(exemplos)
    )


def _bloco_referencia(question: DissertativaQuestion) -> str:
    """A resposta certa gerada junto com a questão, como âncora da correção
    (evita o modelo local fugir do assunto). Igual em todas as chamadas do
    julgamento -- fica no prefixo compartilhado, sem custo de cache."""
    if not question.resposta_modelo:
        return ""
    return f"RESPOSTA DE REFERÊNCIA (exemplo de resposta completa; o material prevalece):\n{question.resposta_modelo}\n\n"


def _prefixo_avaliacao(session: Session, question: DissertativaQuestion, resposta: str) -> str:
    fonte = texto_das_secoes(secoes_fonte(session, question))
    return (
        f"MATERIAL (seções do guia da aula):\n{fonte}\n\n"
        f"ENUNCIADO:\n{question.enunciado}\n\n"
        f"{_bloco_referencia(question)}"
        f"RESPOSTA DO ESTUDANTE:\n{resposta}\n\n"
    )


def enfileirar_julgamento(
    session: Session, attempt: DissertativaAttempt, *, indices: list[int] | None = None, rodada: int = 0
) -> IaLocalJob:
    question = attempt.question
    rubrica = normalizar_rubrica(question.rubrica_json)
    sistema = INSTRUCOES_AVALIADOR + _bloco_calibracao(session, attempt.user_id, question.tipo)
    prefixo = _prefixo_avaliacao(session, question, attempt.resposta_texto)

    alvo = list(range(len(rubrica))) if indices is None else indices
    verbo = "julgando" if rodada == 0 else "conferindo de novo"
    chamadas = [
        _chamada(
            f"ponto-{i}", f"{verbo} o ponto {i + 1} de {len(rubrica)}", sistema,
            prefixo + TAREFA_PONTO.format(ponto=rubrica[i]["ponto"]), VereditoPontoOut, 0.0, 350,
        )
        for i in alvo
    ]
    if indices is None:
        chamadas.append(
            _chamada("estrutura", "avaliando a estrutura", sistema, prefixo + TAREFA_ESTRUTURA, EstruturaOut, 0.0, 600)
        )

    attempt.status = "julgando"
    attempt.erro = None
    return fila_local.criar_job(
        session,
        tipo="dissertativa_julgar",
        chamadas=chamadas,
        meta={"rodada": rodada, "indices": alvo, "total_pontos": len(rubrica)},
        lesson_id=question.lesson_id,
        question_id=question.id,
        attempt_id=attempt.id,
        user_id=attempt.user_id,
    )


def _processar_julgamento(session: Session, job: IaLocalJob, respostas: dict) -> None:
    meta = json.loads(job.payload_json)["meta"]
    attempt = session.get(DissertativaAttempt, job.attempt_id)
    rubrica = normalizar_rubrica(attempt.question.rubrica_json)
    atual = json.loads(attempt.vereditos_json or "{}")
    pontos = {p["idx"]: p for p in atual.get("pontos", [])}

    for i in meta["indices"]:
        try:
            v = VereditoPontoOut.model_validate(respostas[f"ponto-{i}"])
        except (KeyError, ValidationError) as exc:
            raise ProcessingError(f"o veredito do ponto {i + 1} não veio no formato esperado: {exc}") from exc
        trecho = v.trecho_da_resposta.strip()
        if v.veredito == "ausente":
            citacao_ok = True  # "ausente" não depende de citação
        else:
            citacao_ok = trecho_existe(trecho, attempt.resposta_texto)
        pontos[i] = {
            "idx": i,
            "ponto": rubrica[i]["ponto"],
            "secao": rubrica[i]["secao"],
            "veredito": v.veredito,
            "trecho": trecho,
            "o_que_falta": v.o_que_falta.strip(),
            "citacao_ok": citacao_ok,
            "rodada": meta["rodada"],
        }

    if "estrutura" in respostas:
        try:
            e = EstruturaOut.model_validate(respostas["estrutura"])
        except ValidationError as exc:
            raise ProcessingError(f"a avaliação de estrutura não veio no formato esperado: {exc}") from exc
        estrutura = {}
        for campo in ROTULOS_ESTRUTURA:
            criterio = getattr(e, campo)
            trecho = criterio.trecho_da_resposta.strip()
            # "Atende" sem trecho que exista na resposta não vale.
            ok = criterio.atende and trecho_existe(trecho, attempt.resposta_texto)
            estrutura[campo] = {"atende": ok, "trecho": trecho if ok else ""}
        atual["estrutura"] = estrutura

    _registrar_ai_call(session, job, respostas)
    sem_citacao = [i for i, p in pontos.items() if not p["citacao_ok"]]

    if sem_citacao and meta["rodada"] < MAX_RODADAS_REJULGAMENTO:
        atual["pontos"] = [pontos[i] for i in sorted(pontos)]
        attempt.vereditos_json = json.dumps(atual, ensure_ascii=False)
        session.flush()
        enfileirar_julgamento(session, attempt, indices=sem_citacao, rodada=meta["rodada"] + 1)
        return

    for i in sem_citacao:
        # Segunda vez citando algo que não está na resposta: não dá pra
        # confiar no veredito. Conta como não coberto, e a tela mostra
        # "não verificado" com o botão de discordar à mão.
        pontos[i]["veredito"] = "nao_verificado"
    atual["pontos"] = [pontos[i] for i in sorted(pontos)]
    attempt.vereditos_json = json.dumps(atual, ensure_ascii=False)
    session.flush()
    enfileirar_redacao(session, attempt)


def cobertura(vereditos_json: str | None) -> tuple[float, int, float]:
    """(fração 0..1, total de pontos, pontos somados) -- parcial vale meio."""
    pontos = json.loads(vereditos_json or "{}").get("pontos", [])
    if not pontos:
        return 0.0, 0, 0.0
    soma = sum(VALOR_VEREDITO.get(p["veredito"], 0.0) for p in pontos)
    return soma / len(pontos), len(pontos), soma


# --- 3. redigir ------------------------------------------------------------------


def sugestoes_do_feedback(feedback: dict) -> list[str]:
    """Lista plana (prioridades, depois demais) -- os índices que a pessoa
    marca em "vou aplicar" são posições nesta lista."""
    return [p["sugestao"] for p in feedback.get("prioridades", [])] + list(feedback.get("demais_sugestoes", []))


def _texto_avaliacao(vereditos: dict) -> str:
    linhas = []
    for p in vereditos.get("pontos", []):
        veredito = "não verificado (o avaliador citou algo que não está na resposta)" if p["veredito"] == "nao_verificado" else p["veredito"]
        linha = f"{p['idx']}. «{p['ponto']}» (seção {p['secao']}) → {veredito}"
        if p.get("trecho") and p["veredito"] != "nao_verificado":
            linha += f" | trecho: «{p['trecho']}»"
        if p.get("o_que_falta"):
            linha += f" | falta: {p['o_que_falta']}"
        linhas.append(linha)
    estrutura = vereditos.get("estrutura") or {}
    if estrutura:
        linhas.append("\nESTRUTURA:")
        for campo, rotulo in ROTULOS_ESTRUTURA.items():
            c = estrutura.get(campo, {})
            linhas.append(f"- {rotulo}: {'sim' if c.get('atende') else 'não'}")
    return "\n".join(linhas)


def enfileirar_redacao(session: Session, attempt: DissertativaAttempt) -> IaLocalJob:
    question = attempt.question
    vereditos = json.loads(attempt.vereditos_json or "{}")
    frac, total, soma = cobertura(attempt.vereditos_json)
    confianca = DISSERTATIVA_CONFIANCAS.get(attempt.confianca or 0, "não informada")

    partes = [
        f"MATERIAL (seções do guia da aula):\n{texto_das_secoes(secoes_fonte(session, question))}",
        f"ENUNCIADO:\n{question.enunciado}",
        *([_bloco_referencia(question).strip()] if question.resposta_modelo else []),
        f"RESPOSTA DO ESTUDANTE:\n{attempt.resposta_texto}",
        f"AVALIAÇÃO (já feita; cobriu {soma:g} de {total} pontos):\n{_texto_avaliacao(vereditos)}",
        f"CONFIANÇA QUE O ESTUDANTE DECLAROU ANTES DE ENVIAR: {confianca}",
    ]
    if attempt.autoavaliacao_texto:
        partes.append(f"O QUE O ESTUDANTE ACHAVA QUE TINHA FALTADO: {attempt.autoavaliacao_texto}")

    anterior = attempt.tentativa_anterior
    if anterior is not None and anterior.feedback_json:
        feedback_anterior = json.loads(anterior.feedback_json)
        sugestoes = sugestoes_do_feedback(feedback_anterior)
        escolhidas = [sugestoes[i] for i in json.loads(attempt.sugestoes_escolhidas_json or "[]") if 0 <= i < len(sugestoes)]
        bloco = (
            "TENTATIVA ANTERIOR (compare em `evolucao`):\n"
            f"Resposta anterior:\n{anterior.resposta_texto}\n\n"
            f"Avaliação anterior:\n{_texto_avaliacao(json.loads(anterior.vereditos_json or '{}'))}"
        )
        if escolhidas:
            bloco += "\n\nSugestões que o estudante escolheu aplicar nesta reescrita:\n" + "\n".join(f"- {s}" for s in escolhidas)
        partes.append(bloco)

    attempt.status = "redigindo"
    return fila_local.criar_job(
        session,
        tipo="dissertativa_redigir",
        chamadas=[_chamada("feedback", "escrevendo o feedback", INSTRUCOES_REDIGIR, "\n\n".join(partes), DissertativaFeedbackOut, 0.4, 2500)],
        meta={"cobertura": frac},
        lesson_id=question.lesson_id,
        question_id=question.id,
        attempt_id=attempt.id,
        user_id=attempt.user_id,
        etapa="na fila (escrever o feedback)",
    )


def _processar_redacao(session: Session, job: IaLocalJob, respostas: dict) -> None:
    from ..study.dissertativa_scheduler import registrar_resultado

    attempt = session.get(DissertativaAttempt, job.attempt_id)
    try:
        saida = DissertativaFeedbackOut.model_validate(respostas["feedback"])
    except (KeyError, ValidationError) as exc:
        raise ProcessingError(f"o feedback não veio no formato esperado: {exc}") from exc

    vereditos = json.loads(attempt.vereditos_json or "{}")
    total = len(vereditos.get("pontos", []))
    numeros = {s["numero"] for s in json.loads(attempt.question.secoes_json or "[]")}
    feedback = saida.model_dump()
    # Nada de elogio sem trecho que exista na resposta (anti-bajulação).
    feedback["pontos_fortes"] = [
        p for p in feedback["pontos_fortes"] if trecho_existe(p["trecho"], attempt.resposta_texto)
    ]
    feedback["prioridades"] = [
        {**p, "ponto_idx": p["ponto_idx"] if -1 <= p["ponto_idx"] < total else -1,
         "secao": p["secao"] if p["secao"] in numeros else None}
        for p in feedback["prioridades"]
    ]
    _marcar_vazamentos(feedback, vereditos.get("pontos", []))
    if attempt.tentativa_anterior_id is None:
        feedback["evolucao"] = []

    frac, _, _ = cobertura(attempt.vereditos_json)
    pontos = vereditos.get("pontos", [])
    attempt.feedback_json = json.dumps(feedback, ensure_ascii=False)
    attempt.pontos_cobertos_json = json.dumps([p["ponto"] for p in pontos if p["veredito"] == "coberto"], ensure_ascii=False)
    attempt.pontos_faltantes_json = json.dumps([p["ponto"] for p in pontos if p["veredito"] != "coberto"], ensure_ascii=False)
    attempt.comentario = feedback["mensagem_final"]
    attempt.status = "avaliado"
    attempt.avaliado_em = datetime.now(timezone.utc)
    attempt.motor = job.motor
    attempt.modelo = job.modelo
    attempt.segundos_total = _segundos_da_correcao(session, attempt.id)
    ai_call = _registrar_ai_call(session, job, respostas)
    attempt.ai_call_id = ai_call.id

    # Só a v1 de um ciclo move o espaçamento: reescrever logo depois de ler
    # o feedback é aplicar o que acabou de ver, não lembrar.
    if attempt.tentativa_anterior_id is None and attempt.user_id is not None:
        registrar_resultado(session, attempt.user_id, attempt.question_id, frac)


def _marcar_vazamentos(feedback: dict, pontos: list[dict]) -> None:
    """Grava em `feedback["vazamentos"]` quais textos visíveis repetem o
    conteúdo de um ponto NÃO coberto: {"campo" | "prioridades.i" |
    "demais_sugestoes.i": idx_do_ponto}. A tela esconde esses textos até o
    ponto ser revelado (nível 3 das pistas). O prompt já pede pra não
    entregar, mas o modelo local atropela com frequência -- e a revelação
    gradual é justamente o que faz a pessoa aprender em vez de só ler."""
    nao_cobertos = [p for p in pontos if p["veredito"] != "coberto"]

    def ponto_vazado(texto: str | None) -> int | None:
        if not texto:
            return None
        return next((q["idx"] for q in nao_cobertos if entrega_o_ponto(texto, q["ponto"])), None)

    vazamentos: dict[str, int] = {}
    for campo in CAMPOS_VISIVEIS:
        idx = ponto_vazado(feedback.get(campo))
        if idx is not None:
            vazamentos[campo] = idx
    for i, pr in enumerate(feedback.get("prioridades", [])):
        idx = ponto_vazado(pr.get("sugestao"))
        if idx is not None:
            vazamentos[f"prioridades.{i}"] = idx
    for i, texto in enumerate(feedback.get("demais_sugestoes", [])):
        idx = ponto_vazado(texto)
        if idx is not None:
            vazamentos[f"demais_sugestoes.{i}"] = idx
    feedback["vazamentos"] = vazamentos


def _segundos_da_correcao(session: Session, attempt_id: int) -> float | None:
    jobs = session.scalars(select(IaLocalJob).where(IaLocalJob.attempt_id == attempt_id)).all()
    valores = [j.segundos_total for j in jobs if j.segundos_total]
    return round(sum(valores), 1) if valores else None


# --- despacho do resultado -------------------------------------------------------


def _registrar_ai_call(session: Session, job: IaLocalJob, respostas: dict) -> AiCall:
    ai_call = AiCall(
        lesson_id=job.lesson_id,
        tipo_acao=job.tipo,
        via=job.motor or "local",
        modelo=job.modelo or "local",
        custo_usd=0.0,
        raw_response_json=json.dumps(respostas, ensure_ascii=False),
    )
    session.add(ai_call)
    session.flush()
    return ai_call


_PROCESSADORES = {
    "dissertativa_gerar": _processar_geracao,
    "dissertativa_julgar": _processar_julgamento,
    "dissertativa_redigir": _processar_redacao,
}


def processar_resultado(session: Session, job: IaLocalJob, respostas: dict) -> None:
    """Chamado pela rota de resultado já com o claim conferido. Resposta
    inválida vira job `failed` (e a tentativa, "erro") com a mensagem, em
    vez de estourar -- o ouvinte já tentou reparar o JSON uma vez."""
    try:
        _PROCESSADORES[job.tipo](session, job, respostas)
    except ProcessingError as exc:
        session.rollback()
        job = session.get(IaLocalJob, job.id)
        marcar_falha(session, job, str(exc))
        return
    job.status = "done"
    job.etapa = "pronto"
    session.commit()


def marcar_falha(session: Session, job: IaLocalJob, erro: str) -> None:
    job.status = "failed"
    job.erro = erro[:2000]
    job.etapa = "falhou"
    if job.attempt_id is not None:
        attempt = session.get(DissertativaAttempt, job.attempt_id)
        if attempt is not None and attempt.status in ("julgando", "redigindo"):
            attempt.status = "erro"
            attempt.erro = erro[:2000]
    session.commit()


def tentar_de_novo(session: Session, attempt: DissertativaAttempt) -> IaLocalJob:
    """Recomeça a correção de uma tentativa que falhou: se os vereditos já
    estão todos lá, só a redação; senão, o julgamento inteiro."""
    vereditos = json.loads(attempt.vereditos_json or "{}")
    total = len(normalizar_rubrica(attempt.question.rubrica_json))
    if len(vereditos.get("pontos", [])) == total and "estrutura" in vereditos:
        job = enfileirar_redacao(session, attempt)
    else:
        attempt.vereditos_json = None
        job = enfileirar_julgamento(session, attempt)
    session.commit()
    return job
