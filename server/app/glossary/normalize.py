"""Normalização de texto pro casamento do glossário (PLANO.md: "sem
acento, minúsculas, casadas em fronteira de palavra"). A função central
(`normalize_char_preserving`) normaliza **caractere a caractere**, nunca
a string inteira de uma vez — é o que garante que o resultado tem
exatamente o mesmo comprimento do original, então um span (start, end)
achado no texto normalizado aponta pro mesmo trecho no texto original,
sem precisar remapear índice nenhum.
"""

import unicodedata


def normalize_char_preserving(texto: str) -> str:
    """Cada caractere vira sua forma base em minúsculo (é -> e, ç -> c),
    preservando 1:1 a posição -- essencial pra depois aplicar o span
    achado aqui direto sobre o texto original, sem desalinhar."""
    saida = []
    for ch in texto:
        decomposto = unicodedata.normalize("NFKD", ch)
        base = "".join(c for c in decomposto if not unicodedata.combining(c))
        # Um caractere raro pode decompor em mais de um (ou nenhum) --
        # nesses casos mantém o original em minúsculo, pra nunca quebrar
        # a garantia de comprimento igual.
        saida.append(base.lower() if len(base) == 1 else ch.lower())
    return "".join(saida)
