"""Guia interativo: o guia de uma consolidação (ou guia focado) como
página de estudo -- resumo na frente, texto completo escondido, mapa
mental, trilha "onde estou", progresso, busca e índice de artigos.

Porta do gerador feito à parte para a consolidação de Penal (pacote
"resumo-penal", `gerador/mdparse.py` + `build.py`). Aqui ele lê o guia
gravado (`GuiaSecao` + `Lesson.guia_arvore_json`) a cada request, então
a página nunca fica desatualizada.

Duas camadas:
- **código** (este módulo, sempre): tópicos e blocos, o que fica
  visível, "ver texto completo", perguntas de aluno, ícone de inaudível,
  etiqueta de artigo, mapa mental com correspondência automática nó ->
  tópico, índice de artigos com regex derivado da própria entrada;
- **skill** `/guia-interativo` (opcional, `GuiaInterativo.conteudo_json`,
  regras em ai/guia_interativo.py): resumos dos exemplos, visuais,
  seções que ficam de fora, correções do mapa e dos artigos. Cada item
  fica preso ao tópico (número + título normalizado) e ao hash do texto
  do bloco (`bloco_hash`) -- nunca à posição. Item cujo tópico ou bloco
  não existe mais simplesmente não entra (o texto literal continua lá) e
  a página avisa quantos ficaram de fora.

O texto do guia entra literal: só se converte a marcação (negrito,
itálico, listas, tabelas) e o rótulo do começo do parágrafo vira selo.
Resumos e visuais da skill são os únicos textos que não são do guia, e
levam o selo "resumo".

Só leitura: não muda o guia, a numeração (ai/guia_numeracao.py) nem o
renderizador do guia (markdown_render.py).
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from html.parser import HTMLParser

from ..ai.guia_numeracao import norm_titulo, numerar_consolidado

# ---------------------------------------------------------------- parse

HEAD_RE = re.compile(r"^(#{2,6}) (\d+(?:\.\d+)*)\.? (.*)$")
LIST_RE = re.compile(r"^( *)(-|\*|\d+\.) (.*)$")


def _rotulo_re(nome: str) -> re.Pattern:
    """`Nome:`, `**Nome:**` ou `**Nome**:` no começo do parágrafo -- as
    três formas que o renderizador do guia aceita (markdown_render.py)."""
    return re.compile(r"^(?:\*\*(?:" + nome + r")(?::\*\*|\*\*:)|(?:" + nome + r"):)[ \t]*")


# (tipo, padrão do rótulo, texto do selo -- None = o rótulo como está no
# guia); ordem importa ("Atenção da professora" antes de "Atenção").
ROTULOS = [
    ("def", _rotulo_re(r"Defini[çc][ãa]o"), "DEFINIÇÃO"),
    ("foco", _rotulo_re(r"Aten[çc][ãa]o d[oa] professora?"), None),
    ("aten", _rotulo_re(r"Aten[çc][ãa]o"), "ATENÇÃO"),
    # Sem negrito em volta, o complemento pode ter negrito dentro
    # ("Exemplo (o colombiano — **art. 7º, I, alínea "a", CP**):").
    ("ex", re.compile(r"^(?:\*\*Exemplo\b[^:*]{0,160}(?::\*\*|\*\*:)|Exemplo\b[^:]{0,160}:)[ \t]*"), "EXEMPLO"),
    # Também "Pergunta de aluno sobre…", sem dois-pontos (como o gerador
    # de referência).
    (
        "q",
        re.compile(
            r"^(?:\*\*(?:Pergunta de alun[oa]|Aluno)(?::\*\*|\*\*:)|(?:Pergunta de alun[oa]|Aluno):|Pergunta de alun[oa]\b)[ \t]*"
        ),
        None,
    ),
    ("lei", _rotulo_re(r"Lei"), "LEI"),
    ("mat", _rotulo_re(r"Material da aula"), "MATERIAL DA AULA"),
    ("dica", _rotulo_re(r"Dica d[oa] professora?"), "DICA DO PROFESSOR"),
]
_ROTULO_DE = {k: (rx, selo) for k, rx, selo in ROTULOS}


def classify(text: str) -> str:
    for kind, rx, _ in ROTULOS:
        if rx.match(text):
            return kind
    if re.fullmatch(r"\*\*[^*].*\*\*", text) and text.count("**") == 2:
        return "sub"
    return "plain"


def parse_list(lines: list[str]) -> dict:
    items: list[list] = []  # (recuo, marcador, texto)
    for ln in lines:
        m = LIST_RE.match(ln)
        if m:
            items.append([len(m.group(1)), m.group(2), m.group(3)])
        elif items:
            items[-1][2] += " " + ln.strip()

    def build(idx: int, indent: int):
        lst = {"ordered": items[idx][1] not in ("-", "*"), "items": []}
        i = idx
        while i < len(items):
            ind = items[i][0]
            if ind < indent:
                break
            if ind == indent:
                lst["items"].append({"text": items[i][2], "children": []})
                i += 1
            else:
                child, i = build(i, ind)
                if lst["items"]:
                    lst["items"][-1]["children"].append(child)
                else:
                    lst["items"].append({"text": "", "children": [child]})
        return lst, i

    lst, _ = build(0, items[0][0])
    return lst


def parse_table(lines: list[str]) -> dict:
    rows = []
    for ln in lines:
        ln = ln.strip()
        if re.match(r"^\|[-| :]+\|$", ln):
            continue
        rows.append([c.strip() for c in ln.strip("|").split("|")])
    return {"head": rows[0], "rows": rows[1:]}


def parse_blocks(body_lines: list[str]) -> list[dict]:
    blocks = []
    i, n = 0, len(body_lines)
    while i < n:
        ln = body_lines[i]
        if not ln.strip():
            i += 1
            continue
        if ln.lstrip().startswith("|"):
            buf = []
            while i < n and body_lines[i].lstrip().startswith("|"):
                buf.append(body_lines[i])
                i += 1
            blocks.append({"type": "table", "data": parse_table(buf)})
            continue
        if ln.startswith(">"):
            buf = []
            while i < n and body_lines[i].startswith(">"):
                buf.append(body_lines[i][1:].strip())
                i += 1
            text = " ".join(buf)
            kind = "mat" if "Material da aula" in text[:40] else "cit"
            blocks.append({"type": "p", "kind": kind, "text": text, "quote": True})
            continue
        if LIST_RE.match(ln):
            buf = []
            while i < n and body_lines[i].strip() and (LIST_RE.match(body_lines[i]) or body_lines[i].startswith("  ")):
                buf.append(body_lines[i])
                i += 1
            blocks.append({"type": "list", "data": parse_list(buf)})
            continue
        buf = []
        while (
            i < n
            and body_lines[i].strip()
            and not LIST_RE.match(body_lines[i])
            and not body_lines[i].lstrip().startswith("|")
            and not body_lines[i].startswith(">")
        ):
            buf.append(body_lines[i].strip())
            i += 1
        text = " ".join(buf)
        blocks.append({"type": "p", "kind": classify(text), "text": text})
    return blocks


def parse_topics(secoes: list[tuple[str, str]]) -> list[dict]:
    """`secoes` = [(titulo, corpo)] na ordem do guia. Numera como a tela
    do guia (ai/guia_numeracao.py) e quebra em tópicos pelos títulos."""
    lines: list[str] = []
    for s in numerar_consolidado(secoes, com_ancora=False):
        lines.append(f"## {s.numero}. {s.titulo}")
        lines.extend(s.corpo.split("\n"))
    topics: list[dict] = []
    cur = None
    for ln in lines:
        m = HEAD_RE.match(ln)
        if m:
            cur = {"id": m.group(2), "level": len(m.group(1)), "title": m.group(3).strip(), "body": []}
            topics.append(cur)
            continue
        if cur is not None:
            cur["body"].append(ln)
    for t in topics:
        t["blocks"] = parse_blocks(t["body"])
    return topics


# ---------------------------------------------------------------- identidade

def plain(text: str) -> str:
    return re.sub(r"\*+", "", text)


def bloco_texto(b: dict) -> str:
    """Texto do bloco sem rótulo, marcação nem espaço extra -- o que o
    hash identifica. Sem o rótulo, a passada de rótulos (/rotular-guia)
    não muda a identidade de um bloco."""
    if b["type"] == "list":
        partes: list[str] = []

        def walk(lst: dict) -> None:
            for it in lst["items"]:
                partes.append(it["text"])
                for c in it["children"]:
                    walk(c)

        walk(b["data"])
        t = "\n".join(partes)
    elif b["type"] == "table":
        t = "\n".join(" | ".join(r) for r in [b["data"]["head"]] + b["data"]["rows"])
    else:
        t = b["text"]
        if b["kind"] in _ROTULO_DE:
            m = _ROTULO_DE[b["kind"]][0].match(t)
            if m:
                t = t[m.end() :]
    return re.sub(r"\s+", " ", plain(t)).strip()


def bloco_hash(b: dict) -> str:
    return hashlib.sha1(bloco_texto(b).encode("utf-8")).hexdigest()[:10]


def topico_texto(t: dict) -> str:
    return plain(t["title"] + "\n" + "\n".join(t["body"]))


# ---------------------------------------------------------------- inline

INAUD = re.compile(r"\[[^\]]*?(?:inaud|incomplet|transcrição)[^\]]*\]")
ART = re.compile(
    r'\b(?:[Aa]rts?\.|[Aa]rtigos?)\s?\d+º?'
    r'(?:(?:,\s*|\s+e\s+|\s+a\s+)(?:\d+º?(?=[\s,.;)]|$)|[IVXL]+\b|§\s*\d+º|parágrafo único|alínea\s*"[a-e]"|inciso\s+[IVXL]+))*'
    r"(?:,?\s*(?:CP|CF)\b|\s+d[oa]\s+(?:CP\b|Código Penal|Código Civil|Constituição|Lei\s+[\d.]+/\d{4}(?:\s*\(Lei de Migração\))?|Lei de Migração)|\s+e\s+seguintes(?:\s+da\s+Lei\s+[\d.]+/\d{4}(?:\s*\(Lei de Migração\))?)?)?"
)


def inline(text: str, tag_art: bool = True) -> str:
    s = html.escape(text, quote=False)
    store: list[str] = []

    def keep(h: str) -> str:
        store.append(h)
        return f"\x00{len(store) - 1}\x00"

    s = INAUD.sub(
        lambda m: keep(
            '<span class="inaud" tabindex="0" role="note" aria-label="trecho incompleto ou inaudível na transcrição"'
            f' data-t="{m.group(0).replace(chr(34), "&quot;")}"></span>'
        ),
        s,
    )
    if tag_art:
        s = ART.sub(lambda m: keep(f'<span class="art">{m.group(0)}</span>'), s)
    s = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    for _ in range(3):
        s = re.sub(r"\x00(\d+)\x00", lambda m: store[int(m.group(1))], s)
    return s


def tid_css(i: str) -> str:
    return "t-" + i.replace(".", "-")


def chap(i: str) -> str:
    return i.split(".")[0]


# ---------------------------------------------------------------- blocos

ICONES = {
    "def": "ⓘ",
    "aten": "⚠&#xFE0E;",
    "foco": "⚠&#xFE0E;",
    "ex": "▶&#xFE0E;",
    "lei": "§",
    "mat": "❝",
    "dica": "★",
    "q": "?",
}


def strip_marker(b: dict) -> tuple[str, str, str]:
    """(texto sem o rótulo, complemento do rótulo, texto do selo)."""
    t, k = b["text"], b["kind"]
    rx, selo = _ROTULO_DE[k]
    m = rx.match(t)
    if not m:
        return t.strip(), "", selo or ""
    rot = plain(t[: m.end()]).strip().rstrip(":").strip()
    rest = t[m.end() :]
    extra = ""
    if k == "ex":
        bruto = t[: m.end()].strip()
        if bruto.startswith("**"):  # "**Exemplo X:**" / "**Exemplo X**:"
            bruto = bruto[2:].replace(":**", ":").replace("**:", ":")
        compl = bruto[len("Exemplo") :].strip().rstrip(":").strip()
        if compl:
            extra = f"<em>{inline(compl)}:</em> "
    if selo is None:
        selo = rot.upper()
    return rest.strip(), extra, selo


def render_list(lst: dict) -> str:
    tag = "ol" if lst["ordered"] else "ul"
    out = [f"<{tag}>"]
    for it in lst["items"]:
        out.append("<li>" + inline(it["text"]) + "".join(render_list(c) for c in it["children"]) + "</li>")
    out.append(f"</{tag}>")
    return "".join(out)


def render_table(tb: dict, sb: bool = True) -> str:
    head = tb["head"]
    out = [f'<div class="{"tbl sb" if sb else "tbl"}"><table><thead><tr>']
    for h in head:
        out.append(f"<th>{inline(h)}</th>")
    out.append("</tr></thead><tbody>")
    for r in tb["rows"]:
        out.append("<tr>")
        for j, c in enumerate(r):
            lab = html.escape(plain(head[j]) if j < len(head) else "")
            out.append(f'<td data-label="{lab}">{inline(c)}</td>')
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def render_block(b: dict, sb: bool = True) -> str:
    s = " sb" if sb else ""
    if b["type"] == "list":
        return f'<div class="blk lst{s}">{render_list(b["data"])}</div>'
    if b["type"] == "table":
        return render_table(b["data"], sb)
    k = b["kind"]
    if k == "sub":
        return f'<div class="blk sub{s}">{inline(b["text"])}</div>'
    if k == "cit":
        return f'<blockquote class="blk cit{s}">{inline(b["text"])}</blockquote>'
    if k == "plain":
        return f'<p class="blk{s}">{inline(b["text"])}</p>'
    text, extra, selo = strip_marker(b)
    return (
        f'<div class="blk box {k}{s}"><span class="badge"><span aria-hidden="true">{ICONES[k]}</span> {html.escape(selo)}</span> '
        f"{extra}{inline(text)}</div>"
    )


def ends_colon(b: dict) -> bool:
    return b["type"] == "p" and plain(b["text"]).rstrip().endswith(":")


VIS_KINDS = {"def", "aten", "foco", "lei", "mat", "dica", "cit"}


def analyze(t: dict, exr: list, tem_visual: bool, mostrar_tudo: bool, esconder_tabelas: bool):
    """Mesma regra do gerador de referência (build.py::analyze)."""
    B = t["blocks"]
    n = len(B)
    vis: set[int] = set()
    if mostrar_tudo:
        vis = set(range(n))
    else:
        for i, b in enumerate(B):
            if b["type"] == "p" and b["kind"] in VIS_KINDS:
                vis.add(i)
                if ends_colon(b) and i + 1 < n and B[i + 1]["type"] == "list":
                    vis.add(i + 1)
            if b["type"] == "table" and not esconder_tabelas:
                vis.add(i)
    exset: set[int] = set()
    for s, e, _ in exr:
        exset |= set(range(s, e + 1))
    qunits: list[list[int]] = []
    qset: set[int] = set()
    titled_q = t["title"].startswith("Pergunta de aluno")
    if titled_q:
        unit = [i for i in range(n) if i not in vis and i not in exset]
        if unit:
            qunits.append(unit)
            qset |= set(unit)
    else:
        i = 0
        while i < n:
            b = B[i]
            is_qsub = b["type"] == "p" and b["kind"] == "sub" and plain(b["text"]).startswith("Pergunta")
            if b["type"] == "p" and (b["kind"] == "q" or is_qsub) and i not in vis:
                unit = [i]
                j = i + 1
                if is_qsub and j < n and B[j].get("kind") == "q":
                    unit.append(j)
                    j += 1
                cnt = 0
                while (
                    j < n
                    and cnt < 4
                    and (B[j]["type"] == "list" or B[j].get("kind") == "plain")
                    and j not in vis
                    and j not in exset
                ):
                    unit.append(j)
                    j += 1
                    cnt += 1
                qunits.append(unit)
                qset |= set(unit)
                i = j
            else:
                i += 1
    for i, b in enumerate(B):
        if b["type"] == "p" and b["kind"] == "sub" and i not in qset:
            j = i + 1
            while j < n and not (B[j]["type"] == "p" and B[j]["kind"] == "sub"):
                if j in vis:
                    vis.add(i)
                    break
                j += 1
    if not vis and not exr and not tem_visual and not titled_q and n:
        k = 0
        while k < n and k in qset:
            k += 1
        if k < n:
            vis.add(k)
            if k + 1 < n and B[k + 1]["type"] == "list" and (k + 1) not in qset:
                vis.add(k + 1)
    return vis, exset, qunits, qset


def word_count(t: dict) -> int:
    return len(re.findall(r"\w+", " ".join(t["body"])))


# ---------------------------------------------------------------- visuais

VIS_TAGS = {
    "div", "span", "p", "ul", "ol", "li", "b", "i", "em", "strong", "small", "br",
    "table", "thead", "tbody", "tr", "th", "td",
}
VIS_ATTRS = {"class", "data-label", "role", "aria-label", "aria-hidden"}
_VOID = {"br"}


class _Saneador(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.erros: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VIS_TAGS:
            self.erros.append(f"tag não permitida: <{tag}>")
            return
        partes = [tag]
        for k, v in attrs:
            if k not in VIS_ATTRS:
                self.erros.append(f"atributo não permitido: {k}")
                continue
            partes.append(f'{k}="{html.escape(v or "", quote=True)}"')
        self.out.append("<" + " ".join(partes) + ">")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in VIS_TAGS and tag not in _VOID:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        self.out.append(html.escape(data, quote=False))

    def handle_comment(self, data):
        self.erros.append("comentário não permitido")

    def handle_decl(self, decl):
        self.erros.append("declaração não permitida")

    def handle_pi(self, data):
        self.erros.append("instrução não permitida")


def sanear_visual(h: str) -> tuple[str, list[str]]:
    """HTML do visual reescrito só com as tags/atributos permitidos. Os
    erros dizem o que foi recusado -- quem chama decide recusar o visual
    inteiro (o colar recusa; a renderização nunca vê erro, porque só
    grava visual já limpo)."""
    p = _Saneador()
    p.feed(h)
    p.close()
    return "".join(p.out), p.erros


# ---------------------------------------------------------------- mapa mental

def norm(s: str) -> list[str]:
    s = unicodedata.normalize("NFD", plain(s).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+", s)


STOP = set(
    "a o e de da do das dos em no na nos nas para por com sem que um uma ao aos as os se sua seu sob como "
    "lei penal art cp cf direito".split()
)


def toks(s: str) -> set[str]:
    return {w for w in norm(s) if w not in STOP and len(w) > 1}


def seal_for(label: str, desc: str) -> str:
    d = (desc or "").lower()
    rules = [
        ("não retroage" in d, "no", "✘ NÃO RETROAGE"),
        ("retroage sempre" in d, "ok", "✔ RETROAGE SEMPRE"),
        (re.search(r"\bretroage\b", d) is not None, "ok", "✔ RETROAGE"),
        ("sempre ultrativa" in d, "ok", "✔ SEMPRE ULTRATIVA"),
        ("não se aplica" in d, "no", "✘ NÃO SE APLICA"),
        ("não adotada" in d, "no", "✘ NÃO ADOTADA"),
        ("adotad" in d, "ok", "✔ ADOTADA"),
        ("não existe" in d, "no", "✘ NÃO EXISTE"),
        (re.search(r"\bnunca\b", d) is not None, "no", "✘ NUNCA"),
        (d.startswith("poderá"), "ok", "✔ PODE"),
        (not d and "não são território" in label.lower(), "no", "✘ NÃO É TERRITÓRIO"),
    ]
    for cond, cls, txt in rules:
        if cond:
            return f'<span class="seal {cls}">{txt}</span>'
    return ""


DROP_DESC = {"retroage", "não retroage", "retroage sempre", "sempre ultrativa", "não existe"}

DISPOSITIVOS = "dispositivos legais"


def key_of(text: str) -> str:
    return text.split(" — ")[0].replace("**", "").strip()


def auto_pattern(path: list[str], has_children: bool) -> str | None:
    """Regex de uma entrada do índice de artigos, derivado só do texto
    dela e das entradas acima (ex.: "art. 7º, CP" > "I" > 'alínea "a"').
    Grupo sem número ("Código Penal") não tem regex próprio. A skill pode
    trocar por um regex escrito à mão (`artigos`)."""
    key = re.sub(r"\s*\([^)]*\)", "", path[-1]).strip()

    def art_num(s: str) -> list[str]:
        m = re.search(r"\b(?:[Aa]rts?\.?|[Aa]rtigos?)\s*(.*)$", s)
        if not m:
            return []
        resto = re.split(r"\b(?:CP|CF|d[oa]s?)\b", m.group(1))[0]
        return re.findall(r"\d+", resto.split("§")[0])

    nums = art_num(key)
    if nums:
        if len(nums) == 1:
            return r"\b[Aa]rt(?:s?\.|igos?)\s*" + nums[0] + r"(?:º|°)?(?!\d)"
        return r"\b" + r"(?:º|°)?,?\s*(?:e\s+|a\s+)?".join(nums) + r"(?:º|°)?(?!\d)"
    art_i = next((i for i in range(len(path) - 2, -1, -1) if art_num(path[i])), None)
    if art_i is not None and len(art_num(path[art_i])) == 1:
        n = art_num(path[art_i])[0]
        rx = r"\b" + n + r"(?:º|°)?"
        for s in path[art_i + 1 :]:
            tok = re.escape(re.sub(r"\s*\([^)]*\)", "", s).strip()).replace(r"\ ", r"\s*")
            rx += r",?\s*(?:inciso\s+)?" + tok
        return rx + r"(?![\w])"
    if (has_children and not re.search(r"\d", key)) or not key:
        return None
    return re.escape(key).replace(r"\ ", r"\s+")


# ---------------------------------------------------------------- página

class Pagina:
    """Monta a página a partir do guia gravado. `extras` é o
    `GuiaInterativo.conteudo_json` já validado pelo colar (ou {})."""

    def __init__(self, secoes: list[tuple[str, str]], arvore: list[dict], extras: dict | None = None):
        ex = extras or {}
        self.ignorados: list[str] = []  # itens da skill que não bateram mais com o guia
        todos = parse_topics(secoes)
        caps_todos = [t for t in todos if t["level"] == 2]
        excluir = set(ex.get("excluir") or [])
        self.excluidos = [t["id"] for t in caps_todos if norm_titulo(t["title"]) in excluir]
        achados = {norm_titulo(t["title"]) for t in caps_todos}
        for x in excluir - achados:
            self.ignorados.append(f"seção a excluir não existe mais: {x}")
        self.topics = [t for t in todos if chap(t["id"]) not in self.excluidos]
        self.T = {t["id"]: t for t in self.topics}
        self.ORDER = [t["id"] for t in self.topics]
        self.chapters: list[dict] = []
        for t in self.topics:
            if t["level"] == 2:
                self.chapters.append({"id": t["id"], "title": t["title"], "topics": []})
            self.chapters[-1]["topics"].append(t)
        self.caps_todos = caps_todos
        self.arvore = arvore
        self.disp_id = next((c["id"] for c in self.chapters if " ".join(norm(c["title"])) == DISPOSITIVOS), None)
        self.disp_list = None
        if self.disp_id:
            lists = [b for b in self.T[self.disp_id]["blocks"] if b["type"] == "list"]
            self.disp_list = lists[0]["data"] if lists else None
        self.TP = {t["id"]: topico_texto(t) for t in self.topics if not self.disp_id or chap(t["id"]) != self.disp_id}
        self.tree_map: list[tuple[int, str, str | None]] = []
        self.art_links: dict[str, list[str]] = {}
        self.art_rx: dict[str, str | None] = {}
        self._resolver(ex)

    # ---- itens da skill -> tópicos atuais
    def achar(self, n: str | None, t: str | None) -> str | None:
        """Tópico pelo número, conferindo o título; se o número mudou, pelo
        título, desde que só um tópico tenha esse título."""
        if n in self.T and (t is None or norm_titulo(self.T[n]["title"]) == t):
            return n
        if t:
            cands = [i for i in self.ORDER if norm_titulo(self.T[i]["title"]) == t]
            if len(cands) == 1:
                return cands[0]
        return None

    def _resolver(self, ex: dict) -> None:
        self.EX: dict[str, list] = {}
        self.V: dict[str, str] = {}
        self.SHOW_ALL: set[str] = set()
        self.HIDE_TABLES: set[str] = set()
        self.TREE_OVERRIDE: dict[str, str] = {}
        self.ART_OVERRIDE: dict[str, tuple] = {}
        self.ART_REMOVE: set[str] = set(ex.get("artigos_remover") or [])

        def tid_de(item: dict, o_que: str) -> str | None:
            tid = self.achar(item.get("n"), item.get("t"))
            if tid is None:
                self.ignorados.append(f"{o_que}: tópico {item.get('n')} não existe mais")
            return tid

        for it in ex.get("exemplos") or []:
            tid = tid_de(it, "resumo de exemplo")
            if not tid:
                continue
            hs = [bloco_hash(b) for b in self.T[tid]["blocks"]]
            if it["de"] not in hs or it["ate"] not in hs[hs.index(it["de"]) :]:
                self.ignorados.append(f"resumo de exemplo em {tid}: o trecho mudou")
                continue
            s = hs.index(it["de"])
            e = s + hs[s:].index(it["ate"])
            if any(not (e < s2 or s > e2) for s2, e2, _ in self.EX.get(tid, [])):
                continue
            self.EX.setdefault(tid, []).append((s, e, it["resumo"]))
        for v in self.EX.values():
            v.sort()
        for it in ex.get("visuais") or []:
            tid = tid_de(it, "visual")
            if tid:
                self.V[tid] = it["html"]
        for chave, alvo in (("mostrar_tudo", self.SHOW_ALL), ("esconder_tabelas", self.HIDE_TABLES)):
            for it in ex.get(chave) or []:
                tid = tid_de(it, chave.replace("_", " "))
                if tid:
                    alvo.add(tid)
        for it in ex.get("mapa") or []:
            tid = tid_de(it, f"correção do mapa ({it.get('no')})")
            if tid:
                self.TREE_OVERRIDE[it["no"]] = tid
        for it in ex.get("artigos") or []:
            self.ART_OVERRIDE[it["entrada"]] = (it.get("regex"), set(it["capitulos"]) if it.get("capitulos") else None)

    # ---- tópicos
    def render_topic(self, t: dict) -> str:
        tid, B = t["id"], t["blocks"]
        exr = self.EX.get(tid, [])
        vis, exset, qunits, qset = analyze(t, exr, bool(self.V.get(tid)), tid in self.SHOW_ALL, tid in self.HIDE_TABLES)
        lv = t["level"]
        o = [f'<article class="topic lv{lv}" id="{tid_css(tid)}" data-id="{tid}">']
        o.append('<header class="th">')
        o.append(f'<h{lv} class="tt sb"><span class="num">{tid}</span> {inline(t["title"])}</h{lv}>')
        o.append(f'<label class="chk"><input type="checkbox" data-id="{tid}"><span>estudado</span></label></header>')
        body = []
        if self.V.get(tid):
            vh = self.V[tid].replace('class="vis"', 'class="vis sb"', 1)
            vh = vh.replace('<div class="vt">', '<div class="vt"><span class="rz">resumo</span> ', 1)
            body.append(vh)
        is_disp = tid == self.disp_id and self.disp_list is not None
        if is_disp:
            body.append(self.art_index_html)
        exstart = {s: (s, e, summ) for s, e, summ in exr}
        for i, b in enumerate(B):
            if i in exstart:
                s, e, summ = exstart[i]
                inner = "".join(render_block(B[k], sb=(k not in vis and k not in qset)) for k in range(s, e + 1))
                body.append(
                    '<div class="exs"><div class="exl"><span class="badge"><span aria-hidden="true">▶&#xFE0E;</span> EXEMPLO</span> '
                    f'<span class="rz">resumo</span> <span class="sb">{inline(summ)}</span></div>'
                    f'<details class="more"><summary>ver o caso completo</summary><div class="dbody">{inner}</div></details></div>'
                )
            if i in vis and not is_disp:
                body.append(render_block(b, sb=True))
        o.append('<div class="tb">' + "".join(body) + "</div>")
        if qunits and not body:
            o.append(
                '<p class="qnote">Este tópico é uma pergunta de aluno respondida pelo professor — abra “perguntas de aluno” abaixo.</p>'
            )
        if qunits:
            qhtml = "".join(
                '<div class="qu">' + "".join(render_block(B[k], sb=True) for k in u) + "</div>" for u in qunits
            )
            o.append(
                f'<details class="more qs"><summary>perguntas de aluno ({len(qunits)})</summary><div class="dbody">{qhtml}</div></details>'
            )
        if B:
            full = []
            for i, b in enumerate(B):
                if is_disp and b["type"] == "list" and b["data"] is self.disp_list:
                    full.append(f'<div class="blk lst">{render_list(self.filtered_disp)}</div>')
                    continue
                dup = (i in vis) or (i in qset) or (i in exset)
                full.append(render_block(b, sb=not dup))
            o.append(
                f'<details class="more full"><summary>ver texto completo <span class="wc">({word_count(t)} palavras)</span></summary>'
                f'<div class="dbody">{"".join(full)}</div></details>'
            )
        o.append("</article>")
        return "".join(o)

    # ---- índice de artigos
    def _filtrar(self, lst: dict, path: list[str]) -> dict:
        items = []
        for it in lst["items"]:
            p = path + [key_of(it["text"])]
            if " > ".join(p) in self.ART_REMOVE:
                continue
            items.append({"text": it["text"], "children": [self._filtrar(c, p) for c in it["children"]], "path": p})
        return {"ordered": lst["ordered"], "items": items}

    def links_for(self, path: list[str], has_children: bool) -> list[str]:
        chave = " > ".join(path)
        if chave in self.ART_OVERRIDE:
            rx, chs = self.ART_OVERRIDE[chave]
        else:
            rx, chs = auto_pattern(path, has_children), None
        self.art_rx[chave] = rx
        if not rx:
            return []
        try:
            r = re.compile(rx)
        except re.error:
            return []
        return [tid for tid in self.ORDER if tid in self.TP and (not chs or chap(tid) in chs) and r.search(self.TP[tid])]

    def render_art_list(self, lst: dict, depth: int = 0) -> str:
        out = ['<ul class="arti">' if depth else '<ul class="arti arti0">']
        for it in lst["items"]:
            lk = self.links_for(it["path"], bool(it["children"]))
            self.art_links[" > ".join(it["path"])] = lk
            chips = "".join(
                f'<a class="tk" href="#{tid_css(x)}" data-go="{x}" title="{html.escape(plain(self.T[x]["title"]))}">{x}</a>'
                for x in lk
            )
            kids = "".join(self.render_art_list(c, depth + 1) for c in it["children"])
            cnt = f'<span class="cnt">{len(lk)} tópico{"s" if len(lk) != 1 else ""}</span>' if lk else ""
            if lk and len(lk) <= 6:
                body = f'<div class="ai sb">{inline(it["text"])}<div class="chips in"><span class="ap">aparece em:</span>{chips}</div></div>'
            elif lk:
                body = (
                    f'<div class="ai sb">{inline(it["text"])} {cnt}</div>'
                    f'<details class="al"><summary>onde aparece ({len(lk)} tópicos)</summary><div class="chips">{chips}</div></details>'
                )
            else:
                body = f'<div class="ai sb">{inline(it["text"])}</div>'
            out.append(f"<li>{body}{kids}</li>")
        out.append("</ul>")
        return "".join(out)

    # ---- mapa mental
    def match(self, label: str, pid: str | None, ch: str) -> str | None:
        if label in self.TREE_OVERRIDE:
            return self.TREE_OVERRIDE[label]
        lt = toks(label.split(" — ")[0])
        if not lt:
            return None
        best, bs = None, -1.0
        for c in (i for i in self.ORDER if chap(i) == ch):
            sc = len(lt & toks(self.T[c]["title"])) / len(lt)
            if pid and c.startswith(pid + "."):
                sc += 0.35
            elif pid and c == pid:
                sc -= 0.2
            sc -= 0.01 * c.count(".")
            if sc > bs:
                best, bs = c, sc
        return best

    def chapter_for(self, idx: int, label: str, usados: set[str]) -> str | None:
        """Capítulo de um nó de 1º nível da árvore, contra todos os
        capítulos do guia (inclusive os excluídos, para o nó do capítulo
        excluído sair junto): o de mais palavras em comum, desempatando
        pela posição."""
        # Todas as palavras, sem tirar as comuns: "Lei penal" só tem
        # palavras da lista STOP e sumiria do mapa.
        lt = set(norm(label.split(" — ")[0]))
        best, bs = None, 0.0
        for j, c in enumerate(self.caps_todos):
            if c["id"] in usados:
                continue
            ct = set(norm(c["title"]))
            sc = (len(lt & ct) / len(lt | ct)) if (lt or ct) else 0.0
            sc -= 0.001 * abs(j - idx)
            if sc > bs:
                best, bs = c["id"], sc
        return best

    def mnode(self, nd: dict, pid: str | None, ch: str, depth: int) -> str:
        label_full = nd["rotulo"]
        mid = self.match(label_full, pid, ch)
        self.tree_map.append((depth, label_full, mid))
        parts = label_full.split(" — ", 1)
        label = parts[0]
        desc = parts[1] if len(parts) > 1 else ""
        sl = seal_for(label, desc)
        dsc = f'<span class="mmd">{inline(desc)}</span>' if desc and desc.strip().lower() not in DROP_DESC else ""
        kids = [self.mnode(c, mid, ch, depth + 1) for c in nd.get("filhos") or []]
        is_open = depth < 2
        cls = "mn" + (" l1" if depth == 1 else "")
        if kids:
            cnt = f'<span class="mcnt" aria-hidden="true">{len(kids)}<i class="chev"></i></span>'
            exp = f' aria-expanded="{"true" if is_open else "false"}"'
            ul = f'<ul class="mkids"{"" if is_open else " hidden"}>{"".join(kids)}</ul>'
        else:
            cnt, exp, ul = "", "", ""
        link = (
            f'<a class="mgo" href="#{tid_css(mid)}" data-go="{mid}">ir até o conteúdo <span aria-hidden="true">→</span></a>'
            if mid
            else ""
        )
        return (
            f'<li class="{cls}"><button type="button" class="mrw"{exp}><span class="mdot" data-dot="{mid or ""}"></span>'
            f'<span class="mtx"><span class="mlab">{inline(label)}</span>{(" " + sl) if sl else ""}{dsc}</span>{cnt}</button>{link}{ul}</li>'
        )

    def build_map(self) -> str:
        tiles, panels = [], []
        usados: set[str] = set()
        for i, nd in enumerate(self.arvore):
            ch = self.chapter_for(i, nd["rotulo"], usados)
            if ch is None:
                self.tree_map.append((0, nd["rotulo"], None))
                continue
            usados.add(ch)
            if ch in self.excluidos:
                continue  # nó do capítulo excluído sai do mapa
            self.tree_map.append((0, nd["rotulo"], ch))
            if ch == self.disp_id and self.disp_list is not None:
                continue  # vira o cartão do índice de artigos, abaixo
            title = inline(self.T[ch]["title"], False)
            tiles.append(
                f'<button type="button" class="mtile" data-mch="{ch}" data-ch="{ch}" aria-expanded="false">'
                f'<span class="mtop"><span class="mnum">{ch}</span><span class="tt">{title}</span></span>'
                f'<span class="cpb"><i></i></span><span class="cpt"></span></button>'
            )
            items = "".join(self.mnode(c, ch, ch, 1) for c in nd.get("filhos") or [])
            head = (
                f'<div class="mhd" data-ch="{ch}"><span class="mnum">{ch}</span><div class="mhx"><b>{title}</b><span class="cpt"></span></div>'
                f'<a class="mgo mgoc" href="#{tid_css(ch)}" data-go="{ch}">ir até o capítulo <span aria-hidden="true">→</span></a></div>'
            )
            tree = f'<ul class="mtree">{items}</ul>' if items else ""
            panels.append(f'<div class="mbr" data-mbr="{ch}" hidden>{head}{tree}</div>')
        if self.disp_id and self.disp_list is not None:
            d = self.disp_id
            tiles.append(
                f'<button type="button" class="mtile" data-go="indice-artigos" data-ch="{d}">'
                f'<span class="mtop"><span class="mnum">{d}</span><span class="tt">{inline(self.T[d]["title"], False)} — índice de artigos</span></span>'
                f'<span class="cpb"><i></i></span><span class="cpt"></span></button>'
            )
        if not tiles:
            return ""
        return '<div class="mgrid">' + "".join(tiles) + "".join(panels) + "</div>"

    # ---- montagem
    def nav_html(self) -> str:
        o = ['<nav class="toc" aria-label="Capítulos">']
        for c in self.chapters:
            subs = [t for t in c["topics"] if t["level"] in (3, 4)]
            items = "".join(
                f'<li class="l{t["level"]}"><a href="#{tid_css(t["id"])}" data-go="{t["id"]}"><span class="num">{t["id"]}</span> {inline(t["title"])}</a></li>'
                for t in subs
            )
            o.append(
                f'<details class="tocc" data-ch="{c["id"]}"><summary><a href="#{tid_css(c["id"])}" data-go="{c["id"]}"><span class="num">{c["id"]}</span> {inline(c["title"], False)}</a>'
                f'<span class="cp"><span class="cpb"><i style="width:0%"></i></span><span class="cpt">0/{len(c["topics"])}</span></span></summary><ul>{items}</ul></details>'
            )
        o.append("</nav>")
        return "".join(o)

    def sections_html(self) -> str:
        out = []
        cs = self.chapters
        for k, c in enumerate(cs):
            prev_c = cs[k - 1] if k > 0 else None
            next_c = cs[k + 1] if k + 1 < len(cs) else None
            tops = "".join(self.render_topic(t) for t in c["topics"])
            pn = '<nav class="chnav">'
            pn += (
                f'<a href="#{tid_css(prev_c["id"])}" data-go="{prev_c["id"]}">← {prev_c["id"]}. {inline(prev_c["title"], False)}</a>'
                if prev_c
                else "<span></span>"
            )
            pn += (
                f'<a href="#{tid_css(next_c["id"])}" data-go="{next_c["id"]}">{next_c["id"]}. {inline(next_c["title"], False)} →</a>'
                if next_c
                else '<a href="#topo" data-go="topo">↑ topo</a>'
            )
            pn += "</nav>"
            out.append(
                f'<section class="chap" data-sec="{c["id"]}"><div class="chprog" data-ch="{c["id"]}"><span class="cpb"><i style="width:0%"></i></span>'
                f'<span class="cpt"></span></div>{tops}{pn}</section>'
            )
        return "".join(out)

    def build(self) -> dict:
        self.art_index_html = ""
        self.filtered_disp = None
        if self.disp_list is not None:
            self.filtered_disp = self._filtrar(self.disp_list, [])
            self.art_index_html = (
                '<div class="vis artidx" id="indice-artigos"><div class="vt">Índice de artigos — toque no número para ir ao tópico</div>'
                + self.render_art_list(self.filtered_disp)
                + "</div>"
            )
        mapa = self.build_map()
        secoes_html = self.sections_html()
        return {
            "total": len(self.topics),
            "capitulos": [c["id"] for c in self.chapters],
            "capitulos_faixa": faixas([c["id"] for c in self.chapters]) if self.chapters else "",
            "excluidos": self.excluidos,
            "mapa_html": mapa,
            "nav_html": self.nav_html(),
            "secoes_html": secoes_html,
            "tem_indice_artigos": bool(self.art_index_html),
            "tree_map": self.tree_map,
            "art_links": self.art_links,
            "ignorados": self.ignorados,
        }


def faixas(ids: list[str]) -> str:
    """["1".."8", "10"] -> "1 a 8 e 10"."""
    nums = [int(i) for i in ids]
    grupos: list[list[int]] = []
    for n in nums:
        if grupos and n == grupos[-1][-1] + 1:
            grupos[-1].append(n)
        else:
            grupos.append([n])
    partes = [f"{g[0]} a {g[-1]}" if len(g) > 2 else (f"{g[0]} e {g[1]}" if len(g) == 2 else str(g[0])) for g in grupos]
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]


def render_foco(foco_md: str) -> str:
    """Bloco "Foco deste guia" (guia focado), literal, com os mesmos
    blocos da página. Fora dos tópicos: sem número nem "estudado"."""
    return "".join(render_block(b, sb=True) for b in parse_blocks(foco_md.strip().split("\n")))


def montar(secoes: list[tuple[str, str]], arvore_json: str | None, conteudo_json: str | None) -> dict:
    """Contexto da página a partir do guia gravado: `secoes` =
    [(titulo, corpo)] de `GuiaSecao`, em ordem; `conteudo_json` =
    `GuiaInterativo.conteudo_json` (ou None, sem a skill)."""
    return Pagina(secoes, json.loads(arvore_json or "[]"), json.loads(conteudo_json or "{}")).build()
