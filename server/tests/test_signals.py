from app.ai.signals import (
    SegmentInput,
    WordInput,
    build_signals_annotation,
    detect_dictation,
    detect_repetitions,
)


def test_detect_repetitions_groups_similar_segments():
    segments = [
        SegmentInput(0, 0.0, 5.0, "a usucapião extraordinária exige quinze anos de posse"),
        SegmentInput(1, 10.0, 15.0, "hoje vamos falar de outro assunto completamente diferente"),
        SegmentInput(2, 60.0, 65.0, "lembrem que a usucapião extraordinária exige quinze anos"),
    ]

    groups = detect_repetitions(segments)

    assert len(groups) == 1
    assert groups[0].count == 2
    assert {o.idx for o in groups[0].occurrences} == {0, 2}


def test_detect_repetitions_ignores_unrelated_segments():
    segments = [
        SegmentInput(0, 0.0, 5.0, "capacidade civil e a aptidão para exercer direitos"),
        SegmentInput(1, 10.0, 15.0, "domicílio é o local onde a pessoa estabelece residência"),
    ]

    groups = detect_repetitions(segments)

    assert groups == []


def test_detect_dictation_flags_slow_segments():
    fast_words = [WordInput(f"palavra{i}", i * 0.2, i * 0.2 + 0.15) for i in range(20)]
    slow_words = [WordInput(f"palavra{i}", i * 2.0, i * 2.0 + 1.5) for i in range(4)]

    segments = [
        SegmentInput(0, 0.0, 4.0, "fala rápida normal", words=fast_words),
        SegmentInput(1, 10.0, 18.0, "art. um dois três oito", words=slow_words),
    ]

    dictation = detect_dictation(segments)

    assert len(dictation) == 1
    assert dictation[0].idx == 1
    assert dictation[0].words_per_minute < dictation[0].average_words_per_minute


def test_detect_dictation_empty_when_uniform_pace():
    segments = [
        SegmentInput(0, 0.0, 4.0, "um dois três quatro", words=[WordInput(w, i, i + 0.5) for i, w in enumerate(["um", "dois", "três", "quatro"])]),
        SegmentInput(1, 5.0, 9.0, "cinco seis sete oito", words=[WordInput(w, i, i + 0.5) for i, w in enumerate(["cinco", "seis", "sete", "oito"])]),
    ]

    assert detect_dictation(segments) == []


def test_build_signals_annotation_shape():
    segments = [
        SegmentInput(0, 0.0, 5.0, "a boa-fé objetiva rege os contratos no código civil"),
        SegmentInput(1, 30.0, 35.0, "a boa-fé objetiva rege os contratos no código civil mesmo"),
    ]

    annotation = build_signals_annotation(segments)

    assert "repeticoes" in annotation
    assert "ditado" in annotation
    assert annotation["repeticoes"][0]["contagem"] == 2
