"""Confere se um trecho que a IA diz ter tirado da resposta do aluno está
mesmo lá (PLANO.md, fase 13b: "feedback sem base na resposta é a falha nº 1
do feedback por IA"). O juiz é obrigado a citar o trecho ANTES de dar o
veredito; este módulo é o que torna essa citação verificável, em vez de
só mais um texto plausível.

Tolerante de propósito: o modelo local costuma trocar pontuação, caixa,
acento ou uma palavra no meio ao copiar -- isso não é inventar. Inventar é
citar uma frase que não existe. Por isso compara por PALAVRAS normalizadas
(sem acento, sem pontuação, minúsculas) e aceita uma janela da resposta
que case em >= LIMIAR_SEMELHANCA com o trecho."""

import re
import unicodedata
from difflib import SequenceMatcher

LIMIAR_SEMELHANCA = 0.8
# Trecho curto demais ("sim", "a posse") casa em qualquer lugar e não
# prova nada -- mas também não é invenção. Abaixo disso, só exige que as
# palavras apareçam em sequência exata.
MIN_PALAVRAS_FUZZY = 4


def _palavras(texto: str) -> list[str]:
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.findall(r"\w+", sem_acento.lower())


def trecho_existe(trecho: str, resposta: str) -> bool:
    """True se `trecho` aparece em `resposta`, com a tolerância descrita no
    topo do módulo. Trecho vazio não "existe" -- quem chama decide se
    vazio é aceitável (é, quando o veredito é "ausente")."""
    alvo = _palavras(trecho)
    if not alvo:
        return False
    texto = _palavras(resposta)
    if not texto:
        return False

    n = len(alvo)
    # Sequência exata de palavras: o caso comum, e o único aceito pra trecho curto.
    for i in range(len(texto) - n + 1):
        if texto[i : i + n] == alvo:
            return True
    if n < MIN_PALAVRAS_FUZZY:
        return False

    # Janelas de tamanho próximo ao do trecho (o modelo pode ter comido ou
    # acrescentado uma palavra ao copiar).
    for tamanho in {n - 1, n, n + 1}:
        if tamanho <= 0 or tamanho > len(texto):
            continue
        for i in range(len(texto) - tamanho + 1):
            if SequenceMatcher(None, alvo, texto[i : i + tamanho]).ratio() >= LIMIAR_SEMELHANCA:
                return True
    return False


# Palavras que não carregam conteúdo -- ficam de fora da sobreposição.
_VAZIAS = set("""
a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela pelos pelas para pra com sem
que se e ou mas nao sim como mais menos muito pouco ja ainda sua seu suas seus ele ela eles elas isso
isto esse essa este esta aquele aquela ser estar ter haver foi era sao esta estao tem pode deve caso
voce sua resposta ponto secao material explique explicar identifique identificar aplique aplicar
conclua concluir releia reler escreva escrever mostre mostrar porque pois quando onde qual quais
""".split())


def palavras_de_conteudo(texto: str) -> set[str]:
    return {p for p in _palavras(texto) if len(p) >= 4 and p not in _VAZIAS}


def entrega_o_ponto(texto: str, ponto: str, limiar: float = 0.5) -> bool:
    """True se `texto` repete boa parte do CONTEÚDO de `ponto` (fração das
    palavras de conteúdo do ponto que aparecem no texto). Usado pra não
    deixar uma sugestão ou o "o que a questão pede" entregar um ponto da
    rubrica que a pessoa ainda não descobriu -- a revelação gradual (pista
    -> seção -> ponto) é o que ensina, e o modelo local tende a atropelá-la."""
    alvo = palavras_de_conteudo(ponto)
    if not alvo:
        return False
    return len(alvo & palavras_de_conteudo(texto)) / len(alvo) >= limiar
