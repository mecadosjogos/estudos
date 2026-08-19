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
