"""Motores da IA local (worker/ia_local.py). Cada motor executa UMA chamada
do job ({id, rotulo, sistema, prompt, schema, temperatura, max_tokens}) e
devolve o JSON já como dict -- o ouvinte não sabe o que é juiz nem redator.
"""

import json
import re

_CERCA = re.compile(r"^```(?:json)?[ \t]*$", re.MULTILINE)


class ChamadaAbortada(Exception):
    """O servidor disse que o job não é mais nosso (cancelado ou devolvido
    pra fila por falta de sinal) -- parar sem reportar falha."""


class RespostaInvalida(Exception):
    """O modelo devolveu algo que não é o JSON pedido (truncado, ou texto)."""


def extrair_json(texto: str) -> dict:
    """Aceita JSON puro ou o último bloco ```json cercado de conversa --
    mesma regra do parser da ponte manual (server/app/ai/parse.py), copiada
    aqui porque o worker não importa o servidor."""
    texto = texto.replace("\r\n", "\n").strip()
    cercas = list(_CERCA.finditer(texto))
    candidato = texto[cercas[-2].end():cercas[-1].start()] if len(cercas) >= 2 else texto
    try:
        valor = json.loads(candidato)
    except json.JSONDecodeError as exc:
        # Último recurso: do primeiro "{" ao último "}".
        inicio, fim = candidato.find("{"), candidato.rfind("}")
        if inicio == -1 or fim <= inicio:
            raise RespostaInvalida(f"a resposta não é JSON: {exc}") from exc
        try:
            valor = json.loads(candidato[inicio : fim + 1])
        except json.JSONDecodeError as exc2:
            raise RespostaInvalida(f"a resposta não é JSON: {exc2}") from exc2
    if not isinstance(valor, dict):
        raise RespostaInvalida("a resposta é JSON, mas não é um objeto")
    return valor
