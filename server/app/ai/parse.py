"""Parser tolerante da resposta colada de volta (PLANO.md, ponte manual):
procura o último bloco ```json; se não achar, tenta o texto inteiro. Sobra
de conversa em volta não pode atrapalhar.

A cerca só conta se estiver sozinha na linha (```` ^```(?:json)?$ ````) --
um `guia_md` pode legitimamente citar material com cerca de código dentro
do próprio texto (ex.: "Material da aula:" reproduzindo algo formatado);
como está dentro de uma string JSON, essa cerca interna nunca fica sozinha
numa linha de verdade (as quebras de linha do valor são `\\n` escapado,
texto, não quebra real) -- só a cerca externa, a que delimita o bloco
colado, fica. Um regex sem essa âncora confundia as duas."""

import json
import re

_FENCE_LINE_RE = re.compile(r"^```(?:json)?[ \t]*$", re.MULTILINE)


def parse_pasted_response(text: str) -> dict:
    # CRLF (arquivo gravado no Windows) deixa um `\r` sobrando antes da
    # quebra de linha -- sem isso, a cerca de fechamento "```" + "\r" não
    # batia com `[ \t]*$` e o parser tentava o texto inteiro, sempre
    # falhando (achado real processando a aula 16 pela segunda vez).
    text = text.replace("\r\n", "\n")
    fences = list(_FENCE_LINE_RE.finditer(text))
    if len(fences) >= 2:
        # Pareia abre/fecha consecutivos e usa o último par -- se a resposta
        # colada trouxer mais de um bloco (rascunho + versão final), o
        # último é o que vale.
        candidate = text[fences[-2].end():fences[-1].start()]
    else:
        candidate = text

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "não consegui entender a resposta colada — confira se é o JSON completo "
            f"(erro: {exc})"
        ) from exc
