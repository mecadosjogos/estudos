"""Interface do cliente de IA, injetável.

PLANO.md, Limites operacionais: os testes que mais importam (preservação de edições
no reprocessamento, ciclo de vida do chunk, recorte de contexto) não têm como rodar
se cada um exigir chamada real, dinheiro e minutos de espera. A implementação real
(Anthropic, `claude-opus-5`) entra na fase 6; por enquanto só a interface e um fake
para os testes já poderem depender dela.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AIResponse:
    content: str
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0


class AIClient(ABC):
    @abstractmethod
    def structured_call(self, *, prompt: str, schema: dict, cache: bool = False) -> AIResponse:
        """Envia um prompt e recebe de volta uma saída validada contra `schema`."""


class FakeAIClient(AIClient):
    """Para testes: devolve respostas pré-gravadas em vez de chamar a API de verdade."""

    def __init__(self, fixed_response: AIResponse | None = None):
        self.fixed_response = fixed_response or AIResponse(
            content="{}", input_tokens=0, output_tokens=0
        )
        self.calls: list[str] = []

    def structured_call(self, *, prompt: str, schema: dict, cache: bool = False) -> AIResponse:
        self.calls.append(prompt)
        return self.fixed_response
