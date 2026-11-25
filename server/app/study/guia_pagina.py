"""Página do guia (`/lessons/{id}/guia`) no layout do guia interativo:
barra no topo, índice lateral, trilha "onde estou", cada tópico num
cartão numerado (1.1, 1.1.1), mapa mental da árvore de conhecimento,
busca e "estudado" por tópico.

Vale para todo guia estruturado -- aula normal, consolidação e guia
focado. Só muda a forma: o texto de cada tópico sai do mesmo
renderizador de sempre (markdown_render.py, com os rótulos Lei/Definição/
Exemplo/... em bloco), todo aberto, sem "ver mais" nem resumo. O que a
página tinha (player da narração, ouvir por seção, editar seção,
sumário com correção, índice, foco, trechos incompletos) continua no
template.

Numeração pela posição (ai/guia_numeracao.py), só na tela: o guia
gravado não muda. Tópicos, índice lateral e mapa vêm do gerador do
guia interativo (study/guia_interativo.py), com duas diferenças no mapa:
nenhum nó da árvore fica de fora (nó de 1º nível sem capítulo
correspondente vira cartão sem número) e nó só aponta para um tópico com
alguma palavra em comum -- sem a skill para corrigir, um "ir até o
conteúdo" no lugar errado engana mais do que ajuda. Sem palavra em
comum na seção do cartão, procura no guia inteiro.
"""

from __future__ import annotations

import html

from ..ai.guia_numeracao import norm_titulo
from ..markdown_render import render_markdown
from .guia_interativo import Pagina, chap, inline, tid_css, toks


# Além das palavras comuns do gerador (guia_interativo.STOP): sozinhas
# não dizem de que assunto se trata ("Não furtarás" x "Não levantar
# falsas testemunhas").
_GENERICAS = set(
    "nao sim ou nem mais menos entre sobre quando ja tambem ser ter ha pelo pela pelos pelas "
    "este esta esse essa isso isto aquele aquela sao foi era tem todo toda todos todas outro outra "
    "qual quais muito pouco cada".split()
)


def _toks(s: str) -> set[str]:
    return toks(s) - _GENERICAS


class _Guia(Pagina):
    def match(self, label: str, pid: str | None, ch: str | None) -> str | None:
        """Primeiro dentro da seção do cartão; sem nada lá, no guia
        inteiro -- no guia de uma aula a árvore não segue a divisão em
        seções."""
        achado = self._match(label, pid, ch)
        if achado is None and ch is not None:
            achado = self._match(label, pid, None)
        return achado

    def _match(self, label: str, pid: str | None, ch: str | None) -> str | None:
        lt = _toks(label.split(" — ")[0])
        if not lt:
            return None
        best, bs = None, float("-inf")
        for c in self.ORDER:
            if ch is not None and chap(c) != ch:
                continue
            comuns = len(lt & _toks(self.T[c]["title"]))
            if not comuns:
                continue
            sc = comuns / len(lt)
            if pid and c.startswith(pid + "."):
                sc += 0.35
            elif pid and c == pid:
                sc -= 0.2
            sc -= 0.01 * c.count(".")
            if sc > bs:
                best, bs = c, sc
        return best

    def mnode(self, nd: dict, pid: str | None, ch: str | None, depth: int) -> str:
        h = super().mnode(nd, pid, ch, depth)
        if nd.get("sem_assunto"):
            h = h.replace('<li class="', '<li class="sem-assunto ', 1)
        return h

    def build_map(self) -> str:
        tiles, panels = [], []
        usados: set[str] = set()
        for i, nd in enumerate(self.arvore):
            ch = self.chapter_for(i, nd["rotulo"], usados)
            if ch is not None:
                usados.add(ch)
            chave = ch or f"a{i + 1}"
            nome, _, compl = nd["rotulo"].partition(" — ")
            num = f'<span class="mnum">{ch or "◆"}</span>'
            data_ch = f' data-ch="{ch}"' if ch else ""
            sem = " sem-assunto" if nd.get("sem_assunto") else ""
            prog = '<span class="cpb"><i></i></span><span class="cpt"></span>' if ch else ""
            tiles.append(
                f'<button type="button" class="mtile{sem}" data-mch="{chave}"{data_ch} aria-expanded="false">'
                f'<span class="mtop">{num}<span class="tt">{inline(nome, False)}</span></span>{prog}</button>'
            )
            items = "".join(self.mnode(c, ch, ch, 1) for c in nd.get("filhos") or [])
            compl_html = f'<span class="mmd">{inline(compl)}</span>' if compl else ""
            ir = (
                f'<a class="mgo mgoc" href="#{tid_css(ch)}" data-go="{ch}">ir até a seção <span aria-hidden="true">→</span></a>'
                if ch
                else ""
            )
            cpt = '<span class="cpt"></span>' if ch else ""
            head = (
                f'<div class="mhd"{data_ch}>{num}<div class="mhx"><b>{inline(nome, False)}</b>{compl_html}'
                f"{cpt}</div>{ir}</div>"
            )
            tree = f'<ul class="mtree">{items}</ul>' if items else ""
            panels.append(f'<div class="mbr" data-mbr="{chave}" hidden>{head}{tree}</div>')
        if not tiles:
            return ""
        return '<div class="mgrid">' + "".join(tiles) + "".join(panels) + "</div>"


def _topico(t: dict, secao, marcados: frozenset[str], audio_ok: bool, eh_admin: bool) -> str:
    tid, lv = t["id"], t["level"]
    foco = norm_titulo(t["title"]) in marcados
    selo = '<span class="selo-foco">★ foco</span>' if foco else ""
    audio = ""
    if lv == 2 and audio_ok and secao.audio_start_s is not None:
        audio = (
            f' data-audio-start="{secao.audio_start_s}" data-audio-end="{secao.audio_end_s}"'
            f' data-audio-titulo="{html.escape(secao.titulo, quote=True)}"'
        )
    o = [f'<article class="topic lv{lv}" id="{tid_css(tid)}" data-id="{tid}">']
    o.append(f'<span class="gp-anc" id="secao-{tid.replace(".", "-")}"></span>')
    o.append('<header class="th">')
    o.append(f'<h{lv} class="tt sb"{audio}><span class="num">{tid}</span> {inline(t["title"], False)}{selo}</h{lv}>')
    o.append(f'<label class="chk"><input type="checkbox" data-id="{tid}"><span>estudado</span></label></header>')
    if lv == 2:
        botoes = []
        if audio:
            botoes.append('<button type="button" class="gp-btn guia-ouvir-secao">▸ ouvir esta seção</button>')
        if eh_admin:
            botoes.append(f'<button type="button" class="gp-btn guia-editar-secao" data-secao-id="{secao.id}">editar seção</button>')
        if botoes:
            o.append('<div class="gp-acoes">' + "".join(botoes) + "</div>")
        if eh_admin:
            o.append(
                f'<textarea class="guia-secao-fonte" data-secao-id="{secao.id}" hidden>{html.escape(secao.corpo)}</textarea>'
            )
    corpo = "\n".join(t["body"]).strip()
    if corpo:
        o.append(f'<div class="gp-md sb">{render_markdown(corpo)}</div>')
    o.append("</article>")
    return "".join(o)


def montar(
    secoes: list,
    arvore: list[dict],
    *,
    marcados: frozenset[str] = frozenset(),
    audio_ok: bool = False,
    eh_admin: bool = False,
) -> dict:
    """`secoes`: as `GuiaSecao` da aula, em ordem; `arvore`: a árvore já
    anotada (assuntos.annotate_arvore_checklist, com `sem_assunto`)."""
    p = _Guia([(s.titulo, s.corpo) for s in secoes], arvore, {})
    p.disp_id = None  # sem índice de artigos nesta página
    p.disp_list = None
    mapa = p.build_map()
    out = []
    cs = p.chapters
    for k, c in enumerate(cs):
        secao = secoes[int(c["id"]) - 1]
        tops = "".join(_topico(t, secao, marcados, audio_ok, eh_admin) for t in c["topics"])
        ant = cs[k - 1] if k > 0 else None
        prox = cs[k + 1] if k + 1 < len(cs) else None
        pn = '<nav class="chnav">'
        pn += (
            f'<a href="#{tid_css(ant["id"])}" data-go="{ant["id"]}">← {ant["id"]}. {inline(ant["title"], False)}</a>'
            if ant
            else "<span></span>"
        )
        pn += (
            f'<a href="#{tid_css(prox["id"])}" data-go="{prox["id"]}">{prox["id"]}. {inline(prox["title"], False)} →</a>'
            if prox
            else '<a href="#topo" data-go="topo">↑ topo</a>'
        )
        pn += "</nav>"
        out.append(
            f'<section class="chap" data-sec="{c["id"]}"><div class="chprog" data-ch="{c["id"]}"><span class="cpb"><i style="width:0%"></i></span>'
            f'<span class="cpt"></span></div>{tops}{pn}</section>'
        )
    return {
        "total": len(p.topics),
        "mapa_html": mapa,
        "nav_html": p.nav_html(),
        "secoes_html": "".join(out),
    }
