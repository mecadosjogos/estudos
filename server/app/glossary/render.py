"""Aplica o casamento do glossário em cima de HTML já renderizado,
percorrendo só os **nós de texto** (nunca o interior de tag) -- PLANO.md:
"um passo percorre apenas os nós de texto do HTML já gerado (jamais o
interior de tags) e envolve os casamentos". O texto fica limpo no banco;
a marcação nasce aqui, em tempo de renderização, então corrigir uma
variante reflete em todo conteúdo passado sem reprocessar nada.

Não é um sanitizador de HTML de propósito geral -- assume que o HTML de
entrada já é confiável (gerado pelos próprios templates do app, não
input de usuário direto) e não trata `<script>`/`<style>` como caso
especial, porque nenhum bloco de texto do glossário passa por eles.
"""

import html
from html.parser import HTMLParser

from .matcher import VariantEntry, find_matches


class _TextNodeWalker(HTMLParser):
    """Reconstrói o HTML pedaço a pedaço: cada tag passa intacta, cada
    nó de texto vira uma entrada própria pra poder ser processado
    separado das tags."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pieces: list[tuple[bool, str]] = []  # (é_texto, conteúdo)

    def handle_starttag(self, tag, attrs):
        self.pieces.append((False, self.get_starttag_text()))

    def handle_startendtag(self, tag, attrs):
        self.pieces.append((False, self.get_starttag_text()))

    def handle_endtag(self, tag):
        self.pieces.append((False, f"</{tag}>"))

    def handle_data(self, data):
        self.pieces.append((True, data))

    def handle_comment(self, data):
        self.pieces.append((False, f"<!--{data}-->"))

    def handle_decl(self, decl):
        self.pieces.append((False, f"<!{decl}>"))


def highlight_html(rendered_html: str, variants: list[VariantEntry], seen_term_ids: set[int] | None = None) -> str:
    """`seen_term_ids` controla "primeira ocorrência" (PLANO.md: "só a
    primeira ocorrência por bloco"). Passe um `set()` novo a cada bloco
    -- é o padrão --, ou compartilhe entre chamadas se quiser "primeira
    ocorrência por página inteira" em vez de por bloco. O conjunto é
    alterado in-place (o chamador pode inspecionar depois se quiser)."""
    if seen_term_ids is None:
        seen_term_ids = set()
    if not variants:
        return rendered_html

    walker = _TextNodeWalker()
    walker.feed(rendered_html)
    walker.close()

    saida = []
    for eh_texto, conteudo in walker.pieces:
        if not eh_texto:
            saida.append(conteudo)
            continue
        saida.append(_highlight_text_piece(conteudo, variants, seen_term_ids))
    return "".join(saida)


def _highlight_text_piece(texto: str, variants: list[VariantEntry], seen_term_ids: set[int]) -> str:
    matches = find_matches(texto, variants)
    if not matches:
        return html.escape(texto)

    partes = []
    cursor = 0
    for m in matches:
        partes.append(html.escape(texto[cursor : m.start]))
        palavra = html.escape(texto[m.start : m.end])
        if m.term_id in seen_term_ids:
            partes.append(palavra)  # não é a primeira ocorrência -- vira texto normal
        else:
            partes.append(f'<span class="glossary-term" data-term-id="{m.term_id}">{palavra}</span>')
            seen_term_ids.add(m.term_id)
        cursor = m.end
    partes.append(html.escape(texto[cursor:]))
    return "".join(partes)
