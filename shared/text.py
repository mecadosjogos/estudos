"""Prepara texto em Markdown pra ser falado por um motor de TTS.

O corpo de cada `GuiaSecao` é Markdown rico de verdade -- sub-títulos em
qualquer profundidade, negrito, listas, links (ver a instrução dada à IA em
`server/app/ai/bridge.py`) -- pensado pra ser renderizado em HTML
(`server/app/routes/lessons.py::view_guia`), não falado. Sem essa limpeza, o
TTS lê os próprios sinais de formatação em voz alta (achado real: "##",
"**", marcadores de lista viravam ruído no meio da narração) em vez de só o
texto. Único consumidor: worker/main.py::process_tts_job.
"""

import re

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_HR_RE = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", re.MULTILINE)
_HEADER_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^[ \t]*>[ \t]?", re.MULTILINE)
_LIST_MARKER_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_BOLD_ITALIC_RE = re.compile(r"(\*\*\*|\*\*|\*|___|__|_)(.+?)\1", re.DOTALL)
_BLANK_LINES_RE = re.compile(r"\n[ \t]*\n+")
_SINGLE_NEWLINE_RE = re.compile(r"\n")
_SPACES_RE = re.compile(r"[ \t]{2,}")


def markdown_para_narracao(texto: str) -> str:
    """Devolve `texto` sem sinais de formatação Markdown, com quebras de
    parágrafo/lista/título viradas em pausa de frase (". ") em vez de
    simplesmente somem -- perder a quebra colaria frases sem pausa nenhuma."""
    texto = _FENCE_RE.sub(" ", texto)
    texto = _HR_RE.sub("", texto)
    texto = _HEADER_RE.sub("", texto)
    texto = _BLOCKQUOTE_RE.sub("", texto)
    texto = _LIST_MARKER_RE.sub("", texto)
    texto = _LINK_RE.sub(r"\1", texto)
    texto = _INLINE_CODE_RE.sub(r"\1", texto)
    texto = _BOLD_ITALIC_RE.sub(r"\2", texto)
    texto = _BLANK_LINES_RE.sub(". ", texto)
    texto = _SINGLE_NEWLINE_RE.sub(". ", texto)
    texto = _SPACES_RE.sub(" ", texto)
    return texto.strip()
