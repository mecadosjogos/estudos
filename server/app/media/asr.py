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
