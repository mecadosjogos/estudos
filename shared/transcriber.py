"""Wrapper fino sobre faster-whisper, usado pelo worker (GPU local) e pelo
caminho de emergência "transcrever na VPS agora" (CPU, modelo médio).

Não é a interface injetável de server/app/media/asr.py — aquela existe para
o ASR curto do Feynman (fase 13) e para testes sem chamada real. Esta aqui é
a implementação de verdade, isolada porque exige a dependência pesada
(faster-whisper) e não deve ser importada em contexto de teste.
"""

from dataclasses import dataclass, field


@dataclass
class WordTiming:
    text: str
    start_s: float
    end_s: float
    probability: float


@dataclass
class SegmentResult:
    idx: int
    start_s: float
    end_s: float
    text: str
    words: list[WordTiming] = field(default_factory=list)


@dataclass
class TranscriptionOutput:
    full_text: str
    duration_s: float
    segments: list[SegmentResult]


class WhisperTranscriber:
    def __init__(self, model_size: str, device: str, compute_type: str):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio_path: str, on_segment=None) -> TranscriptionOutput:
        """`on_segment(segment_result, duration_s)` é chamado a cada segmento
        pronto — dá pro worker imprimir progresso/ETA em tempo real."""
        segments_iter, info = self.model.transcribe(audio_path, word_timestamps=True)

        segments: list[SegmentResult] = []
        text_parts: list[str] = []
        for i, seg in enumerate(segments_iter):
            words = [
                WordTiming(w.word.strip(), w.start, w.end, w.probability)
                for w in (seg.words or [])
            ]
            result = SegmentResult(
                idx=i, start_s=seg.start, end_s=seg.end, text=seg.text.strip(), words=words
            )
            segments.append(result)
            text_parts.append(result.text)
            if on_segment:
                on_segment(result, info.duration)

        return TranscriptionOutput(
            full_text=" ".join(text_parts), duration_s=info.duration, segments=segments
        )
