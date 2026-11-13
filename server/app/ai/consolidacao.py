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

from ..models import AiCall, Exam, Lesson
from .guia_numeracao import extrair_marcas, numerar_consolidado, titulos_marcados
from .guia_parser import parse_guia_markdown
from .pipeline import ProcessingError, persistir_guia

TIPO = "consolidacao"


def titulo_padrao(fontes: list[Lesson]) -> str:
    datas = sorted(f.data for f in fontes)
    return f"Consolidação aulas {datas[0]:%d/%m} até {datas[-1]:%d/%m}"


def titulo_padrao_focado(exam: Exam | None = None) -> str:
    """Título proposto: "Focado — P1" com prova ligada, "Focado — Prova"
    sem. Num foco de tema o usuário troca o fim ao criar ("Focado —
    Direito romano")."""
    return f"Focado — {exam.titulo if exam else 'Prova'}"


def provas_da_materia(session: Session, subject_id: int) -> list[Exam]:
    return list(session.scalars(select(Exam).where(Exam.subject_id == subject_id).order_by(Exam.data)))


def _validar_exam(session: Session, subject_id: int, exam_id: int | None) -> int | None:
    if not exam_id:
        return None
    exam = session.get(Exam, exam_id)
    if exam is None or exam.subject_id != subject_id:
        raise ProcessingError("prova não encontrada nesta matéria")
    return exam.id


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


def criar_consolidacao(
    session: Session,
    subject_id: int,
    fonte_ids: list[int],
    titulo: str,
    *,
    foco_orientacao: str | None = None,
    exam_id: int | None = None,
) -> Lesson:
    """Com `foco_orientacao`, nasce um guia Focado (models.py::Lesson)."""
    fontes = _validar_fontes(session, subject_id, fonte_ids)
    foco = (foco_orientacao or "").strip() or None
    exam_id = _validar_exam(session, subject_id, exam_id) if foco else None
    if foco:
        padrao = titulo_padrao_focado(session.get(Exam, exam_id) if exam_id else None)
    else:
        padrao = titulo_padrao(fontes)
    lesson = Lesson(
        subject_id=subject_id,
        tipo=TIPO,
        titulo=titulo.strip() or padrao,
        data=fontes[-1].data,
        consolidacao_fontes_json=json.dumps([f.id for f in fontes]),
        foco_orientacao=foco,
        exam_id=exam_id,
    )
    session.add(lesson)
    session.commit()
    return lesson


def trocar_foco(session: Session, lesson: Lesson, foco_orientacao: str, exam_id: int | None) -> None:
    """Corrige a orientação/prova de um guia Focado. Como `trocar_fontes`:
    o guia atual (bloco de foco e marcas incluídos) fica até a skill rodar
    de novo."""
    foco = (foco_orientacao or "").strip()
    if not foco:
        raise ProcessingError("a orientação do foco não pode ficar vazia")
    lesson.foco_orientacao = foco
    lesson.exam_id = _validar_exam(session, lesson.subject_id, exam_id)
    session.commit()


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


FOCO_INSTRUCTIONS = """# Este guia é FOCADO

Este guia tem um FOCO: uma prova ou um tema, descrito na ORIENTAÇÃO
abaixo (o que o usuário passou: fala do professor em aula, observações
dele). **O guia traz SÓ o conteúdo do foco** -- quem o pega quer
estudar exatamente o que cai, sem o resto da matéria no caminho. Esta
parte muda duas regras de cima; as demais (não parafrasear conceito,
nada externo, sem aula de origem, sem meta-fala, como montar o índice)
continuam valendo.

## 1. O que entra -- e a regra "perder conteúdo" muda

- **Entra todo o conteúdo dos guias que pertence aos temas do foco**, de
  qualquer aula. O critério é o TEMA, não a aula: se o foco é Direito
  romano e a Lei das Doze Tábuas foi dada numa aula sobre outro
  assunto, ela entra; se uma aula sobre Direito romano começou retomando
  outro tema, a retomada não entra.
- **Fica de fora o que não pertence ao foco** -- outros povos, sistemas,
  códigos e teorias, avisos de outras provas, leituras/filmes que não
  sejam do tema do foco.
- **Dentro do foco, nada se perde.** A regra "Perder conteúdo" de cima
  vale inteira para o conteúdo do foco: tudo o que os guias trazem
  sobre os temas do foco tem que estar aqui.
- **Fronteira:** um conceito de fora entra só do jeito que foi ensinado
  DENTRO de um tema do foco (ex.: "o fundamento jusnaturalista do direito
  romano arcaico" entra com o romano; a teoria geral do jusnaturalismo,
  dada noutro contexto, não). Na dúvida, deixe de fora e liste no
  relatório final para o usuário decidir.
- A organização é a que ensina melhor, como em qualquer consolidação --
  só que do conteúdo do foco. A árvore de conhecimento também cobre só
  o foco.

## 2. Bloco "Foco deste guia"

Logo depois do título (`#`), antes da árvore, uma seção
`## Foco deste guia`, curta, em lista. Diz a quem pega o guia em que ele
está focado:

- **o foco**: qual prova (e a data, se houver prova ligada abaixo) ou
  qual tema;
- **o que cai / o que o foco cobre**, com as palavras do professor;
- **formato da prova**, se a orientação disser;
- outras orientações dadas sobre ESTA prova (o que é mais fácil, o que
  priorizar, o que levar). Orientação sobre esta prova que esteja num
  guia-fonte (ex.: uma seção "Orientações para a prova") vem para cá,
  com a redação do guia;
- **ficou de fora**: uma linha com os grandes temas da matéria que este
  guia não traz (ex.: "Direito egípcio, Código de Hamurabi, direito
  hebraico"), pra ninguém achar que esqueceu.

Regras do bloco:
- **Fala do professor vai entre aspas, literal**, como está na
  orientação. Sem retocar.
- **Dedução não se passa por fala.** A orientação pode misturar o que o
  professor disse com o que quem a reuniu deduziu ("o 'ou' deve ser erro
  da transcrição", "'Direito de comando' é Direito Romano"). Dedução
  entra marcada como tal, em itálico e com "(observação)" -- nunca entre
  aspas, nunca como se fosse do professor.
- **Nada além da orientação.** O bloco não ensina a matéria; quem ensina
  é o resto do guia.
- **Item do foco sem conteúdo nos guias**: se a orientação cita um tema
  que nenhum guia abaixo traz, NÃO invente o conteúdo -- registre no
  bloco: "Citado no foco, sem conteúdo nos guias: <tema>".

## 3. Sem marca nos títulos

O guia inteiro é o foco: NÃO escreva `{foco}` nos títulos.

## 4. Destaque de trecho: `**Atenção da professora:**`

Quando a orientação destaca um PONTO específico dentro de um tema ("quero
chamar a atenção de vocês para dois crimes"), ponha junto do conteúdo
correspondente, no corpo, um parágrafo próprio (linha em branco antes):

```
**Atenção da professora:** "quero chamar a atenção de vocês para dois crimes cometidos durante esse período romano"
```

(`**Atenção do professor:**` se for professor.) Só com fala literal da
orientação, entre aspas -- dedução não vira destaque. É um rótulo novo,
não substitui o conteúdo: o conteúdo continua com a redação do guia.
"""


def _bloco_foco(lesson: Lesson) -> str:
    parts = [FOCO_INSTRUCTIONS]
    if lesson.exam is not None:
        parts.append(f"Prova ligada a este guia: **{lesson.exam.titulo}**, em {lesson.exam.data:%d/%m/%Y}.\n")
    else:
        parts.append("Nenhuma prova cadastrada ligada a este guia -- o foco é o que a orientação disser.\n")
    parts.append("## ORIENTAÇÃO (como o usuário passou)\n")
    parts.append("<<<INÍCIO ORIENTAÇÃO>>>\n" + (lesson.foco_orientacao or "").strip() + "\n<<<FIM ORIENTAÇÃO>>>\n")
    return "\n".join(parts)


def build_pacote(session: Session, lesson: Lesson) -> str:
    if lesson.tipo != TIPO:
        raise ProcessingError("esta aula não é uma consolidação")
    fontes = fontes_de(session, lesson)
    if not fontes:
        raise ProcessingError("consolidação sem aulas-fonte")
    parts = [
        f"# Consolidar guias — {lesson.subject.nome} — {lesson.titulo}\n",
        INSTRUCTIONS,
    ]
    if lesson.focado:
        parts.append(_bloco_foco(lesson))
    parts += [
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
_ROTULOS = {
    "lei",
    "definicao",
    "exemplo",
    "atencao",
    "atencao da professora",
    "atencao do professor",
    "pergunta de aluno",
    "aluno",
    "material da aula",
}


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


_FOCO_TITULO_RE = re.compile(r"^##[ \t]+foco deste guia[ \t#]*$", re.IGNORECASE)
_SECAO_RE = re.compile(r"^##[ \t]")


def separar_bloco_foco(md: str) -> tuple[str, str | None]:
    """Tira a seção `## Foco deste guia` do markdown (vai pra
    `Lesson.foco_md`, fora das seções: não é numerada nem narrada) e
    devolve (resto, corpo do bloco ou None)."""
    linhas = md.split("\n")
    inicio = next((i for i, line in enumerate(linhas) if _FOCO_TITULO_RE.match(line.strip())), None)
    if inicio is None:
        return md, None
    fim = next((j for j in range(inicio + 1, len(linhas)) if _SECAO_RE.match(linhas[j])), len(linhas))
    corpo = "\n".join(linhas[inicio + 1 : fim]).strip()
    resto = "\n".join(linhas[:inicio] + linhas[fim:])
    return resto, corpo or None


# Só no começo de parágrafo -- a mesma regra que faz o rótulo virar bloco
# na tela (markdown_render.py::wrap_labeled_blocks); fora disso o
# relatório contaria um destaque que ninguém vê.
_ATENCAO_RE = re.compile(r"(?:\A|\n[ \t]*\n)[ \t]*\*\*Aten[çc][ãa]o d[oa] professora?:\*\*", re.IGNORECASE)


def ingest_consolidacao(session: Session, lesson: Lesson, texto: str) -> dict:
    if lesson.tipo != TIPO:
        raise ProcessingError("esta aula não é uma consolidação")
    md = extrair_markdown(texto)
    if not md.startswith("# "):
        raise ProcessingError("resposta sem título (# ...) -- não parece o guia consolidado")
    md, foco_md = separar_bloco_foco(md)
    md, marcados = extrair_marcas(md)
    if lesson.focado:
        if not foco_md:
            raise ProcessingError("guia Focado sem a seção '## Foco deste guia'")
    elif foco_md or marcados:
        raise ProcessingError("esta consolidação não tem foco -- tire o bloco de foco e as marcas {foco}")
    lesson.foco_md = foco_md
    lesson.foco_marcas_json = json.dumps(marcados, ensure_ascii=False) if lesson.focado else None
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
    resultado = {
        "ok": True,
        "secoes": len(parsed.secoes),
        "subtitulos": len(re.findall(r"^### ", corpo_total, re.MULTILINE)),
        "conceitos": len(re.findall(r"^#### ", corpo_total, re.MULTILINE)),
        "relatorio": relatorio_termos([f.guia_md or "" for f in fontes], md),
    }
    if lesson.focado:
        numeradas = numerar_consolidado([(s.titulo, s.corpo) for s in parsed.secoes], marcados=frozenset(marcados))
        # Aviso, não bloqueio (mesmo espírito do relatório de termos): a
        # skill confere cada item da orientação contra esta lista.
        resultado["foco"] = {
            "marcados": titulos_marcados(numeradas),
            "atencao": len(_ATENCAO_RE.findall(corpo_total)),
        }
    return resultado

