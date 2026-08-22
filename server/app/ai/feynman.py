"""Feynman por voz (PLANO.md, fase 13): você explica um termo em voz alta,
o sistema compara contra a(s) definição(ões) do professor e aponta o que
faltou -- "produção, não reconhecimento". A transcrição (ASR curto,
`app/media/asr.py`) nunca passa pela ponte manual, é sempre automática --
não é chamada paga, é `faster-whisper` rodando na CPU da VPS. Só a
AVALIAÇÃO (o julgamento sobre o que faltou) segue a ponte manual de
sempre, porque essa parte sim é uma chamada de IA de verdade."""

import json
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AiCall, Definition, FeynmanAttempt, Term
from .budget import check_budget_or_raise
from .client import AIClient
from .parse import parse_pasted_response
from .pipeline import ProcessingError
from .pricing import estimate_cost_usd
from .schemas import FeynmanFeedbackOut

INSTRUCTIONS = """Você avalia uma explicação falada em voz alta sobre um termo
jurídico, comparando com a definição do professor -- método Feynman: a
pessoa tenta explicar de memória, e você aponta o que faltou.

Devolva:
- pontos_cobertos: os elementos da definição que a explicação cobriu
  corretamente, em frases curtas.
- pontos_faltantes: elementos que a definição do professor tem mas a
  explicação não cobriu ou cobriu errado. Vazio é um resultado válido --
  não force encontrar falha se a explicação já cobriu tudo.
- divergencias_terminologicas: quando a pessoa usou um termo diferente do
  vocabulário do professor pra mesma ideia (ex.: "você disse 'culpa' onde
  o professor usa 'culpabilidade' -- são coisas distintas nesta matéria"),
  uma frase por divergência.
- comentario_geral: um comentário curto, direto, tom de professor
  corrigindo de viva voz -- não robótico, não uma lista.

Avalie o SENTIDO, não a forma -- não penalize por não usar as mesmas
palavras do professor se o conceito está certo. Se houver mais de uma
definição do professor (matérias diferentes), avalie contra cada uma e
diga quando a explicação bate melhor com uma do que com outra. Nunca
invente o que a pessoa não disse.

Devolva JSON válido no formato do schema abaixo -- nada além do JSON."""


def active_definitions_for_term(session: Session, term_id: int) -> list[Definition]:
    return session.scalars(
        select(Definition).where(Definition.term_id == term_id, Definition.status == "ativo")
    ).all()


def build_feynman_prompt(term: Term, definitions: list[Definition], transcript_text: str) -> str:
    schema_json = json.dumps(FeynmanFeedbackOut.model_json_schema(), ensure_ascii=False, indent=2)
    definicoes_texto = "\n\n".join(
        f"[{d.subject.sigla if d.subject else 'matéria não informada'}] {d.definicao_md}"
        + (f'\nCitação literal do professor: "{d.citacao_literal}"' if d.citacao_literal else "")
        for d in definitions
    ) or "(nenhuma definição ativa registrada pra este termo)"

    return f"""{INSTRUCTIONS}

TERMO: {term.rotulo}

DEFINIÇÃO(ÕES) DO PROFESSOR:
{definicoes_texto}

SUA EXPLICAÇÃO (transcrita de um áudio curto, pode ter ruído de fala):
{transcript_text}

SCHEMA DE SAÍDA:
{schema_json}
"""


def package_as_markdown(term: Term, prompt: str) -> str:
    header = f"# Avaliar Feynman: {term.rotulo}\n\n"
    return header + prompt


def evaluate_feynman_automatically(session: Session, attempt: FeynmanAttempt, ai_client: AIClient) -> AiCall:
    check_budget_or_raise(session)

    term = session.get(Term, attempt.term_id)
    prompt = build_feynman_prompt(term, active_definitions_for_term(session, term.id), attempt.transcript_text or "")
    response = ai_client.structured_call(
        prompt=prompt, schema=FeynmanFeedbackOut.model_json_schema(), cache=False
    )

    from .. import config

    return _ingest(
        session,
        attempt,
        parsed_dict=json.loads(response.content),
        model=config.AI_MODEL,
        via="automatico",
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cache_read_input_tokens=response.cache_read_input_tokens,
    )


def ingest_feynman_manual_response(session: Session, attempt: FeynmanAttempt, pasted_text: str) -> AiCall:
    parsed_dict = parse_pasted_response(pasted_text)
    return _ingest(
        session, attempt, parsed_dict=parsed_dict, model="manual", via="manual",
        input_tokens=0, output_tokens=0, cache_read_input_tokens=0,
    )


def _ingest(
    session: Session,
    attempt: FeynmanAttempt,
    *,
    parsed_dict: dict,
    model: str,
    via: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int,
) -> AiCall:
    try:
        output = FeynmanFeedbackOut.model_validate(parsed_dict)
    except ValidationError as exc:
        raise ProcessingError(f"resposta não bate com o formato esperado: {exc}") from exc

    attempt.pontos_cobertos_json = json.dumps(output.pontos_cobertos, ensure_ascii=False)
    attempt.pontos_faltantes_json = json.dumps(output.pontos_faltantes, ensure_ascii=False)
    attempt.divergencias_json = json.dumps(output.divergencias_terminologicas, ensure_ascii=False)
    attempt.comentario_geral = output.comentario_geral
    attempt.status = "avaliado"
    attempt.avaliado_em = datetime.now(timezone.utc)

    cost = (
        estimate_cost_usd(model, input_tokens, output_tokens, cache_read_input_tokens)
        if via == "automatico"
        else 0.0
    )
    ai_call = AiCall(
        lesson_id=None,
        tipo_acao="feynman",
        via=via,
        modelo=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        custo_usd=cost,
        raw_response_json=json.dumps(parsed_dict, ensure_ascii=False),
    )
    session.add(ai_call)
    session.flush()
    attempt.ai_call_id = ai_call.id
    session.commit()
    return ai_call
