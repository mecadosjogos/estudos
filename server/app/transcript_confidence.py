"""Confiança da transcrição: sinal do próprio Whisper (probabilidade por
palavra em `TranscriptSegment.words_json`), nunca de uma passada de IA.
Compartilhado entre a revisão humana da transcrição (fase 8) e a
marcação de baixa confiança da fase 6 (citação de artigo, latim) --
mesmo cálculo, dois lugares que precisam bater."""

import json

from .models import TranscriptSegment

LOW_CONFIDENCE_THRESHOLD = 0.5


def word_probabilities(segment: TranscriptSegment) -> list[float]:
    words = json.loads(segment.words_json) if segment.words_json else []
    return [w.get("probability", 1.0) for w in words]


def segment_confidence(segment: TranscriptSegment) -> float | None:
    probs = word_probabilities(segment)
    return (sum(probs) / len(probs)) if probs else None


def is_low_confidence_segment(segment: TranscriptSegment) -> bool:
    confidence = segment_confidence(segment)
    return confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD


REPEAT_WINDOW_S = 30.0


def has_recent_repeat(segments: list[TranscriptSegment], index: int, window_s: float = REPEAT_WINDOW_S) -> bool:
    """Texto idêntico a outro trecho dentro de uma janela curta de tempo é
    sinal de loop de repetição do Whisper -- mesmo com probabilidade de
    palavra alta. Num loop desses o modelo fica "confiante" reforçando o
    próprio erro (confirmado com um caso real: seis trechos repetindo a
    mesma palavra, cada um com probabilidade individual razoável).
    `segments` precisa estar ordenado por tempo (por `idx`, como já vem
    do banco); a busca varre só a vizinhança dentro da janela, não a
    lista inteira."""
    segment = segments[index]
    normalized = segment.text.strip().lower()
    if not normalized:
        return False

    j = index - 1
    while j >= 0 and segment.start_s - segments[j].start_s <= window_s:
        if segments[j].text.strip().lower() == normalized:
            return True
        j -= 1

    j = index + 1
    while j < len(segments) and segments[j].start_s - segment.start_s <= window_s:
        if segments[j].text.strip().lower() == normalized:
            return True
        j += 1

    return False


def is_suspicious_segment(segments: list[TranscriptSegment], index: int) -> bool:
    """União dos dois sinais: probabilidade baixa OU repetição recente.
    É o que a tela de revisão usa pra marcar "baixa confiança" -- a
    fase 6 (citação/latim) continua só com `is_low_confidence_segment`,
    que é sobre um intervalo, não uma lista posicional."""
    return is_low_confidence_segment(segments[index]) or has_recent_repeat(segments, index)
