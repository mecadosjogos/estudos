"""Orquestra o processamento de uma aula (PLANO.md, fase 6): sinais em
código -> prompt -> chamada (automática ou colada manualmente) -> diff por
deriv_key -> persistência. As regras de integridade (deriv_key, reconciliação,
teto de custo) rodam sempre, nos dois caminhos."""

import json
from datetime import date, datetime, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..ai.client import AIClient
from ..assuntos import normalize_slug
from ..models import (
    AiCall,
    AnnouncementProposal,
    ArticleMention,
    CardProposal,
    EditedBlock,
    Lesson,
    LessonAssunto,
    OutlineItem,
    TranscriptSegment,
)
from .bridge import build_prompt
from .budget import check_budget_or_raise
from .deriv_key import compute_deriv_key
from .parse import parse_pasted_response
from .pricing import estimate_cost_usd
from .reconcile import reconcile
from .schemas import LessonProcessingOutput
from .signals import SegmentInput, WordInput, build_signals_annotation
from ..transcript_confidence import LOW_CONFIDENCE_THRESHOLD, word_probabilities


class ProcessingError(Exception):
    pass


def _segment_inputs(segments: list[TranscriptSegment]) -> list[SegmentInput]:
    result = []
    for seg in segments:
        words_raw = json.loads(seg.words_json) if seg.words_json else []
        words = [
            WordInput(w.get("text", ""), w.get("start_s", 0.0), w.get("end_s", 0.0), w.get("probability", 1.0))
            for w in words_raw
        ]
        result.append(SegmentInput(seg.idx, seg.start_s, seg.end_s, seg.text, words=words))
    return result


def _disambiguated_key(
    occurrence_counts: dict[tuple, int], tipo: str, start_s: float, end_s: float, source_text: str
) -> str:
    """Duas propostas do mesmo tipo podem nascer do mesmo intervalo (dois
    cards sobre o mesmo trecho, por exemplo) — sem isso colidiriam na mesma
    deriv_key e uma sumiria no reconcile."""
    interval_key = (tipo, round(start_s, 1), round(end_s, 1))
    occurrence = occurrence_counts.get(interval_key, 0)
    occurrence_counts[interval_key] = occurrence + 1
    tipo_com_ocorrencia = tipo if occurrence == 0 else f"{tipo}-{occurrence}"
    return compute_deriv_key(tipo_com_ocorrencia, start_s, end_s, source_text)


def _source_text_for_interval(segments: list[TranscriptSegment], start_s: float, end_s: float) -> str:
    """O deriv_key hasheia isto, não o texto que a IA gerou — é o que
    mantém a chave estável entre reprocessamentos mesmo quando a IA
    reformula diferente na próxima passada (Integridade #1 do PLANO.md:
    a chave é sobre a origem, não sobre a saída)."""
    parts = [seg.text for seg in segments if seg.end_s >= start_s and seg.start_s <= end_s]
    return " ".join(parts) if parts else f"{start_s}-{end_s}"


def _low_confidence(segments: list[TranscriptSegment], start_s: float, end_s: float) -> bool:
    """Média de probabilidade das palavras do Whisper no intervalo — abaixo
    do limiar, o servidor marca pra você confirmar com um toque (PLANO.md).
    Mesmo cálculo de `transcript_confidence.py`, usado também na tela de
    revisão da transcrição (fase 8) — um só lugar decide o que é "baixo"."""
    probs = [
        p
        for seg in segments
        if seg.end_s >= start_s and seg.start_s <= end_s
        for p in word_probabilities(seg)
    ]
    if not probs:
        return False
    return (sum(probs) / len(probs)) < LOW_CONFIDENCE_THRESHOLD


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def build_prompt_for_lesson(lesson: Lesson) -> tuple[str, dict]:
    if lesson.transcript is None:
        raise ProcessingError("aula sem transcrição — transcreva antes de processar")
    segments = _segment_inputs(lesson.transcript.segments)
    signals = build_signals_annotation(segments)
    prompt = build_prompt(lesson, lesson.transcript.segments, signals)
    return prompt, signals


def process_lesson_automatically(session: Session, lesson: Lesson, ai_client: AIClient) -> AiCall:
    check_budget_or_raise(session)

    prompt, _signals = build_prompt_for_lesson(lesson)
    response = ai_client.structured_call(
        prompt=prompt, schema=LessonProcessingOutput.model_json_schema(), cache=True
    )

    from .. import config

    return _ingest(
        session,
        lesson,
        parsed_dict=json.loads(response.content),
        model=config.AI_MODEL,
        via="automatico",
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cache_read_input_tokens=response.cache_read_input_tokens,
    )


def ingest_manual_response(session: Session, lesson: Lesson, pasted_text: str) -> AiCall:
    parsed_dict = parse_pasted_response(pasted_text)
    return _ingest(
        session,
        lesson,
        parsed_dict=parsed_dict,
        model="manual",
        via="manual",
        input_tokens=0,
        output_tokens=0,
        cache_read_input_tokens=0,
    )


def _ingest(
    session: Session,
    lesson: Lesson,
    *,
    parsed_dict: dict,
    model: str,
    via: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int,
) -> AiCall:
    try:
        output = LessonProcessingOutput.model_validate(parsed_dict)
    except ValidationError as exc:
        raise ProcessingError(f"resposta não bate com o formato esperado: {exc}") from exc

    lesson.resumo = output.resumo
    transcript_segments = lesson.transcript.segments if lesson.transcript else []

    block_counts: dict[tuple, int] = {}
    block_items = []
    for ordem, b in enumerate(output.aula_editada):
        source_text = _source_text_for_interval(transcript_segments, b.start_s, b.end_s)
        key = _disambiguated_key(block_counts, b.tipo, b.start_s, b.end_s, source_text)
        block_items.append(
            (
                key,
                {
                    "ordem": ordem,
                    "tipo": b.tipo,
                    "texto": b.texto,
                    "start_s": b.start_s,
                    "end_s": b.end_s,
                    "origens_json": json.dumps([{"start_s": b.start_s, "end_s": b.end_s}]),
                    "repeticoes": 1,
                    "baixa_confianca": _low_confidence(transcript_segments, b.start_s, b.end_s),
                },
            )
        )
    reconcile(session, EditedBlock, lesson.id, block_items, has_versao_nova=True)

    outline_counts: dict[tuple, int] = {}
    outline_items = [
        (
            _disambiguated_key(
                outline_counts,
                "indice",
                o.start_s,
                o.end_s,
                _source_text_for_interval(transcript_segments, o.start_s, o.end_s),
            ),
            {"ordem": ordem, "titulo": o.titulo, "start_s": o.start_s, "end_s": o.end_s},
        )
        for ordem, o in enumerate(output.indice)
    ]
    reconcile(session, OutlineItem, lesson.id, outline_items)

    article_counts: dict[tuple, int] = {}
    article_items = [
        (
            _disambiguated_key(
                article_counts,
                "artigo",
                a.start_s,
                a.start_s,
                _source_text_for_interval(transcript_segments, a.start_s, a.start_s + 1),
            ),
            {
                "texto_citado": a.texto_citado,
                "start_s": a.start_s,
                "baixa_confianca": _low_confidence(transcript_segments, a.start_s, a.start_s + 1),
            },
        )
        for a in output.artigos
    ]
    reconcile(session, ArticleMention, lesson.id, article_items)

    announcement_counts: dict[tuple, int] = {}
    announcement_items = [
        (
            _disambiguated_key(
                announcement_counts,
                "data",
                a.start_s,
                a.start_s,
                _source_text_for_interval(transcript_segments, a.start_s, a.start_s + 1),
            ),
            {
                "texto": a.texto,
                "data_anunciada": _parse_iso_date(a.data_anunciada),
                "start_s": a.start_s,
            },
        )
        for a in output.datas_anunciadas
    ]
    reconcile(session, AnnouncementProposal, lesson.id, announcement_items)

    card_counts: dict[tuple, int] = {}
    card_items = [
        (
            _disambiguated_key(
                card_counts,
                "card",
                c.start_s,
                c.end_s,
                _source_text_for_interval(transcript_segments, c.start_s, c.end_s),
            ),
            {"frente": c.frente, "verso": c.verso, "start_s": c.start_s, "end_s": c.end_s},
        )
        for c in output.cards
    ]
    reconcile(session, CardProposal, lesson.id, card_items, has_versao_nova=True)

    # Assunto (fase 8): sem intervalo -- a proposta é sobre a aula inteira,
    # então a chave de dedup é o slug do texto, não um hash de intervalo.
    assunto_items = [
        (f"assunto:{normalize_slug(texto)}", {"texto_proposto": texto}) for texto in output.assuntos
    ]
    reconcile(session, LessonAssunto, lesson.id, assunto_items)

    cost = (
        estimate_cost_usd(model, input_tokens, output_tokens, cache_read_input_tokens)
        if via == "automatico"
        else 0.0
    )
    ai_call = AiCall(
        lesson_id=lesson.id,
        tipo_acao="processar_aula",
        via=via,
        modelo=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        custo_usd=cost,
        raw_response_json=json.dumps(parsed_dict, ensure_ascii=False),
    )
    session.add(ai_call)
    session.commit()
    return ai_call
