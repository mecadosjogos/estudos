"""Ordem de conteúdo dos exercícios do "Dominar o guia": a fila de prática
segue o índice do guia (seção por seção e, dentro dela, o trecho de onde
a questão saiu), com os tipos misturados como o conteúdo vier -- nunca
"todas as definições, depois todas as lacunas".

Antes a fila puxava o backlog por `criado_em`, ou seja, na ordem em que o
JSON da IA listou os exercícios. Bastou um lote sair agrupado por tipo
(bug real, aula 35: a regra de cobertura de definições fez o gerador
listar todas as definições primeiro) pra fila inteira ficar agrupada por
tipo. Agora a ordem é calculada aqui, pelo guia, e gravada em
`GuiaExercicio.ordem` -- a ordem do JSON só desempata dentro do mesmo
trecho.

Como cada exercício acha o seu lugar:
1. `secao_titulo` casa com um cabeçalho do guia (`##` da seção ou um
   `###`..`######` dentro dela), sem numeração e sem acento -- vale pro
   "2. Título" das aulas normais e pro "8.1 Título" da consolidação.
2. Dentro do trecho desse cabeçalho, o parágrafo que mais compartilha
   palavras raras com a pergunta + gabarito é a posição da questão (uma
   lacuna é a própria frase do guia; uma definição costuma repetir o
   texto dele). Sem cabeçalho reconhecido, procura no guia inteiro.
3. Recordação livre ("escreva tudo que lembra da seção") vai pro fim do
   trecho -- só faz sentido depois das questões pontuais dele.
"""

import json
import math
import re
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..assuntos import normalize_slug
from ..models import GuiaExercicio, GuiaSecao, Lesson

_SUB_RE = re.compile(r"^(#{3,6})[ \t]+(.+?)[ \t#]*$")
_FENCE_RE = re.compile(r"^ *(```|~~~)")
_NUMERACAO_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")
_PALAVRA_RE = re.compile(r"[a-z0-9]+")

# Palavras de enunciado ("escreva", "reconstrua"...) e de ligação: aparecem
# em qualquer parágrafo ou em qualquer pergunta, não dizem de onde a
# questão veio.
_IGNORAR = frozenset(
    """
    para como pelo pela pelos pelas mais menos quando qual quais sobre entre esse essa esses essas
    este esta estes estas isso isto aquele aquela aquilo cada todo toda todos todas tudo pode podem
    deve devem sendo seria sera nao sim tambem ainda apenas onde porque quem aula guia secao trecho
    escreva reconstrua memoria lembra lembre explique diga indique complete ordem diferenca qual
    conceito segundo exemplo caso responda resposta pergunta tipo forma modo
    """.split()
)

_SEM_LUGAR = 10**6


class _Bloco(NamedTuple):
    secao: int  # posição da seção no guia
    indice: int  # posição do bloco dentro da seção (0 = o próprio título)
    nivel: int | None  # 2..6 se o bloco é um cabeçalho, None se é parágrafo
    titulo: str | None  # título normalizado, só nos cabeçalhos
    palavras: frozenset[str]


class ExercicioParaOrdenar(NamedTuple):
    id: int
    tipo: str
    secao_titulo: str | None
    pergunta: str
    gabarito_json: str


def _norm_titulo(titulo: str) -> str:
    return normalize_slug(_NUMERACAO_RE.sub("", titulo.strip().lstrip("#").strip()))


def _palavras(texto: str) -> frozenset[str]:
    texto = normalize_slug(texto).replace("-", " ")
    return frozenset(p for p in _PALAVRA_RE.findall(texto) if len(p) >= 4 and p not in _IGNORAR)


def _textos(valor) -> list[str]:
    """Todo texto de dentro do gabarito, qualquer que seja o formato do
    tipo (resposta, lista de lacunas, árvore, caso...)."""
    if isinstance(valor, str):
        return [valor]
    if isinstance(valor, dict):
        return [t for v in valor.values() for t in _textos(v)]
    if isinstance(valor, list):
        return [t for v in valor for t in _textos(v)]
    return []


def _blocos(secoes: list[tuple[str, str]]) -> list[_Bloco]:
    """O guia picado em cabeçalhos e parágrafos, na ordem de leitura."""
    blocos: list[_Bloco] = []
    for s, (titulo, corpo) in enumerate(secoes):
        da_secao = [_Bloco(s, 0, 2, _norm_titulo(titulo), _palavras(titulo))]
        paragrafo: list[str] = []
        in_fence = False

        def fechar():
            if paragrafo:
                da_secao.append(_Bloco(s, len(da_secao), None, None, _palavras("\n".join(paragrafo))))
                paragrafo.clear()

        for linha in corpo.split("\n"):
            if _FENCE_RE.match(linha):
                in_fence = not in_fence
            m = None if in_fence else _SUB_RE.match(linha)
            if m:
                fechar()
                da_secao.append(
                    _Bloco(s, len(da_secao), len(m.group(1)), _norm_titulo(m.group(2)), _palavras(m.group(2)))
                )
            elif not linha.strip() and not in_fence:
                fechar()
            else:
                paragrafo.append(linha)
        fechar()
        blocos.extend(da_secao)
    return blocos


def _trecho(blocos: list[_Bloco], cabecalho: _Bloco) -> list[_Bloco]:
    """Os blocos sob um cabeçalho: até o próximo cabeçalho de nível igual
    ou mais raso, sem sair da seção."""
    trecho = [cabecalho]
    for b in blocos[blocos.index(cabecalho) + 1 :]:
        if b.secao != cabecalho.secao or (b.nivel is not None and b.nivel <= cabecalho.nivel):
            break
        trecho.append(b)
    return trecho


def ordenar(secoes: list[tuple[str, str]], exercicios: list[ExercicioParaOrdenar]) -> list[int]:
    """`secoes` = [(título, corpo)] na ordem do guia; `exercicios` na ordem
    de desempate (a do lote gerado). Devolve os ids na ordem do conteúdo."""
    blocos = _blocos(secoes)
    # título normalizado -> cabeçalhos com esse título, na ordem do guia.
    # Lista, não valor único: "Conceito" se repete em várias seções.
    cabecalhos: dict[str, list[_Bloco]] = {}
    for b in blocos:
        if b.titulo is not None:
            cabecalhos.setdefault(b.titulo, []).append(b)

    # Peso de cada palavra = quão rara ela é no guia: "abolitio" aponta o
    # parágrafo; "pena" aparece em metade deles e quase não decide nada.
    df: dict[str, int] = {}
    for b in blocos:
        for p in b.palavras:
            df[p] = df.get(p, 0) + 1
    total = max(len(blocos), 1)

    def pontos(palavras: frozenset[str], bloco: _Bloco) -> float:
        return sum(math.log(1 + total / df[p]) for p in palavras & bloco.palavras)

    chaves: dict[int, tuple] = {}
    for desempate, ex in enumerate(exercicios):
        try:
            gabarito = json.loads(ex.gabarito_json)
        except (TypeError, ValueError):
            gabarito = None
        palavras = _palavras(" ".join([ex.pergunta.replace("_", " "), *_textos(gabarito)]))

        trechos = [_trecho(blocos, c) for c in cabecalhos.get(_norm_titulo(ex.secao_titulo or ""), [])]
        if not trechos:
            trechos = [blocos]

        melhor: tuple[float, _Bloco, list[_Bloco]] | None = None
        for trecho in trechos:
            for b in trecho:
                p = pontos(palavras, b)
                if melhor is None or p > melhor[0]:
                    melhor = (p, b, trecho)

        if melhor is None or (melhor[0] == 0 and trechos[0] is blocos):
            chaves[ex.id] = (_SEM_LUGAR, 0, 0, desempate)
            continue
        pontuacao, bloco, trecho = melhor
        if pontuacao == 0:
            bloco = trecho[0]
        if ex.tipo == "recordacao_livre" and trecho is not blocos:
            chaves[ex.id] = (trecho[-1].secao, trecho[-1].indice, 1, desempate)
        else:
            chaves[ex.id] = (bloco.secao, bloco.indice, 0, desempate)

    return sorted(chaves, key=chaves.__getitem__)


_H2_RE = re.compile(r"^##[ \t]+(.+?)[ \t#]*$")
# Cabeçalhos do guia que não são conteúdo: a árvore e o sumário citam a
# aula inteira e puxariam qualquer questão pro começo.
_FORA_DO_CONTEUDO = ("arvore-de-conhecimento", "sumario")


def _secoes_do_markdown(guia_md: str) -> list[tuple[str, str]]:
    """Guia antigo (antes do guia estruturado) não tem `GuiaSecao` -- só o
    `guia_md` inteiro. Pica pelos `##`, do mesmo jeito que a seção nasce
    no guia estruturado."""
    secoes: list[tuple[str, list[str]]] = []
    in_fence = False
    for linha in guia_md.split("\n"):
        if _FENCE_RE.match(linha):
            in_fence = not in_fence
        m = None if in_fence else _H2_RE.match(linha)
        if m:
            secoes.append((m.group(1), []))
        elif secoes:
            secoes[-1][1].append(linha)
    return [
        (titulo, "\n".join(corpo))
        for titulo, corpo in secoes
        if not _norm_titulo(titulo).startswith(_FORA_DO_CONTEUDO)
    ]


def reordenar_exercicios(session: Session, lesson: Lesson) -> int:
    """Grava `GuiaExercicio.ordem` (0..n-1) de todos os exercícios da aula
    pela ordem do guia. Não mexe em progresso de ninguém: o que já está na
    mesa continua lá; muda só a ordem em que o backlog entra. Não comita --
    quem chama decide. Devolve quantos exercícios foram ordenados."""
    secoes = [
        (s.titulo, s.corpo)
        for s in session.scalars(select(GuiaSecao).where(GuiaSecao.lesson_id == lesson.id).order_by(GuiaSecao.ordem))
    ] or _secoes_do_markdown(lesson.guia_md or "")
    linhas = list(
        session.scalars(
            select(GuiaExercicio).where(GuiaExercicio.lesson_id == lesson.id).order_by(GuiaExercicio.id)
        )
    )
    if not linhas:
        return 0
    por_id = {e.id: e for e in linhas}
    ids = ordenar(
        secoes,
        [ExercicioParaOrdenar(e.id, e.tipo, e.secao_titulo, e.pergunta, e.gabarito_json) for e in linhas],
    )
    for posicao, exercicio_id in enumerate(ids):
        por_id[exercicio_id].ordem = posicao
    session.flush()
    return len(ids)
