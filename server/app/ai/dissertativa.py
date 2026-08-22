"""Dissertativa avaliada (PLANO.md, fase 13): "prova de Direito é
escrita" -- a IA gera uma questão no estilo do professor com rubrica, e
corrige sua resposta contra ela. Duas passadas distintas (gerar questão,
corrigir resposta), cada uma com seu par automático/ponte manual, iguais
em espírito a `ai/pipeline.py`: sempre a partir do recorte literal da
transcrição (nunca da aula editada), nunca inventando um ponto que a aula
não cobriu."""

import json
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..models import AiCall, DissertativaAttempt, DissertativaQuestion, Lesson
from .budget import check_budget_or_raise
from .client import AIClient
from .parse import parse_pasted_response
from .pipeline import ProcessingError
from .pricing import estimate_cost_usd
from .schemas import DissertativaCorrectionOut, DissertativaQuestionOut

INSTRUCTIONS_GENERATE = """Você escreve uma questão dissertativa de Direito
no estilo de prova do professor, a partir do conteúdo abaixo -- transcrição
literal de aula(s), não resumo.

A questão deve:
- Cobrar RACIOCÍNIO, não decoreba -- nunca "o que é X", sempre um caso
  concreto, uma comparação ou uma aplicação que exige usar o conceito.
- Usar o vocabulário e, se fizer sentido, os exemplos que o PRÓPRIO
  professor usou nesta aula -- não doutrina genérica de fora da aula.
- Ter um enunciado de 2 a 4 frases, no padrão de uma questão dissertativa
  de prova de Direito.

Junto, escreva a RUBRICA: uma lista dos pontos que uma resposta completa
precisa cobrir, extraídos do que o professor efetivamente disse na aula.
Nunca invente um ponto que a aula não cobriu.

Devolva JSON válido no formato do schema abaixo -- nada além do JSON."""

INSTRUCTIONS_CORRECT = """Você corrige uma resposta dissertativa de Direito
contra a rubrica abaixo, extraída da aula do professor.

Aponte:
- pontos_cobertos: itens da rubrica que a resposta atendeu.
- pontos_faltantes: itens da rubrica que faltaram ou vieram errados.
- comentario: um parágrafo curto, tom de professor corrigindo prova,
  direto sobre o que melhorar -- não uma lista repetindo os pontos acima.

Avalie o mérito jurídico do conteúdo, não a forma (erro de português não é
o foco). Nunca invente um ponto que não está na rubrica.

Devolva JSON válido no formato do schema abaixo -- nada além do JSON."""


def build_context_for_lesson(lesson: Lesson) -> str:
    if lesson.transcript is None:
        raise ProcessingError("aula sem transcrição — transcreva antes de gerar uma questão")
    return f"--- AULA: {lesson.titulo} ({lesson.data.isoformat()}) ---\n{lesson.transcript.full_text}"


def build_generation_prompt(source_label: str, source_text: str) -> str:
    schema_json = json.dumps(DissertativaQuestionOut.model_json_schema(), ensure_ascii=False, indent=2)
    return f"""{INSTRUCTIONS_GENERATE}

FONTE: {source_label}

CONTEÚDO:
{source_text}

SCHEMA DE SAÍDA:
{schema_json}
"""


def build_correction_prompt(question: DissertativaQuestion, resposta_texto: str) -> str:
    schema_json = json.dumps(DissertativaCorrectionOut.model_json_schema(), ensure_ascii=False, indent=2)
    rubrica = json.loads(question.rubrica_json)
    rubrica_texto = "\n".join(f"- {item}" for item in rubrica)
    return f"""{INSTRUCTIONS_CORRECT}

ENUNCIADO:
{question.enunciado}

RUBRICA:
{rubrica_texto}

RESPOSTA DO ALUNO:
{resposta_texto}

SCHEMA DE SAÍDA:
{schema_json}
"""


def package_generation_as_markdown(source_label: str, prompt: str) -> str:
    return f"# Gerar questão dissertativa: {source_label}\n\n{prompt}"


def package_correction_as_markdown(question: DissertativaQuestion, prompt: str) -> str:
    return f"# Corrigir dissertativa #{question.id}\n\n{prompt}"


def generate_question_automatically(
    session: Session, *, subject_id: int | None, lesson_id: int | None, assunto_id: int | None,
    source_label: str, source_text: str, ai_client: AIClient,
) -> tuple[DissertativaQuestion, AiCall]:
    check_budget_or_raise(session)
    prompt = build_generation_prompt(source_label, source_text)
    response = ai_client.structured_call(
        prompt=prompt, schema=DissertativaQuestionOut.model_json_schema(), cache=False
    )
    from .. import config

    return _ingest_question(
        session, subject_id=subject_id, lesson_id=lesson_id, assunto_id=assunto_id,
        parsed_dict=json.loads(response.content), model=config.AI_MODEL, via="automatico",
        input_tokens=response.input_tokens, output_tokens=response.output_tokens,
        cache_read_input_tokens=response.cache_read_input_tokens,
    )


def ingest_question_manual_response(
    session: Session, *, subject_id: int | None, lesson_id: int | None, assunto_id: int | None, pasted_text: str,
) -> tuple[DissertativaQuestion, AiCall]:
    parsed_dict = parse_pasted_response(pasted_text)
    return _ingest_question(
        session, subject_id=subject_id, lesson_id=lesson_id, assunto_id=assunto_id,
        parsed_dict=parsed_dict, model="manual", via="manual",
        input_tokens=0, output_tokens=0, cache_read_input_tokens=0,
    )


def _ingest_question(
    session: Session, *, subject_id: int | None, lesson_id: int | None, assunto_id: int | None,
    parsed_dict: dict, model: str, via: str, input_tokens: int, output_tokens: int, cache_read_input_tokens: int,
) -> tuple[DissertativaQuestion, AiCall]:
    try:
        output = DissertativaQuestionOut.model_validate(parsed_dict)
    except ValidationError as exc:
        raise ProcessingError(f"resposta não bate com o formato esperado: {exc}") from exc

    cost = (
        estimate_cost_usd(model, input_tokens, output_tokens, cache_read_input_tokens)
        if via == "automatico"
        else 0.0
    )
    ai_call = AiCall(
        lesson_id=lesson_id, tipo_acao="dissertativa_gerar", via=via, modelo=model,
        input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=cache_read_input_tokens,
        custo_usd=cost, raw_response_json=json.dumps(parsed_dict, ensure_ascii=False),
    )
    session.add(ai_call)
    session.flush()

    question = DissertativaQuestion(
        subject_id=subject_id, lesson_id=lesson_id, assunto_id=assunto_id,
        enunciado=output.enunciado, rubrica_json=json.dumps(output.rubrica, ensure_ascii=False),
        ai_call_id=ai_call.id,
    )
    session.add(question)
    session.commit()
    return question, ai_call


def correct_attempt_automatically(session: Session, attempt: DissertativaAttempt, ai_client: AIClient) -> AiCall:
    check_budget_or_raise(session)
    question = session.get(DissertativaQuestion, attempt.question_id)
    prompt = build_correction_prompt(question, attempt.resposta_texto)
    response = ai_client.structured_call(
        prompt=prompt, schema=DissertativaCorrectionOut.model_json_schema(), cache=False
    )
    from .. import config

    return _ingest_correction(
        session, attempt, parsed_dict=json.loads(response.content), model=config.AI_MODEL, via="automatico",
        input_tokens=response.input_tokens, output_tokens=response.output_tokens,
        cache_read_input_tokens=response.cache_read_input_tokens,
    )


def ingest_correction_manual_response(session: Session, attempt: DissertativaAttempt, pasted_text: str) -> AiCall:
    parsed_dict = parse_pasted_response(pasted_text)
    return _ingest_correction(
        session, attempt, parsed_dict=parsed_dict, model="manual", via="manual",
        input_tokens=0, output_tokens=0, cache_read_input_tokens=0,
    )


def _ingest_correction(
    session: Session, attempt: DissertativaAttempt, *, parsed_dict: dict, model: str, via: str,
    input_tokens: int, output_tokens: int, cache_read_input_tokens: int,
) -> AiCall:
    try:
        output = DissertativaCorrectionOut.model_validate(parsed_dict)
    except ValidationError as exc:
        raise ProcessingError(f"resposta não bate com o formato esperado: {exc}") from exc

    attempt.pontos_cobertos_json = json.dumps(output.pontos_cobertos, ensure_ascii=False)
    attempt.pontos_faltantes_json = json.dumps(output.pontos_faltantes, ensure_ascii=False)
    attempt.comentario = output.comentario
    attempt.status = "avaliado"
    attempt.avaliado_em = datetime.now(timezone.utc)

    cost = (
        estimate_cost_usd(model, input_tokens, output_tokens, cache_read_input_tokens)
        if via == "automatico"
        else 0.0
    )
    ai_call = AiCall(
        lesson_id=None, tipo_acao="dissertativa_corrigir", via=via, modelo=model,
        input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=cache_read_input_tokens,
        custo_usd=cost, raw_response_json=json.dumps(parsed_dict, ensure_ascii=False),
    )
    session.add(ai_call)
    session.flush()
    attempt.ai_call_id = ai_call.id
    session.commit()
    return ai_call
