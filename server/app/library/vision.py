"""Interface do cliente de visão (transcrição de páginas fotografadas), injetável.

Implementação real (`claude-haiku-4-5`) entra na fase 10. Ver ai/client.py para a
razão de existir atrás de interface desde já.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class VisionResult:
    text: str
    cost_usd: float


class VisionClient(ABC):
    @abstractmethod
    def transcribe_page(self, image_path: str) -> VisionResult: ...


class FakeVisionClient(VisionClient):
    """Para testes: devolve uma transcrição fixa em vez de chamar a API de visão."""

    def __init__(self, fixed_result: VisionResult | None = None):
        self.fixed_result = fixed_result or VisionResult(text="", cost_usd=0.0)
        self.calls: list[str] = []

    def transcribe_page(self, image_path: str) -> VisionResult:
        self.calls.append(image_path)
        return self.fixed_result
