"""Preço por modelo (PLANO.md, seção IA) — estimativa, não a fonte de
verdade da Anthropic. Serve pro painel de gasto e pro teto mensal; o valor
que importa de verdade é o que a API realmente cobrar."""

# USD por milhão de tokens. cache_read é ~10% do preço de input (PLANO.md).
_PRICING_PER_MILLION = {
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-sonnet-5": {"input": 2.50, "output": 12.50},
}
_DEFAULT_PRICING = {"input": 5.00, "output": 25.00}
CACHE_READ_DISCOUNT = 0.10


def estimate_cost_usd(
    model: str, input_tokens: int, output_tokens: int, cache_read_input_tokens: int = 0
) -> float:
    pricing = _PRICING_PER_MILLION.get(model, _DEFAULT_PRICING)
    billable_input = max(0, input_tokens - cache_read_input_tokens)
    cost = (
        billable_input * pricing["input"]
        + cache_read_input_tokens * pricing["input"] * CACHE_READ_DISCOUNT
        + output_tokens * pricing["output"]
    ) / 1_000_000
    return round(cost, 6)
