"""Guia interativo (RUNBOOK.md, "Guia interativo"): pacote e colar da skill
/guia-interativo, que escreve o que a página interativa não tira sozinha
do guia -- resumos de 1-2 linhas dos exemplos, visuais, seções que ficam
de fora, correções do mapa mental e do índice de artigos. A página é
montada por study/guia_interativo.py a cada request, do guia gravado;
isto só grava o acréscimo em `GuiaInterativo` (uma linha por aula,
substituída por inteiro a cada envio).

Só consolidação e guia focado (decisão do usuário). Só leitura do guia:
nada aqui muda `GuiaSecao`, a numeração ou o pacote da consolidação.

`INSTRUCTIONS` é a fonte única das regras; a skill só orquestra.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import GuiaInterativo, GuiaSecao, Lesson
from ..study import guia_interativo as gi
from .guia_numeracao import norm_titulo
from .pipeline import ProcessingError

INSTRUCTIONS = """\
# Guia interativo — o que a página não tira sozinha do guia

A página interativa deste guia já existe e é montada **por código** a cada
abertura, direto do guia gravado: título, definições, atenções, citações e
tabelas na frente; o texto integral de cada tópico em "ver texto
completo"; perguntas de aluno escondidas; mapa mental a partir da árvore
de conhecimento; índice de artigos a partir da seção "Dispositivos
legais"; busca e progresso. **O texto do guia entra literal e você não o
reescreve.**

Você devolve **só o acréscimo**, num JSON (formato no fim):

1. **Resumos dos exemplos** (`exemplos`). Cada exemplo narrado pelo
   professor aparece na frente como resumo de 1–2 linhas, e o caso
   completo, literal, fica em "ver o caso completo". Ex.: "Carnaval de
   2005: adultério cometido antes da lei que o revogou → abolitio criminis
   retroage". O resumo leva o selo "resumo" na página.
   - **Nada novo:** nenhum fato, nome, número, artigo ou conclusão que
     não esteja nos blocos indicados. Pode condensar; não pode mudar o
     sentido. Confira cada número e cada artigo contra o bloco ("art. 7º,
     I, alínea "a", CP"; "sem pena de caráter perpétuo").
   - `de` e `ate` são os hashes (entre colchetes no pacote) do primeiro e
     do último bloco do caso, no mesmo tópico, em ordem. Um caso costuma
     ser o bloco `ex` e os blocos `plain` ou listas que o continuam.
     Casos do mesmo tópico não se sobrepõem.
   - Uma linha só, sem quebra; até ~300 caracteres. Negrito (`**x**`) só
     para termo que está no bloco.
2. **Visuais** (`visuais`), no máximo um por tópico, só onde um visual
   ajuda a entender ou memorizar mais que o texto. Escolha o formato pelo
   conteúdo: árvore para classificação (gênero → espécie), colunas para
   comparar, linha do tempo para sucessão, fluxograma para roteiro de
   decisão, checklist para requisitos cumulativos, passo a passo para
   método de cálculo, quadro com selo ✔/✘ para regra que aplica ou não.
   Se nenhum visual funciona, deixe o texto — não force.
   - **Conteúdo só do guia**, deste capítulo (o tópico do visual e os
     que ele resume).
     Nada deduzido, completado ou "aplicando a regra": se o guia cita seis
     meses, o visual não lista doze. O visual leva o selo "resumo".
   - **HTML/CSS só**, sem SVG, sem script, sem estilo inline, sem link.
     Tags: div span p ul ol li b i em strong small br table thead tbody
     tr th td. Atributos: class, data-label, role, aria-label,
     aria-hidden. O servidor recusa o visual que tiver outra coisa.
   - Comece com `<div class="vis"><div class="vt">Título do visual</div>`
     e use as classes da página:
     `vnote` (nota) · `small` · `tree` (árvore em ul/li aninhados) ·
     `mini` (lista miúda) · `cols c2|c3` (+ `tight`, `quad`) com `card`
     (`ch` = cabeçalho; `okc`/`noc` = borda verde/vermelha; `ctr`) ·
     `big` · `tag` · `pron` · `anat` com `part p1|p2`, `pl`, `pq` ·
     `roman` (spans; `off`) · `nest` com `n1..n4` e `nl` · `flow` com
     `step` (`hl` = destaque; `sno` = número) · `seq` com `sq`/`sn` ·
     `formula` com `fx` (`rl`/`an`) e `op` · `tl` com `tlr back|dot|mid|fwd`,
     `tlk`, `tlv` (linha do tempo) · `trap` (pegadinha; `trap no`) ·
     `checklist` (li; `etc`) · `fc` com `fq` (pergunta), `fb`, `fy` (sim),
     `fn` (não), `fl` (rótulo) · `calc` · `method` com `mc`, `mh`, `mv`,
     `mx` · `terr2`, `tz`, `tground` (blocos de território) ·
     `seal ok|no|cond` (selo "✔ PODE" / "✘ NÃO PODE" — sempre ícone +
     texto, nunca só cor) · `art` (etiqueta de artigo) · `tbl` (tabela;
     ponha `data-label` em cada `td`, que no celular vira cartão).
   - Tabela do guia que o visual substitui: ponha o tópico em
     `esconder_tabelas` (a tabela continua no texto completo).
3. **Seções que ficam de fora** (`excluir`): títulos `##` (como estão no
   pacote, sem número) de seções que não são matéria para estudar —
   orientações de estudo, avisos de prova, recados de calendário. Saem da
   página inteira: mapa, busca, progresso e índice. A numeração das
   outras não muda. Na dúvida, não exclua.
4. **Mapa mental** (`mapa`): a árvore abaixo traz, para cada nó, o tópico
   que o código achou (`??` = nenhum). Corrija os errados e os ambíguos
   com `{"no": "<rótulo exato do nó>", "topico": "<número>"}`. Cada nó
   deve apontar para o tópico que trata dele.
5. **Índice de artigos** (`artigos`, `artigos_remover`), só se o guia tem
   a seção "Dispositivos legais": cada entrada traz o regex que o código
   gerou e os tópicos onde ele acha o artigo. Corrija o regex que acha
   demais ou de menos (`\\b` no fim: `art\\. 28\\b`, senão casa 288), e
   limite a capítulos (`capitulos`) quando o mesmo número vale para
   outra lei. `regex: null` = entrada sem links. Tire (`artigos_remover`)
   as entradas que só vêm de seção excluída.
6. **Mostrar tudo** (`mostrar_tudo`): tópicos curtos em que o texto todo
   é o conteúdo (cartões simples), e nada deve ficar escondido.

Reenviar substitui tudo: devolva sempre o JSON completo (a "Resposta
atual", no fim do pacote, é o ponto de partida quando houver).

## Formato da resposta

Só o JSON, sem comentário:

```json
{
  "excluir": ["Orientações de estudo e avisos de prova"],
  "mostrar_tudo": ["8.1"],
  "esconder_tabelas": ["6.6.4.6"],
  "exemplos": [{"topico": "1.1.2", "de": "a1b2c3d4e5", "ate": "a1b2c3d4e5", "resumo": "..."}],
  "visuais": [{"topico": "1", "html": "<div class=\\"vis\\"><div class=\\"vt\\">...</div>...</div>"}],
  "mapa": [{"no": "Autorização da União por lei complementar", "topico": "1.1.2"}],
  "artigos": [{"entrada": "Código Penal > art. 7º, CP", "regex": "[Aa]rt\\\\.\\\\s*7º", "capitulos": ["6"]}],
  "artigos_remover": ["Código Penal > arts. 1º a 5º do CP"]
}
```

A resposta do servidor lista o que foi recusado (com o motivo), os termos
em negrito dos resumos e visuais que não aparecem no tópico
(`externos` — confira cada um), o mapa e o índice de artigos finais.
"""


def _lesson_ok(session: Session, lesson: Lesson) -> list[tuple[str, str]]:
    if lesson.tipo != "consolidacao":
        raise ProcessingError("guia interativo só existe para consolidação e guia focado")
    secoes = session.scalars(
        select(GuiaSecao).where(GuiaSecao.lesson_id == lesson.id).order_by(GuiaSecao.ordem)
    ).all()
    if not secoes:
        raise ProcessingError("a consolidação ainda não tem guia (sem seções)")
    return [(s.titulo, s.corpo) for s in secoes]


def conteudo_atual(session: Session, lesson: Lesson) -> str | None:
    row = session.scalar(select(GuiaInterativo).where(GuiaInterativo.lesson_id == lesson.id))
    return row.conteudo_json if row else None


def _texto_bloco_pacote(b: dict) -> str:
    if b["type"] == "list":
        linhas: list[str] = []

        def walk(lst: dict, d: int) -> None:
            for it in lst["items"]:
                linhas.append("    " * d + "- " + it["text"])
                for c in it["children"]:
                    walk(c, d + 1)

        walk(b["data"], 0)
        return "\n" + "\n".join(linhas)
    if b["type"] == "table":
        rows = [b["data"]["head"]] + b["data"]["rows"]
        return "\n" + "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return b["text"]


def _para_skill(conteudo: dict) -> dict:
    """Formato gravado -> formato da resposta (para "Resposta atual")."""
    def tp(it: dict) -> str:
        return it["n"]

    return {
        "excluir": conteudo.get("excluir_titulos") or [],
        "mostrar_tudo": [tp(x) for x in conteudo.get("mostrar_tudo") or []],
        "esconder_tabelas": [tp(x) for x in conteudo.get("esconder_tabelas") or []],
        "exemplos": [
            {"topico": tp(x), "de": x["de"], "ate": x["ate"], "resumo": x["resumo"]}
            for x in conteudo.get("exemplos") or []
        ],
        "visuais": [{"topico": tp(x), "html": x["html"]} for x in conteudo.get("visuais") or []],
        "mapa": [{"no": x["no"], "topico": tp(x)} for x in conteudo.get("mapa") or []],
        "artigos": conteudo.get("artigos") or [],
        "artigos_remover": conteudo.get("artigos_remover") or [],
    }


def build_pacote(session: Session, lesson: Lesson) -> str:
    secoes = _lesson_ok(session, lesson)
    atual = conteudo_atual(session, lesson)
    pag = gi.Pagina(secoes, json.loads(lesson.guia_arvore_json or "[]"), json.loads(atual or "{}"))
    pag.build()
    todos = gi.parse_topics(secoes)

    out = [INSTRUCTIONS, f"\n# Guia: {lesson.guia_titulo or lesson.titulo} (aula {lesson.id})\n"]
    if lesson.focado:
        out.append(
            "Guia focado. O bloco \"Foco deste guia\" fica no topo da página, fora dos tópicos, e não é seu.\n"
        )

    out.append("## Árvore de conhecimento (nó → tópico achado)\n")
    if pag.tree_map:
        out.extend(f"{'    ' * d}- [{mid or '??'}] {rot}" for d, rot, mid in pag.tree_map)
    else:
        out.append("(o guia não tem árvore)")

    out.append("\n## Índice de artigos (entrada :: regex :: tópicos)\n")
    if pag.art_links:
        for path, lk in pag.art_links.items():
            out.append(f"- {path} :: {pag.art_rx.get(path)} :: {' '.join(lk) or '—'}")
    else:
        out.append("(o guia não tem a seção \"Dispositivos legais\")")

    out.append("\n## Tópicos (blocos: [hash tipo] texto)\n")
    for t in todos:
        out.append(f"\n### T {t['id']} {t['title']}\n")
        for b in t["blocks"]:
            tipo = b["type"] if b["type"] != "p" else b["kind"]
            out.append(f"[{gi.bloco_hash(b)} {tipo}] {_texto_bloco_pacote(b)}\n")

    if atual:
        out.append("\n## Resposta atual\n")
        out.append("```json\n" + json.dumps(_para_skill(json.loads(atual)), ensure_ascii=False, indent=1) + "\n```")
    return "\n".join(out) + "\n"


def _parse_json(texto: str) -> dict:
    t = texto.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        d = json.loads(t)
    except json.JSONDecodeError as exc:
        raise ProcessingError(f"resposta não é JSON válido: {exc}") from exc
    if not isinstance(d, dict):
        raise ProcessingError("a resposta tem que ser um objeto JSON")
    return d


def _negritos_resumo(s: str) -> list[str]:
    return [x.strip() for x in re.findall(r"\*\*(.+?)\*\*", s) if x.strip()]


def _negritos_html(h: str) -> list[str]:
    return [
        re.sub(r"<[^>]+>", "", x).strip()
        for x in re.findall(r"<(?:b|strong)>(.*?)</(?:b|strong)>", h, re.S)
        if re.sub(r"<[^>]+>", "", x).strip()
    ]


def _cabe(termo: str, texto_norm: str) -> bool:
    return " ".join(gi.norm(termo)) in texto_norm


def aplicar(session: Session, lesson: Lesson, resposta: str) -> dict:
    secoes = _lesson_ok(session, lesson)
    d = _parse_json(resposta)
    arvore = json.loads(lesson.guia_arvore_json or "[]")

    todos = gi.parse_topics(secoes)
    caps = {norm_titulo(t["title"]): t for t in todos if t["level"] == 2}
    rejeitados: list[dict] = []
    externos: list[dict] = []

    # seções de fora
    excluir, excluir_titulos, caps_fora = [], [], set()
    for titulo in d.get("excluir") or []:
        k = norm_titulo(str(titulo))
        if k not in caps:
            rejeitados.append({"item": {"excluir": titulo}, "motivo": "não há seção ## com esse título"})
            continue
        excluir.append(k)
        excluir_titulos.append(caps[k]["title"])
        caps_fora.add(caps[k]["id"])

    T = {t["id"]: t for t in todos if gi.chap(t["id"]) not in caps_fora}

    def cap_texto(tid: str) -> str:
        ch = gi.chap(tid)
        return " ".join(" ".join(gi.norm(gi.topico_texto(t))) for i, t in T.items() if gi.chap(i) == ch)

    def chave(item: dict, campo: str = "topico") -> dict | None:
        n = str(item.get(campo, "")).strip().rstrip(".")
        if n not in T:
            rejeitados.append({"item": item, "motivo": f"tópico {n or '(vazio)'} não existe (ou está numa seção excluída)"})
            return None
        return {"n": n, "t": norm_titulo(T[n]["title"])}

    def lista_topicos(nome: str) -> list[dict]:
        out = []
        for n in d.get(nome) or []:
            k = chave({"topico": n})
            if k:
                out.append(k)
        return out

    mostrar_tudo = lista_topicos("mostrar_tudo")
    esconder_tabelas = lista_topicos("esconder_tabelas")

    exemplos: list[dict] = []
    faixas: dict[str, list[tuple[int, int]]] = {}
    for it in d.get("exemplos") or []:
        k = chave(it)
        if not k:
            continue
        resumo = str(it.get("resumo") or "").strip()
        if not resumo or "\n" in resumo:
            rejeitados.append({"item": it, "motivo": "resumo vazio ou com quebra de linha"})
            continue
        hs = [gi.bloco_hash(b) for b in T[k["n"]]["blocks"]]
        de, ate = str(it.get("de", "")), str(it.get("ate", ""))
        if de not in hs or ate not in hs[hs.index(de) :]:
            rejeitados.append({"item": it, "motivo": "de/ate não são blocos deste tópico, em ordem"})
            continue
        s = hs.index(de)
        e = s + hs[s:].index(ate)
        if any(not (e < s2 or s > e2) for s2, e2 in faixas.get(k["n"], [])):
            rejeitados.append({"item": it, "motivo": "sobrepõe outro resumo do mesmo tópico"})
            continue
        faixas.setdefault(k["n"], []).append((s, e))
        exemplos.append({**k, "de": de, "ate": ate, "resumo": resumo})
        txt = " ".join(gi.norm(" ".join(gi.bloco_texto(b) for b in T[k["n"]]["blocks"][s : e + 1])))
        for termo in _negritos_resumo(resumo):
            if not _cabe(termo, txt):
                externos.append({"topico": k["n"], "onde": "resumo", "termo": termo})

    visuais: list[dict] = []
    com_visual: set[str] = set()
    for it in d.get("visuais") or []:
        k = chave(it)
        if not k:
            continue
        if k["n"] in com_visual:
            rejeitados.append({"item": {"topico": k["n"]}, "motivo": "mais de um visual no mesmo tópico"})
            continue
        h = str(it.get("html") or "").strip()
        limpo, erros = gi.sanear_visual(h)
        if erros:
            rejeitados.append({"item": {"topico": k["n"]}, "motivo": "; ".join(sorted(set(erros)))})
            continue
        if not limpo.startswith('<div class="vis">'):
            rejeitados.append({"item": {"topico": k["n"]}, "motivo": 'o visual tem que começar com <div class="vis">'})
            continue
        com_visual.add(k["n"])
        visuais.append({**k, "html": limpo})
        txt = cap_texto(k["n"])
        for termo in _negritos_html(limpo):
            if not _cabe(termo, txt):
                externos.append({"topico": k["n"], "onde": "visual", "termo": termo})

    rotulos: set[str] = set()

    def walk(nos: list[dict]) -> None:
        for no in nos:
            rotulos.add(no["rotulo"])
            walk(no.get("filhos") or [])

    walk(arvore)
    mapa = []
    for it in d.get("mapa") or []:
        if it.get("no") not in rotulos:
            rejeitados.append({"item": it, "motivo": "nó não existe na árvore (o rótulo tem que ser exato)"})
            continue
        k = chave(it)
        if k:
            mapa.append({"no": it["no"], **k})

    # índice de artigos: caminhos que existem
    base = gi.Pagina(secoes, arvore, {"excluir": excluir})
    base.build()
    caminhos = set(base.art_links)
    artigos, artigos_remover = [], []
    for it in d.get("artigos") or []:
        entrada = str(it.get("entrada") or "")
        if entrada not in caminhos:
            rejeitados.append({"item": it, "motivo": "entrada não existe no índice de artigos"})
            continue
        rx = it.get("regex")
        if rx is not None:
            try:
                re.compile(rx)
            except re.error as exc:
                rejeitados.append({"item": it, "motivo": f"regex inválido: {exc}"})
                continue
        chs = [str(c) for c in it.get("capitulos") or []] or None
        artigos.append({"entrada": entrada, "regex": rx, "capitulos": chs})
    for entrada in d.get("artigos_remover") or []:
        if entrada not in caminhos:
            rejeitados.append({"item": {"artigos_remover": entrada}, "motivo": "entrada não existe no índice de artigos"})
            continue
        artigos_remover.append(entrada)

    conteudo = {
        "excluir": excluir,
        "excluir_titulos": excluir_titulos,
        "mostrar_tudo": mostrar_tudo,
        "esconder_tabelas": esconder_tabelas,
        "exemplos": exemplos,
        "visuais": visuais,
        "mapa": mapa,
        "artigos": artigos,
        "artigos_remover": artigos_remover,
    }
    conteudo_json = json.dumps(conteudo, ensure_ascii=False)
    row = session.scalar(select(GuiaInterativo).where(GuiaInterativo.lesson_id == lesson.id))
    if row is None:
        row = GuiaInterativo(lesson_id=lesson.id, conteudo_json=conteudo_json)
        session.add(row)
    else:
        row.conteudo_json = conteudo_json
        row.gerado_em = datetime.now(timezone.utc)
    session.commit()

    final = gi.Pagina(secoes, arvore, conteudo).build()
    return {
        "aceitos": {
            "excluir": len(excluir),
            "mostrar_tudo": len(mostrar_tudo),
            "esconder_tabelas": len(esconder_tabelas),
            "exemplos": len(exemplos),
            "visuais": len(visuais),
            "mapa": len(mapa),
            "artigos": len(artigos),
            "artigos_remover": len(artigos_remover),
        },
        "rejeitados": rejeitados,
        "externos": externos,
        "excluidas": excluir_titulos,
        "topicos": final["total"],
        "mapa": [f"{'  ' * dd}{mid or '??'}  <= {rot}" for dd, rot, mid in final["tree_map"]],
        "sem_topico_no_mapa": [rot for _, rot, mid in final["tree_map"] if not mid],
        "artigos_links": final["art_links"],
        "ignorados": final["ignorados"],
    }
