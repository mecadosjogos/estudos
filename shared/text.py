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
# tabela: a linha separadora (|---|:--:|) some; nas demais, cada célula vira
# um trecho de frase separado por vírgula
_TABLE_SEPARATOR_RE = re.compile(r"^[ \t]*\|?(?:[ \t]*:?-{3,}:?[ \t]*\|?)+[ \t]*$", re.MULTILINE)
_TABLE_EDGE_RE = re.compile(r"^[ \t]*\|[ \t]*|[ \t]*\|[ \t]*$", re.MULTILINE)
_TABLE_PIPE_RE = re.compile(r"[ \t]*\|[ \t]*")
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
    # Guia editado no navegador volta com \r\n: o \r quebrava o "$" das
    # regras por linha e sobrava no meio da pontuação (".\r.").
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = _FENCE_RE.sub(" ", texto)
    texto = _HR_RE.sub("", texto)
    # Citação antes de título: "> # Título" (material da aula citado) só
    # vira título solto depois que o ">" sai.
    texto = _BLOCKQUOTE_RE.sub("", texto)
    texto = _HEADER_RE.sub("", texto)
    texto = _TABLE_SEPARATOR_RE.sub("", texto)
    texto = _TABLE_EDGE_RE.sub("", texto)
    texto = _TABLE_PIPE_RE.sub(", ", texto)
    texto = _LIST_MARKER_RE.sub("", texto)
    texto = _LINK_RE.sub(r"\1", texto)
    texto = _INLINE_CODE_RE.sub(r"\1", texto)
    # Até parar de mudar: itálico dentro de negrito ("**disser *sempre* ou**")
    # só aparece depois que o negrito de fora sai.
    anterior = None
    while anterior != texto:
        anterior, texto = texto, _BOLD_ITALIC_RE.sub(r"\2", texto)
    texto = _BLANK_LINES_RE.sub(". ", texto)
    texto = _SINGLE_NEWLINE_RE.sub(". ", texto)
    return texto_para_fala(texto)


# --- símbolos --------------------------------------------------------------
#
# Depois do Markdown, o que sobra de sinal no texto também é lido em voz alta
# (ou vira ruído) pelo Chatterbox -- achado real no guia e nas questões do
# "Dominar o guia": "[trecho incompleto/inaudível na transcrição]" inteiro,
# "99,9%" virando "9999 dos nove nove", "=" e "+" de fórmulas, "·" de
# listas, ";." de item de lista que já fechava com ponto e vírgula.

_INAUDIVEL_RE = re.compile(r"\[[^\]]*(?:inaud[íi]vel|incompleto)[^\]]*\]", re.IGNORECASE)
_SUPRESSAO_RE = re.compile(r"\[\s*(?:\.{2,}|…)\s*\]")
_COLCHETES_RE = re.compile(r"[\[\]{}]")
_ARTIGO_RE = re.compile(r"\bart\.\s*", re.IGNORECASE)
_PORCENTO_RE = re.compile(r"\s*%")
_IGUAL_RE = re.compile(r"\s*=\s*")
_MAIS_RE = re.compile(r"\s+\+\s+")
_E_OU_RE = re.compile(r"\be/ou\b", re.IGNORECASE)
_BARRA_ENTRE_PALAVRAS_RE = re.compile(r"(?<=[^\W\d_])/(?=[^\W\d_])")
_TRAVESSAO_RE = re.compile(r"\s*[—–]\s*|\s+-\s+")
# Aspas somem; apóstrofo dentro de palavra ("rock'n'roll", "d'água") fica.
_ASPAS_RE = re.compile(r"[\"“”«»]|(?<![^\W\d_])['‘’]|['‘’](?![^\W\d_])")
_RESTO_MARKDOWN_RE = re.compile(r"[*#`_~^|\\<>]")
_PONTUACAO_SEGUIDA_RE = re.compile(r"[ \t]*([,;:.!?])(?:[ \t]*[,;:.!?])+")
_ESPACO_ANTES_PONTUACAO_RE = re.compile(r"[ \t]+([,;:.!?])")
_INICIO_PONTUADO_RE = re.compile(r"^[\s,;:.!?]+")
_FORCA = {"?": 5, "!": 5, ".": 4, ";": 3, ":": 2, ",": 1}


def _mais_forte(m: re.Match) -> str:
    return max(re.findall(r"[,;:.!?]", m.group(0)), key=_FORCA.__getitem__)


def texto_para_fala(texto: str) -> str:
    """Troca por palavra (ou tira) os símbolos que o TTS leria errado,
    deixando só letras, números e a pontuação que vira pausa."""
    texto = _INAUDIVEL_RE.sub(", trecho inaudível, ", texto)
    texto = _SUPRESSAO_RE.sub(" ", texto)
    texto = _COLCHETES_RE.sub(" ", texto)
    texto = _ARTIGO_RE.sub("artigo ", texto)
    texto = texto.replace("§", " parágrafo ").replace("×", " versus ")
    texto = _PORCENTO_RE.sub(" por cento", texto)
    texto = _IGUAL_RE.sub(" é ", texto)
    texto = _MAIS_RE.sub(" mais ", texto)
    texto = _E_OU_RE.sub("e ou", texto)
    texto = _BARRA_ENTRE_PALAVRAS_RE.sub(" ou ", texto)
    texto = texto.replace("/", " ")
    texto = _TRAVESSAO_RE.sub(", ", texto)
    texto = texto.replace("·", ", ").replace("…", ". ")
    texto = _ASPAS_RE.sub("", texto)
    texto = _RESTO_MARKDOWN_RE.sub(" ", texto)
    texto = _ESPACO_ANTES_PONTUACAO_RE.sub(r"\1", texto)
    texto = _PONTUACAO_SEGUIDA_RE.sub(_mais_forte, texto)
    texto = _INICIO_PONTUADO_RE.sub("", texto)
    return _SPACES_RE.sub(" ", texto).strip()
