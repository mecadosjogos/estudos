"""Aula de consolidação (PLANO.md, "Aula de consolidação"): junta os
guias de várias aulas de uma matéria num guia único, sem repetição e
organizado para ensinar, com índice hierárquico próprio (ai/guia_numeracao.py).

Parte dos GUIAS, não da transcrição -- exceção deliberada, mesmo
precedente do "Dominar o guia": o guia já é o material revisado e aceito
para estudo. Quem escreve é a skill /consolidar-guia pela ponte manual
(pacote -> resposta -> colar); aqui ficam o pacote (fonte única das
regras), a ingestão e um relatório de termos que ajuda a conferir que
nada se perdeu e nada entrou de fora. A resposta é markdown puro, não
JSON: o texto é longo e o parser do guia (ai/guia_parser.py) já lê
markdown.
"""

import json
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AiCall, Lesson
from .guia_parser import parse_guia_markdown
from .pipeline import ProcessingError, persistir_guia

TIPO = "consolidacao"


def titulo_padrao(fontes: list[Lesson]) -> str:
    datas = sorted(f.data for f in fontes)
    return f"Consolidação aulas {datas[0]:%d/%m} até {datas[-1]:%d/%m}"


def aulas_consolidaveis(session: Session, subject_id: int) -> list[Lesson]:
    """Aulas normais da matéria com guia estruturado, em ordem cronológica."""
    return list(
        session.scalars(
            select(Lesson)
            .where(
                Lesson.subject_id == subject_id,
                Lesson.tipo == "aula",
                Lesson.guia_secoes.any(),
            )
            .order_by(Lesson.data, Lesson.id)
        )
    )


def fontes_de(session: Session, lesson: Lesson) -> list[Lesson]:
    ids = json.loads(lesson.consolidacao_fontes_json or "[]")
    por_id = {f.id: f for f in session.scalars(select(Lesson).where(Lesson.id.in_(ids)))}
    return [por_id[i] for i in ids if i in por_id]


def _validar_fontes(session: Session, subject_id: int, fonte_ids: list[int]) -> list[Lesson]:
    validas = {f.id: f for f in aulas_consolidaveis(session, subject_id)}
    fontes = [validas[i] for i in dict.fromkeys(fonte_ids) if i in validas]
    if len(fontes) < 2:
        raise ProcessingError("escolha pelo menos duas aulas com guia")
    return sorted(fontes, key=lambda f: (f.data, f.id))


def criar_consolidacao(session: Session, subject_id: int, fonte_ids: list[int], titulo: str) -> Lesson:
    fontes = _validar_fontes(session, subject_id, fonte_ids)
    lesson = Lesson(
        subject_id=subject_id,
        tipo=TIPO,
        titulo=titulo.strip() or titulo_padrao(fontes),
        data=fontes[-1].data,
        consolidacao_fontes_json=json.dumps([f.id for f in fontes]),
    )
    session.add(lesson)
    session.commit()
    return lesson


def trocar_fontes(session: Session, lesson: Lesson, fonte_ids: list[int]) -> None:
    """Corrige a seleção sem recriar a aula (o app não apaga aula). Só a
    lista muda -- o guia atual fica até a skill rodar de novo; título e
    data seguem a nova seleção."""
    fontes = _validar_fontes(session, lesson.subject_id, fonte_ids)
    if lesson.titulo == titulo_padrao(fontes_de(session, lesson) or fontes):
        lesson.titulo = titulo_padrao(fontes)
    lesson.data = fontes[-1].data
    lesson.consolidacao_fontes_json = json.dumps([f.id for f in fontes])
    session.commit()


INSTRUCTIONS = """Você vai CONSOLIDAR os guias de aula abaixo -- todos da
mesma matéria -- num GUIA ÚNICO. É o material de estudo para depois que a
matéria fechou: quem lê precisa encontrar tudo o que foi dado em aula,
uma vez só, organizado para aprender.

## O que PODE

- Reorganizar livremente por TEMA, na ordem que facilita aprender (do
  geral para o específico; cronológica quando o próprio conteúdo é
  histórico) -- não na ordem das aulas.
- Juntar num lugar só o que aparece espalhado em várias aulas.
- Transformar em tabela, lista ou quadro comparativo quando isso deixa o
  conteúdo mais claro (ex.: fases, tribunais, penas, comparações entre
  sistemas).
- Cortar a repetição: o mesmo conceito dado em mais de uma aula fica em
  UM lugar só.

## O que NÃO pode

- **Trocar as palavras de um conceito.** Definições, termos,
  classificações, citações e exemplos ficam com a redação do guia -- é o
  que o professor passou e o que vai ser cobrado na prova. Nada de
  sinônimo, nada de "melhorar" a frase. Juntar e mover, sim; reescrever,
  não.
- **Acrescentar conteúdo externo.** Nenhum autor, data, fato, exemplo
  ou explicação que não esteja nos guias abaixo, mesmo que você saiba
  que é verdade. O limite é o que foi dado em aula.
- **Perder conteúdo.** Tudo o que os guias trazem tem que estar no
  consolidado. Quando duas aulas explicam a mesma coisa com detalhes
  diferentes, some os detalhes. Quando divergem, mantenha as duas
  formulações lado a lado, sem resolver por conta própria.
- **Indicar a aula de origem.** Nada de "(aula 3)", "visto na aula de
  25/08" -- o consolidado é um texto só.
- **Manter meta-fala de aula.** "Retomada", "na aula passada", "como
  vimos", "hoje vamos ver" saem; o conteúdo de uma seção de retomada se
  funde no tema correspondente.

Marcadores `[trecho incompleto/inaudível...]` ficam onde estão, junto do
trecho a que pertencem. O conteúdo de blocos "Material da aula" entra
integrado ao tema (pode manter o rótulo **Material da aula:** quando for
citação literal do material).

## Formato da resposta

Markdown puro (pode vir dentro de um bloco ```markdown). NÃO numere nada
e NÃO escreva sumário/índice -- o sistema numera (8 / 8.1 / 8.1.1 /
8.1.1.1 / 8.1.1.1.1) e gera o índice a partir dos títulos.

```
# <título do guia consolidado>

## Árvore de conhecimento
- <conceito>
    - <subconceito>

## <Tema>                    (nível 1 -- vira 1, 2, 3...)
### <Subtema>                (nível 2 -- vira 1.1, 1.2...)
#### <Espécie/conceito>      (nível 3 -- vira 1.1.1...)
##### <Subespécie>           (nível 4 -- vira 1.1.1.1...)
###### <Detalhe>             (nível 5 -- vira 1.1.1.1.1...)
<texto>

## Trechos incompletos/inaudíveis     (opcional, só se houver)
- <trecho>
```

## Como montar o índice

Os níveis acima são o LIMITE, não um molde. A profundidade segue a
matéria, não o formato:

- **Os níveis espelham as classificações dadas em aula** -- gênero ->
  espécie -> subespécie. Se o professor disse que retroatividade e
  ultratividade são espécies de extratividade, elas ficam DENTRO de
  extratividade; se costumes e princípios são fontes formais mediatas,
  ficam dentro de "fontes formais mediatas", não ao lado de "fontes
  formais". Não achate uma classificação para caber em menos níveis.
- **Cada ramo desce só o que precisa.** Um tema raso fica com dois
  níveis; uma classificação com gênero, espécie e subespécie chega a
  quatro ou cinco. Nada de forçar todos os ramos à mesma profundidade.
- **Só abra um nível com pelo menos dois filhos.** Um filho único vira
  texto do pai.
- **Todo título que alguém procuraria no índice ganha título** -- e
  ganha número, até o quinto nível. Exemplo que serve pra localizar
  ("o caso do feminicídio", "a enchente") pode ser título, pendurado no
  conceito que ilustra.
- **Detalhe de apoio fica no texto, não no índice.** "Como se escreve e
  como se pronuncia", observação curta, frase solta: dentro do conceito,
  sem título próprio.
"""


def build_pacote(session: Session, lesson: Lesson) -> str:
    if lesson.tipo != TIPO:
        raise ProcessingError("esta aula não é uma consolidação")
    fontes = fontes_de(session, lesson)
    if not fontes:
        raise ProcessingError("consolidação sem aulas-fonte")
    parts = [
        f"# Consolidar guias — {lesson.subject.nome} — {lesson.titulo}\n",
        INSTRUCTIONS,
        f"# Guias das aulas ({len(fontes)})\n",
        "Cada guia vem entre `<<<INÍCIO GUIA ...>>>` e `<<<FIM GUIA>>>`. "
        "A numeração das seções dentro deles é da aula original -- ignore.\n",
    ]
    for f in fontes:
        parts.append(f"<<<INÍCIO GUIA — {f.titulo} — {f.data:%d/%m/%Y} — {f.guia_titulo or ''}>>>\n")
        parts.append((f.guia_md or "").strip() + "\n")
        parts.append("<<<FIM GUIA>>>\n")
    return "\n".join(parts)


_FENCE_BLOCO_RE = re.compile(r"```(?:markdown|md)?[ \t]*\n(.*)\n```", re.DOTALL)


def extrair_markdown(texto: str) -> str:
    """Aceita o markdown cru ou dentro de um bloco ```markdown. Só
    desembrulha quando o texto COMEÇA com o bloco -- um guia cru pode ter
    blocos de código no meio."""
    texto = (texto or "").replace("\r\n", "\n").strip()
    if texto.startswith("```"):
        m = _FENCE_BLOCO_RE.match(texto)
        if m:
            return m.group(1).strip()
    return texto


# --- relatório de termos ----------------------------------------------------------

_NEGRITO_RE = re.compile(r"\*\*(.+?)\*\*")
# Rótulos de bloco (markdown_render.py::_ROTULOS) -- estrutura, não conteúdo.
_ROTULOS = {"lei", "definicao", "exemplo", "atencao", "pergunta de aluno", "aluno", "material da aula"}


def _norm(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[*_`|>#]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _termos_negrito(md: str) -> dict[str, str]:
    """{normalizado: como aparece} dos trechos em negrito, sem rótulos."""
    termos = {}
    for m in _NEGRITO_RE.finditer(md):
        bruto = m.group(1).strip().rstrip(":").strip()
        n = _norm(bruto).strip(" .,;:")
        if n and n not in _ROTULOS and not n.startswith("exemplo"):
            termos.setdefault(n, bruto)
    return termos


def relatorio_termos(fontes_md: list[str], consolidado_md: str) -> dict:
    """Aviso, não bloqueio: termos em negrito das fontes que não aparecem
    em lugar nenhum do consolidado (possível perda) e termos em negrito do
    consolidado que não aparecem em nenhuma fonte (possível conteúdo
    externo). Compara normalizado (caixa, acento, espaço, marcação)."""
    fontes_norm = " \n ".join(_norm(md) for md in fontes_md)
    consolidado_norm = _norm(consolidado_md)
    termos_fontes: dict[str, str] = {}
    for md in fontes_md:
        for n, bruto in _termos_negrito(md).items():
            termos_fontes.setdefault(n, bruto)
    perdidos = [bruto for n, bruto in termos_fontes.items() if n not in consolidado_norm]
    externos = [bruto for n, bruto in _termos_negrito(consolidado_md).items() if n not in fontes_norm]
    return {"perdidos": perdidos, "externos": externos}


def ingest_consolidacao(session: Session, lesson: Lesson, texto: str) -> dict:
    if lesson.tipo != TIPO:
        raise ProcessingError("esta aula não é uma consolidação")
    md = extrair_markdown(texto)
    if not md.startswith("# "):
        raise ProcessingError("resposta sem título (# ...) -- não parece o guia consolidado")
    fontes = fontes_de(session, lesson)
    parsed = parse_guia_markdown(md)
    persistir_guia(session, lesson, parsed)
    session.add(
        AiCall(
            lesson_id=lesson.id,
            tipo_acao="consolidar_guia",
            via="manual",
            modelo="manual",
            input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=0,
            custo_usd=0.0,
            raw_response_json=json.dumps({"guia_md": md}, ensure_ascii=False),
        )
    )
    session.commit()

    corpo_total = "\n".join(s.corpo for s in parsed.secoes)
    return {
        "ok": True,
        "secoes": len(parsed.secoes),
        "subtitulos": len(re.findall(r"^### ", corpo_total, re.MULTILINE)),
        "conceitos": len(re.findall(r"^#### ", corpo_total, re.MULTILINE)),
        "relatorio": relatorio_termos([f.guia_md or "" for f in fontes], md),
    }

