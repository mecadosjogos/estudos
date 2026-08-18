"""Sinais determinísticos calculados em código, antes da chamada de IA
(PLANO.md): repetição, queda de ritmo (ditado) e tempo por tópico. Custam
nada, são reprodutíveis, e melhoram o destaque sem a IA precisar adivinhar —
ela recebe isso pronto como anotação no prompt.

Opera sobre dataclasses simples, não sobre os modelos do SQLAlchemy: mantém
os testes rápidos e sem precisar de banco, e deixa claro que é lógica pura.
"""

import re
from dataclasses import dataclass, field

STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "que", "em",
    "um", "uma", "é", "no", "na", "se", "por", "com", "para", "não", "ne",
    "então", "isso", "aí", "né", "ao", "aos", "às", "à",
}


@dataclass
class WordInput:
    text: str
    start_s: float
    end_s: float
    probability: float = 1.0


@dataclass
class SegmentInput:
    idx: int
    start_s: float
    end_s: float
    text: str
    words: list[WordInput] = field(default_factory=list)


@dataclass
class RepetitionOccurrence:
    idx: int
    start_s: float
    end_s: float
    text: str


@dataclass
class RepetitionGroup:
    representative_text: str
    occurrences: list[RepetitionOccurrence]
    count: int
    total_duration_s: float


@dataclass
class DictationSpan:
    idx: int
    start_s: float
    end_s: float
    text: str
    words_per_minute: float
    average_words_per_minute: float


def _normalize_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zà-ú0-9]+", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def detect_repetitions(
    segments: list[SegmentInput], similarity_threshold: float = 0.6, min_tokens: int = 3
) -> list[RepetitionGroup]:
    """Agrupa segmentos com conteúdo parecido por similaridade de Jaccard
    sobre os tokens normalizados. O(n²) — aceitável porque isso roda uma vez
    por processamento de aula, não em caminho quente."""
    candidates = []
    for seg in segments:
        tokens = _normalize_tokens(seg.text)
        if len(tokens) >= min_tokens:
            candidates.append((seg, tokens))

    used = set()
    groups: list[RepetitionGroup] = []

    for i, (seg_a, tokens_a) in enumerate(candidates):
        if seg_a.idx in used:
            continue
        occurrences = [RepetitionOccurrence(seg_a.idx, seg_a.start_s, seg_a.end_s, seg_a.text)]
        used.add(seg_a.idx)

        for seg_b, tokens_b in candidates[i + 1 :]:
            if seg_b.idx in used:
                continue
            intersection = len(tokens_a & tokens_b)
            union = len(tokens_a | tokens_b)
            similarity = intersection / union if union else 0.0
            if similarity >= similarity_threshold:
                occurrences.append(RepetitionOccurrence(seg_b.idx, seg_b.start_s, seg_b.end_s, seg_b.text))
                used.add(seg_b.idx)

        if len(occurrences) > 1:
            total_duration = sum(o.end_s - o.start_s for o in occurrences)
            groups.append(
                RepetitionGroup(
                    representative_text=occurrences[0].text,
                    occurrences=occurrences,
                    count=len(occurrences),
                    total_duration_s=total_duration,
                )
            )

    return groups


def detect_dictation(
    segments: list[SegmentInput], drop_ratio: float = 0.5, min_words: int = 4
) -> list[DictationSpan]:
    """Sinaliza segmentos onde o ritmo (palavras/minuto) cai bem abaixo da
    média da aula — o professor desacelerando para você copiar."""
    rates = []
    for seg in segments:
        duration_min = (seg.end_s - seg.start_s) / 60
        word_count = len(seg.words) if seg.words else len(seg.text.split())
        if duration_min <= 0 or word_count < min_words:
            continue
        rates.append((seg, word_count / duration_min))

    if not rates:
        return []

    average = sum(r for _, r in rates) / len(rates)
    threshold = average * drop_ratio

    return [
        DictationSpan(seg.idx, seg.start_s, seg.end_s, seg.text, rate, average)
        for seg, rate in rates
        if rate < threshold
    ]


def build_signals_annotation(segments: list[SegmentInput]) -> dict:
    """Empacota os sinais como o bloco de metadados que entra no prompt."""
    repetitions = detect_repetitions(segments)
    dictation = detect_dictation(segments)
    return {
        "repeticoes": [
            {
                "texto": g.representative_text,
                "ocorrencias": [
                    {"start_s": o.start_s, "end_s": o.end_s, "texto": o.text} for o in g.occurrences
                ],
                "contagem": g.count,
                "tempo_total_s": g.total_duration_s,
            }
            for g in repetitions
        ],
        "ditado": [
            {
                "start_s": d.start_s,
                "end_s": d.end_s,
                "texto": d.text,
                "palavras_por_minuto": round(d.words_per_minute, 1),
                "media_palavras_por_minuto": round(d.average_words_per_minute, 1),
            }
            for d in dictation
        ],
    }
