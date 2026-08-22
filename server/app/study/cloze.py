"""Cloze na aula editada (PLANO.md, fase 8b, Absorção #4): os trechos-chave
dos blocos `ditado` e `conceito` somem no modo estudo e você preenche —
recuperação ativa reaproveitando blocos que já estão classificados, sem
tela nova nem chamada de IA. "A feature mais barata da lista".

A escolha de quais palavras mascarar é determinística (mesmo texto, mesma
escolha sempre) — as mais longas fora de uma lista de conectivos — pra dar
pra testar isolado (PLANO.md, item 16 dos testes: "não apaga a frase
inteira nem palavra irrelevante"). O mascaramento em si é CSS
(.study-mode .cloze-word); o HTML é o mesmo com ou sem o modo estudo
ativo, então nada disso muda o que é salvo no banco.
"""

import html
import re

CLOZE_TIPOS = ("ditado", "conceito")

MIN_WORD_LEN = 4

_STOPWORDS = {
    "aqui", "aquilo", "aquela", "aquele", "aquelas", "aqueles",
    "assim", "então", "isso", "isto", "esta", "este",
    "muito", "muita", "muitos", "muitas", "mais", "menos",
    "também", "ainda", "apenas", "sobre", "entre", "quando", "quanto",
    "porque", "porém", "sendo", "sido", "seja", "sejam", "estar", "estão",
    "estava", "estavam", "tinha", "tinham", "tendo", "onde", "quais",
    "qual", "quem", "para", "pelo", "pela", "pelos", "pelas", "como",
    "cada", "todo", "toda", "todos", "todas", "esse", "essa", "esses",
    "essas", "seus", "suas", "nosso", "nossa", "nossos", "nossas", "gente",
}

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def select_blanks(texto: str, max_blanks: int = 3) -> list[dict]:
    """Escolhe até `max_blanks` palavras pra mascarar: as mais longas fora
    da lista de conectivos comuns. Nunca a frase inteira (só palavras
    isoladas) e nunca uma palavra curta/irrelevante (comprimento mínimo +
    lista de conectivos). Devolve na ordem em que aparecem no texto."""
    candidates = []
    for match in _WORD_RE.finditer(texto):
        word = match.group()
        if len(word) < MIN_WORD_LEN:
            continue
        if word.lower() in _STOPWORDS:
            continue
        candidates.append((match.start(), match.end(), word))

    if not candidates:
        return []

    ranked = sorted(candidates, key=lambda c: (-len(c[2]), c[0]))
    chosen = sorted(ranked[:max_blanks], key=lambda c: c[0])
    return [{"start": start, "end": end, "palavra": word} for start, end, word in chosen]


def render_cloze_html(texto: str, blanks: list[dict]) -> str:
    """Envolve as palavras escolhidas num span clicável; o resto do texto é
    escapado normalmente, sem nenhuma palavra a mais mascarada."""
    if not blanks:
        return html.escape(texto)

    parts = []
    cursor = 0
    for blank in blanks:
        parts.append(html.escape(texto[cursor : blank["start"]]))
        word = html.escape(blank["palavra"])
        parts.append(f'<span class="cloze-word" data-answer="{word}">{word}</span>')
        cursor = blank["end"]
    parts.append(html.escape(texto[cursor:]))
    return "".join(parts)
