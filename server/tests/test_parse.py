import json

import pytest

from app.ai.parse import parse_pasted_response


def test_simple_json_block():
    payload = {"a": 1}
    text = "```json\n" + json.dumps(payload) + "\n```"
    assert parse_pasted_response(text) == payload


def test_prose_around_block_is_ignored():
    payload = {"a": 1}
    text = "texto antes\n```json\n" + json.dumps(payload) + "\n```\ntexto depois"
    assert parse_pasted_response(text) == payload


def test_internal_code_fence_inside_string_value_does_not_confuse_parser():
    """Achado real (processamento da aula 16): um `guia_md` citando material
    com cerca de código interna fazia o parser antigo (sem âncora de linha)
    casar a cerca de dentro da string em vez da cerca externa do bloco."""
    payload = {
        "guia_md": "# Título\n\nTexto antes.\n\n```\ncitação formatada\n```\n\nTexto depois.",
        "outro_campo": "valor",
    }
    text = "```json\n" + json.dumps(payload) + "\n```"
    assert parse_pasted_response(text) == payload


def test_multiple_blocks_takes_the_last_one():
    rascunho = {"a": "rascunho"}
    final = {"a": "final"}
    text = (
        "aqui vai um rascunho:\n```json\n"
        + json.dumps(rascunho)
        + "\n```\nagora a versão final:\n```json\n"
        + json.dumps(final)
        + "\n```"
    )
    assert parse_pasted_response(text) == final


def test_no_fence_falls_back_to_whole_text():
    payload = {"a": 1}
    text = json.dumps(payload)
    assert parse_pasted_response(text) == payload


def test_invalid_json_raises_value_error_with_helpful_message():
    with pytest.raises(ValueError, match="não consegui entender"):
        parse_pasted_response("```json\n{not valid json\n```")


def test_crlf_line_endings_do_not_break_fence_matching():
    """Achado real (aula 16, segunda passada): arquivo gravado no Windows
    com CRLF deixava um \\r antes da quebra de linha, e a cerca de
    fechamento parava de bater com o regex."""
    payload = {"a": 1}
    text = ("```json\n" + json.dumps(payload) + "\n```").replace("\n", "\r\n")
    assert parse_pasted_response(text) == payload
