"""Parser tolerante da resposta colada de volta (PLANO.md, ponte manual):
procura o último bloco ```json; se não achar, tenta o texto inteiro. Sobra
de conversa em volta não pode atrapalhar."""

import json
import re

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_pasted_response(text: str) -> dict:
    blocks = _JSON_BLOCK_RE.findall(text)
    candidate = blocks[-1] if blocks else text

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "não consegui entender a resposta colada — confira se é o JSON completo "
            f"(erro: {exc})"
        ) from exc
