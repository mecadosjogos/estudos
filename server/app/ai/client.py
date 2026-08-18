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


class AnthropicAIClient(AIClient):
    """Implementação real — ainda não testada nesta sessão (sem
    ANTHROPIC_API_KEY disponível). Usa tool-use forçado pra obter saída
    estruturada e cache_control no prompt quando `cache=True` (PLANO.md:
    'o cache_control fica no recorte')."""

    def __init__(self, api_key: str, model: str):
        from anthropic import Anthropic

        self.client = Anthropic(api_key=api_key)
        self.model = model

    def structured_call(self, *, prompt: str, schema: dict, cache: bool = False) -> AIResponse:
        import json

        tool_name = "responder_estruturado"
        content_block = {"type": "text", "text": prompt}
        if cache:
            content_block["cache_control"] = {"type": "ephemeral"}

        message = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            tools=[
                {
                    "name": tool_name,
                    "description": "Devolve a resposta no formato pedido.",
                    "input_schema": schema,
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": [content_block]}],
        )

        tool_use = next(block for block in message.content if block.type == "tool_use")
        usage = message.usage
        return AIResponse(
            content=json.dumps(tool_use.input),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )


def get_ai_client() -> AIClient:
    from .. import config

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY não configurada — só o modo manual funciona")
    return AnthropicAIClient(api_key=config.ANTHROPIC_API_KEY, model=config.AI_MODEL)
