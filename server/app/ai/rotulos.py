"""Passada de rótulos no guia (RUNBOOK.md, "Rótulos do guia"): depois que o
guia de uma aula ou de uma consolidação está gravado, uma leitura à parte
acrescenta os rótulos `Definição:` / `Exemplo:` / `Atenção:` que o
renderizador (markdown_render.py, `_ROTULO_RE`) transforma em bloco com selo.

Regra que manda em tudo (decisão do usuário): **nenhuma palavra muda**. Só
se acrescentam rótulos, se quebra um parágrafo em dois, se tira o `>` de
uma citação que vira rótulo, se troca o sinal logo depois de um rótulo por
dois-pontos e se acertam asteriscos. `validar()` confere isso por seção,
em código, e recusa a seção que mexeu em qualquer outra coisa -- a regra
não depende de quem rotula.

A passada roda sozinha (sem lista para aprovar): aplica só o que é claro e
deixa de fora o que é duvidoso, que foi o que o usuário aprovou na
primeira rodada (consolidação 66).

Grava por seção, como a correção manual (`routes/lessons.py::
edit_guia_secao`): não reprocessa a aula, mantém o id das seções (e com
ele os exercícios do guia) e não refaz a narração.

Guia Focado fica de fora por enquanto (decisão do usuário): o rótulo
"Atenção da professora" é dele e a consolidação não pode mudar por causa
do foco.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..markdown_render import wrap_labeled_blocks
from ..models import GuiaSecao, Lesson
from .pipeline import ProcessingError

INSTRUCTIONS = """\
# Passada de rótulos de formatação

O objetivo é facilitar a leitura do guia **sem mudar o texto**: nenhuma
palavra alterada, removida ou reordenada. Só se acrescentam rótulos e,
quando necessário, se quebra um parágrafo em dois. **Ninguém vai aprovar
uma lista antes:** você aplica sozinho, então aplique só o que for claro.
**Na dúvida, não rotule** — um rótulo a menos não custa nada; um rótulo
errado engana quem estuda.

O servidor confere cada seção que você devolver e **recusa a seção
inteira** se qualquer palavra mudou, sumiu ou trocou de lugar.

## Como o guia vira bloco destacado

O sistema transforma em bloco colorido, com selo, o parágrafo que
**começa** com um destes rótulos:
`Lei:` · `Definição:` · `Exemplo:` (aceita "Exemplo invertido:" etc., até
30 letras depois de "Exemplo", sem negrito) · `Atenção:` ·
`Pergunta de aluno:` / `Aluno:` · `Material da aula:`

Formas reconhecidas, sempre no começo da linha e depois de uma linha em
branco: `Exemplo: texto…` · `**Exemplo:** texto…` · `**Exemplo**: texto…`

Limites:
- **Não funciona dentro de item de lista** (`- …`, `1. …`) nem dentro de
  citação (`> …`).
- O bloco cobre **só aquele parágrafo**. A lista que vem logo depois só
  entra no bloco se o parágrafo terminar em `:`.

## O que fazer

**1. Rotular parágrafos claramente de um tipo** — acrescente `Definição: `,
`Exemplo: ` ou `Atenção: ` no começo. Se o parágrafo começa com um título
em negrito (`**Julgamento à distância.** …`), fica
`Atenção: **Julgamento à distância.** …`.
- **Definição**: o parágrafo diz o que algo é ou significa ("X significa…",
  "X é…", "considera-se…", a formulação de uma teoria entre aspas).
- **Exemplo**: um caso, hipotético ou real, contado no parágrafo. Inclui o
  parágrafo de abertura de uma seção cujo título já é "Exemplo: …" mas
  cujo corpo não tem o rótulo, para ficar igual aos casos que já têm.
- **Atenção**: regra taxativa, pegadinha, "não confunda", "basta uma",
  "só nessas", "nunca"/"sempre", consequência prática importante.

**2. Quebrar o parágrafo** (`\\n\\n`, as palavras não mudam) quando:
- o rótulo já está escrito no **meio** do parágrafo
  (`… pode somente nessas hipóteses. Atenção: isso só vale…`);
- o parágrafo abre com outra frase e só depois vem a definição, o exemplo
  ou a regra — quebre logo antes e rotule a segunda parte.

**3. Citação com definição ou regra ditada** (`> **Retroatividade é…**`): o
rótulo não funciona dentro de citação. Tire o `>` (de todas as linhas da
citação) e rotule: `**Retroatividade é…**` vira
`Definição: **Retroatividade é…**`. Regra ditada ("Memorize: …", "só em
benefício do réu", "sempre ultra-agirá") vira `Atenção:`. Citação que não
for claramente definição ou regra fica como está.

**4. A armadilha dos asteriscos** — rótulo e título do caso num negrito só,
**com o texto do caso continuando na mesma linha**:
`**Exemplo: o caso Jean Charles.** O Jean Charles era…`
não é reconhecido. A correção só mexe nos asteriscos:
`**Exemplo:** **o caso Jean Charles.** O Jean Charles era…`
Vale para qualquer rótulo (`Lei`, `Definição`, `Exemplo`, `Atenção`,
`Pergunta de aluno`, `Aluno`, `Material da aula`).
Regex: `^\\*\\*(Lei|Defini[çc][ãa]o|Exemplo|Aten[çc][ãa]o|Pergunta de aluno|Aluno|Material da aula):[ \\t]+([^*\\n]+?)\\*\\*` → `**\\1:** **\\2**`
**Não corrija** quando o negrito é uma linha sozinha (título do caso) e o
texto vem no parágrafo seguinte: a correção criaria um bloco só com o
nome do caso, colado num segundo bloco com o mesmo selo.

**5. Rótulo já escrito com o sinal errado** — troque só o sinal por
dois-pontos:
- `Atenção — e isso é importante…` → `Atenção: e isso é importante…`
- `Atenção, para vocês…` → `Atenção: para vocês…`
- `Exemplo fácil de enxergar.` → `Exemplo fácil de enxergar:`
Só quando o que fica antes dos dois-pontos cabe no rótulo ("Exemplo" + até
30 letras, sem negrito). Se não couber, deixe como está.

## O que NÃO fazer (decisões do usuário)

- **Não acrescentar rótulos novos de "Pergunta de aluno"**, nem mexer em
  "Perguntas de aluno:" no plural, "Pergunta de aluna:" ou "Pergunta de
  aluno sobre…". Para pergunta de aluno só vale o conserto de asteriscos.
- Não rotular nada **dentro de listas**, e não transformar lista em
  parágrafo. Não mexer em títulos (`#`), tabelas nem na indentação.
- Não rotular parágrafos de **continuação** de um exemplo que já tem
  rótulo (não repetir o rótulo no mesmo caso).
- Não tirar o `>` de `> **Material da aula:**`.
- Rótulos que o sistema não conhece (`Princípio:`, `Conselho:`,
  `Analogia:`, `Liberação:`) ficam como estão. Não trocar por outro.
- Não reescrever, não corrigir português, não acertar pontuação fora do
  item 5, não juntar parágrafos.
- **Nunca reprocessar a aula.**

## Duvidoso = fica sem rótulo

Estes casos ficaram de fora na rodada que o usuário aprovou. Não rotule:
- **Definição** que é só enumeração de partes ("é composto por três
  bases: terra, ar e mar") ou que aparece no fim de uma frase sobre outra
  coisa ("…Essa zona é a área de exploração econômica exclusiva").
- **Exemplo** que pode ser continuação do exemplo anterior, que retoma um
  caso já contado ("Voltando à Estação Espacial…") ou que é uma pergunta
  retórica abrindo hipótese ("Você poderia fazer uma outra pergunta…").
- **Atenção** que é: dica de como estudar ou memorizar ("Dica do
  professor:", "Memoriza pelo nome…"); relevância ou contexto ("é da
  própria Constituição", "Relevância: …"); explicação do porquê de uma
  regra; conclusão sem palavra taxativa; repetição de uma regra que já
  está rotulada na mesma seção ou na seção vizinha; detalhe de uma
  exceção ("exceção da exceção").

## Formato da resposta

Devolva **só as seções que mudaram**, cada uma com a linha de abertura
copiada do pacote e o **corpo inteiro** da seção logo abaixo (não só o
trecho alterado):

```
<<<SECAO (id) | (título)>>>
(corpo completo da seção, já rotulado)

<<<SECAO (id) | (título)>>>
(corpo completo da seção, já rotulado)
```

(`(id)` e `(título)` são os da linha de abertura da seção no pacote, por
exemplo `<<<SECAO 163 | Retroatividade>>>`.)

Fora das seções que você mexeu, tudo fica igual — linhas em branco,
listas, tabelas, títulos. Se nenhuma seção precisar de rótulo, responda
só `NENHUMA`.
"""

_SECAO_RE = re.compile(r"^<<<SECAO (\d+)(?: \|[^\n]*?)?>>>[ \t]*$", re.MULTILINE)
_BLOCO_RE = re.compile(r'guia-bloco--(\w+)"')

# Tokenização para a conferência: o que não é palavra nem pontuação
# (espaço, quebra de linha dentro do parágrafo, asterisco, `>` de citação)
# não conta; a quebra de parágrafo é um token próprio.
_PAR = "¶"
_CITACAO_RE = re.compile(r"^[ \t]*>[ \t]?", re.MULTILINE)
_PARAGRAFO_RE = re.compile(r"\n[ \t]*\n")
_TOKEN_RE = re.compile(r"\w+|[^\w\s]")
_NOVOS = {"Definição", "Exemplo", "Atenção"}
_ROTULO_PALAVRA = {"Lei", "Definição", "Definicao", "Exemplo", "Atenção", "Atencao", "Aluno", "Pergunta", "Material"}
_SINAL_TROCAVEL = {"—", "–", "-", ",", ".", ";"}
# Linhas de estrutura (lista, título, tabela): têm que ficar idênticas.
_ESTRUTURA_RE = re.compile(r"^[ \t]*(?:[-*+][ \t]|\d+[.)][ \t]|#{1,6}[ \t]|\|)")
_MATERIAL_CITACAO_RE = re.compile(r"^[ \t]*>[ \t]*(?:\*\*)?Material da aula", re.MULTILINE)


def contar_rotulos(texto: str) -> Counter:
    """Blocos com selo que o renderizador monta, por tipo."""
    return Counter(_BLOCO_RE.findall(wrap_labeled_blocks(texto.replace("\r\n", "\n"))))


def _tokens(texto: str) -> list[str]:
    texto = _CITACAO_RE.sub("", texto.replace("\r\n", "\n")).replace("*", "")
    out: list[str] = []
    for par in _PARAGRAFO_RE.split(texto.strip()):
        toks = _TOKEN_RE.findall(par)
        if not toks:
            continue
        if out:
            out.append(_PAR)
        out.extend(toks)
    return out


def _estrutura(texto: str) -> list[str]:
    return [
        linha.replace("*", "").rstrip()
        for linha in texto.replace("\r\n", "\n").split("\n")
        if _ESTRUTURA_RE.match(linha)
    ]


def _inicio_do_paragrafo(toks: list[str], j: int) -> int:
    while j > 0 and toks[j - 1] != _PAR:
        j -= 1
    return j


def _trecho(toks: list[str], i: int, j: int) -> str:
    return " ".join(t for t in toks[max(i, 0):j] if t != _PAR)[:80]


def validar(antigo: str, novo: str) -> str | None:
    """None se `novo` só acrescenta rótulos/quebras ao `antigo`; senão, o
    motivo da recusa (curto, para a skill corrigir e reenviar)."""
    if _estrutura(antigo) != _estrutura(novo):
        return "mexeu em lista, título ou tabela"
    if len(_MATERIAL_CITACAO_RE.findall(antigo)) != len(_MATERIAL_CITACAO_RE.findall(novo)):
        return "mexeu na citação de Material da aula"

    a, b = _tokens(antigo), _tokens(novo)
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        if tag == "insert":
            k = j1
            while k < j2:
                if b[k] == _PAR:
                    k += 1
                    continue
                if b[k] in _NOVOS and k + 1 < j2 and b[k + 1] == ":":
                    if k > 0 and b[k - 1] != _PAR:
                        return f"rótulo fora do começo do parágrafo: «{_trecho(b, k - 6, k + 6)}»"
                    if k + 2 < len(b) and b[k + 2] in _ROTULO_PALAVRA and ":" in b[k + 3:k + 6]:
                        return f"rótulo em cima de outro rótulo: «{_trecho(b, k, k + 8)}»"
                    k += 2
                    continue
                return f"acrescentou texto: «{_trecho(b, j1, j2)}»"
            continue
        if tag == "replace" and i2 - i1 == 1 and a[i1] in _SINAL_TROCAVEL and b[j1:j2] == [":"]:
            inicio = _inicio_do_paragrafo(b, j1)
            if b[inicio] in ("Exemplo", "Atenção") and j1 - inicio <= 7:
                continue
            return f"trocou pontuação fora de um rótulo: «{_trecho(b, inicio, j2 + 4)}»"
        if tag == "delete":
            if all(t == _PAR for t in a[i1:i2]):
                return f"juntou parágrafos: «{_trecho(a, i1 - 6, i2 + 6)}»"
            return f"removeu texto: «{_trecho(a, i1, i2)}»"
        return f"mudou o texto: «{_trecho(a, i1, i2)}» → «{_trecho(b, j1, j2)}»"
    return None


def _secoes(session: Session, lesson: Lesson) -> list[GuiaSecao]:
    if lesson.focado:
        raise ProcessingError("guia focado fica fora da passada de rótulos por enquanto")
    secoes = session.scalars(
        select(GuiaSecao).where(GuiaSecao.lesson_id == lesson.id).order_by(GuiaSecao.ordem)
    ).all()
    if not secoes:
        raise ProcessingError("a aula não tem guia estruturado (sem seções)")
    return list(secoes)


def _total(secoes: list[GuiaSecao]) -> dict[str, int]:
    total: Counter = Counter()
    for s in secoes:
        total += contar_rotulos(s.corpo)
    return dict(sorted(total.items()))


def build_pacote(session: Session, lesson: Lesson) -> str:
    secoes = _secoes(session, lesson)
    partes = [
        f"<!-- rótulos do guia — aula {lesson.id}: {lesson.titulo} -->",
        "",
        INSTRUCTIONS,
        "",
        f"# Seções do guia ({len(secoes)})",
        "",
        f"Blocos com selo hoje: {_total(secoes)}",
        "",
    ]
    for s in secoes:
        titulo = " ".join(s.titulo.split())
        partes += [f"<<<SECAO {s.id} | {titulo}>>>", s.corpo.strip(), ""]
    return "\n".join(partes)


def parse_resposta(texto: str) -> dict[int, str]:
    texto = texto.replace("\r\n", "\n").strip()
    marcas = list(_SECAO_RE.finditer(texto))
    if not marcas:
        if texto.upper().strip("`. \n") == "NENHUMA":
            return {}
        raise ProcessingError("resposta sem nenhuma linha <<<SECAO id | título>>> (ou NENHUMA)")
    out: dict[int, str] = {}
    for n, m in enumerate(marcas):
        fim = marcas[n + 1].start() if n + 1 < len(marcas) else len(texto)
        secao_id = int(m.group(1))
        if secao_id in out:
            raise ProcessingError(f"seção {secao_id} veio duas vezes na resposta")
        out[secao_id] = texto[m.end():fim].strip()
    return out


def aplicar(session: Session, lesson: Lesson, resposta: str) -> dict:
    """Grava as seções que passaram na conferência e recusa as outras, uma
    a uma (uma seção recusada não segura as demais). Não faz commit nem
    remonta `guia_md` -- quem chama faz, uma vez só."""
    secoes = _secoes(session, lesson)
    por_id = {s.id: s for s in secoes}
    antes = _total(secoes)

    alteradas, rejeitadas, iguais = [], [], 0
    for secao_id, corpo in parse_resposta(resposta).items():
        secao = por_id.get(secao_id)
        if secao is None:
            rejeitadas.append({"secao_id": secao_id, "titulo": None, "motivo": "seção não é deste guia"})
            continue
        if not corpo:
            rejeitadas.append({"secao_id": secao_id, "titulo": secao.titulo, "motivo": "corpo vazio"})
            continue
        if corpo == secao.corpo.strip():
            iguais += 1
            continue
        motivo = validar(secao.corpo, corpo)
        if motivo:
            rejeitadas.append({"secao_id": secao_id, "titulo": secao.titulo, "motivo": motivo})
            continue
        ganho = contar_rotulos(corpo)
        ganho.subtract(contar_rotulos(secao.corpo))
        secao.corpo = corpo
        alteradas.append(
            {"secao_id": secao_id, "titulo": secao.titulo, "rotulos": {k: v for k, v in ganho.items() if v}}
        )

    return {
        "alteradas": alteradas,
        "rejeitadas": rejeitadas,
        "sem_mudanca": iguais,
        "rotulos_antes": antes,
        "rotulos_depois": _total(secoes),
    }
