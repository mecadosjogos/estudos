""""Dominar o guia" (PLANO.md): passada de IA independente e sob
demanda que gera uma bateria de exercícios de memorização a partir do
GUIA de uma aula (`Lesson.guia_md`), não da transcrição -- única exceção
deliberada à regra "fonte = transcrição literal recortada" do resto do
app. Essa regra existe para evitar distorção silenciosa de texto
jurídico citável (poderá×deverá); aqui não se aplica, porque o guia já é
o material que o usuário revisou e aceitou como referência de estudo --
o alvo é internalizar o que já está ali, erros inclusos, não extrair uma
alegação nova para citar em prova.

Mesmo padrão de `ai/dissertativa.py`: par automático (API paga, se
configurada) / ponte manual (colar resposta), ingestão via `reconcile()`
genérico. Sem intervalo de origem (o guia não carrega start_s/end_s por
seção) -- deriv_key hasheia o texto normalizado da seção + pergunta."""

import json

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AiCall, GuiaExercicio, Lesson
from .budget import check_budget_or_raise
from .client import AIClient
from .deriv_key import compute_deriv_key
from .parse import parse_pasted_response
from .pipeline import ProcessingError
from .pricing import estimate_cost_usd
from .reconcile import reconcile
from .schemas import GUIA_EXERCICIO_TIPOS, GuiaExerciciosOutput

INSTRUCTIONS = f"""Você gera uma bateria de exercícios de memorização a
partir do GUIA DE AULA abaixo -- o material que o usuário já revisou e
aceitou como referência de estudo desta aula. Trabalhe SÓ com o que está
neste guia: nunca acrescente conhecimento jurídico externo, nunca
corrija o que o guia diz mesmo que pareça impreciso -- o objetivo é
memorizar este guia específico, não substituí-lo.

Gere exercícios cobrindo TODOS os conceitos centrais do guia (não só o
primeiro parágrafo), distribuídos pelos tipos abaixo -- não precisa ser
uniforme, use o tipo que faz sentido para cada trecho, mas cubra vários
tipos, não só um:

- **definicao**: pergunta direta de definição/conceito. `gabarito`:
  {{"resposta": "..."}}.
- **cloze**: uma frase-chave do guia com um termo ou trecho central
  substituído por "______". `gabarito`: {{"texto_com_lacunas": "...",
  "respostas": ["...", ...]}}.
- **lista_ordenada**: quando o guia apresenta uma enumeração ou sequência
  (fases, requisitos, excludentes, etc.), peça para reconstruir a ordem.
  `gabarito`: {{"itens_em_ordem": ["...", ...]}}.
- **hierarquia**: baseado num trecho da árvore de conhecimento do guia,
  peça para reconstruir a relação entre um conceito e seus
  subconceitos. `gabarito`: {{"arvore_alvo": {{"rotulo": "...", "filhos":
  [{{"rotulo": "...", "filhos": []}}]}}}}.
- **discriminacao**: quando o guia contrasta dois conceitos próximos,
  pergunte a diferença entre eles. `gabarito`: {{"termo_a": "...",
  "termo_b": "...", "eixo": "..."}}.
- **recordacao_livre**: peça para escrever de memória tudo que lembra de
  uma seção inteira do guia. `gabarito`: {{"pontos_esperados": ["...",
  ...]}} -- os pontos que uma recordação completa deveria cobrir.
- **aplicacao_caso**: quando o guia trouxer um trecho marcado "Exemplo:"
  ou um caso prático, monte uma pergunta de "qual conceito se aplica
  aqui". `gabarito`: {{"caso": "...", "conceito_correto": "..."}}.

`secao_titulo` deve ser o título da seção do guia de onde o exercício
veio (use o texto exato do cabeçalho "## ...").

Devolva JSON válido no formato do schema abaixo -- nada além do JSON."""


def build_context_for_lesson(lesson: Lesson) -> str:
    if not lesson.guia_md:
        raise ProcessingError("aula sem guia gerado — processe a aula (fase 6) antes de dominar o guia")
    return lesson.guia_md


def build_prompt(lesson: Lesson) -> str:
    schema_json = json.dumps(GuiaExerciciosOutput.model_json_schema(), ensure_ascii=False, indent=2)
    guia_md = build_context_for_lesson(lesson)
    return f"""{INSTRUCTIONS}

GUIA DE AULA: {lesson.titulo}

{guia_md}

SCHEMA DE SAÍDA:
{schema_json}
"""


def package_as_markdown(lesson: Lesson, prompt: str) -> str:
    return f"# Dominar o guia — exercícios de memorização: {lesson.titulo}\n\n{prompt}"


def generate_exercicios_automatically(session: Session, lesson: Lesson, ai_client: AIClient) -> AiCall:
    check_budget_or_raise(session)
    prompt = build_prompt(lesson)
    response = ai_client.structured_call(prompt=prompt, schema=GuiaExerciciosOutput.model_json_schema(), cache=False)
    from .. import config

    return _ingest_exercicios(
        session, lesson, parsed_dict=json.loads(response.content), model=config.AI_MODEL, via="automatico",
        input_tokens=response.input_tokens, output_tokens=response.output_tokens,
        cache_read_input_tokens=response.cache_read_input_tokens,
    )


def ingest_exercicios_manual_response(session: Session, lesson: Lesson, pasted_text: str) -> AiCall:
    parsed_dict = parse_pasted_response(pasted_text)
    return _ingest_exercicios(
        session, lesson, parsed_dict=parsed_dict, model="manual", via="manual",
        input_tokens=0, output_tokens=0, cache_read_input_tokens=0,
    )


def _ingest_exercicios(
    session: Session, lesson: Lesson, *, parsed_dict: dict, model: str, via: str,
    input_tokens: int, output_tokens: int, cache_read_input_tokens: int,
) -> AiCall:
    try:
        output = GuiaExerciciosOutput.model_validate(parsed_dict)
    except ValidationError as exc:
        raise ProcessingError(f"resposta não bate com o formato esperado: {exc}") from exc

    occurrence_counts: dict[tuple, int] = {}
    items = []
    for ex in output.exercicios:
        if ex.tipo not in GUIA_EXERCICIO_TIPOS:
            continue
        source_text = f"{ex.secao_titulo or ''}|{ex.pergunta}"
        occurrence = occurrence_counts.get(ex.tipo, 0)
        occurrence_counts[ex.tipo] = occurrence + 1
        tipo_com_ocorrencia = ex.tipo if occurrence == 0 else f"{ex.tipo}-{occurrence}"
        key = compute_deriv_key(tipo_com_ocorrencia, 0.0, 0.0, source_text)
        items.append(
            (
                key,
                {
                    "tipo": ex.tipo,
                    "secao_titulo": ex.secao_titulo,
                    "pergunta": ex.pergunta,
                    "gabarito_json": json.dumps(ex.gabarito, ensure_ascii=False),
                },
            )
        )

    reconcile(session, GuiaExercicio, lesson.id, items, has_versao_nova=True)

    # flush antes de consultar: a sessão é autoflush=False (db.py) e
    # reconcile() só dá session.add() nas linhas novas, sem flush -- sem
    # isso, o select() logo abaixo não veria as linhas recém-inseridas
    # (ainda não gravadas no banco) e a auto-aprovação não pegaria nada na
    # primeira leva (bug real, visto no smoke test: só "curava" na segunda
    # chamada, quando as linhas já estavam de fato commitadas).
    session.flush()

    # Auto-aprova, diferente de card/anúncio/assunto (que exigem revisão
    # humana): o guia não é fonte de verdade jurídica extraída da fala do
    # professor, é o material que o usuário já revisou e aceitou -- um
    # exercício sobre ele não alega um fato novo a conferir, só reformula
    # o que já está aprovado. Decisão do usuário. Só pega quem ainda está
    # "pendente" (recém-inserido pelo reconcile acima); nunca reativa algo
    # que o usuário descartou manualmente (`status="descartado"`).
    for row in session.scalars(
        select(GuiaExercicio).where(GuiaExercicio.lesson_id == lesson.id, GuiaExercicio.status == "pendente")
    ):
        row.status = "aceito"

    cost = (
        estimate_cost_usd(model, input_tokens, output_tokens, cache_read_input_tokens)
        if via == "automatico"
        else 0.0
    )
    ai_call = AiCall(
        lesson_id=lesson.id, tipo_acao="guia_exercicios_gerar", via=via, modelo=model,
        input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=cache_read_input_tokens,
        custo_usd=cost, raw_response_json=json.dumps(parsed_dict, ensure_ascii=False),
    )
    session.add(ai_call)
    session.commit()
    return ai_call
