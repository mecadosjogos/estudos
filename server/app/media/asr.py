"""Interface do transcritor de áudio (ASR), injetável — mesma razão do ai/client.py.

A implementação real (faster-whisper) roda no worker (fase 4) e no ASR curto da
CPU da VPS (fase 13). Aqui fica só o contrato usado pelo pipeline do servidor.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Word:
    text: str
    start_s: float
    end_s: float
    probability: float


@dataclass
class TranscriptionResult:
    text: str
    words: list[Word]


class ASRClient(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str) -> TranscriptionResult: ...


class FakeASRClient(ASRClient):
    """Para testes: devolve uma transcrição fixa em vez de rodar o Whisper de verdade."""

    def __init__(self, fixed_result: TranscriptionResult | None = None):
        self.fixed_result = fixed_result or TranscriptionResult(text="", words=[])
        self.calls: list[str] = []

    def transcribe(self, audio_path: str) -> TranscriptionResult:
        self.calls.append(audio_path)
        return self.fixed_result


class RealASRClient(ASRClient):
    """`faster-whisper` de verdade, na CPU da VPS (fase 13) -- mesmo
    `WhisperTranscriber` da válvula de emergência (`routes/lessons.py`,
    fase 4), só com modelo pequeno. Carrega o modelo só no primeiro uso
    (não no import): a suíte de teste nunca instancia esta classe (usa
    `FakeASRClient`), mas se algum código chegasse a importá-la sem
    chamar `transcribe`, não faria sentido baixar/carregar o modelo à toa."""

    def __init__(self, model_size: str, compute_type: str):
        self._model_size = model_size
        self._compute_type = compute_type
        self._transcriber = None

    def transcribe(self, audio_path: str) -> TranscriptionResult:
        from shared.transcriber import WhisperTranscriber

        if self._transcriber is None:
            self._transcriber = WhisperTranscriber(self._model_size, device="cpu", compute_type=self._compute_type)

        output = self._transcriber.transcribe(audio_path)
        words = [
            Word(w.text, w.start_s, w.end_s, w.probability)
            for seg in output.segments
            for w in seg.words
        ]
        return TranscriptionResult(text=output.full_text, words=words)


def get_asr_client() -> ASRClient:
    from .. import config

    return RealASRClient(config.WHISPER_SHORT_MODEL, config.WHISPER_SHORT_COMPUTE_TYPE)
