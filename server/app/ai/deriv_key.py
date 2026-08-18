"""Chave de derivação (PLANO.md, Integridade #1): tipo + intervalo de origem
+ hash do conteúdo-fonte. É o que permite reprocessar sem duplicar nem
apagar o que você editou — sem uma identidade estável, só restariam dois
comportamentos ruins: apagar tudo ou inserir tudo de novo."""

import hashlib


def compute_deriv_key(tipo: str, start_s: float, end_s: float, source_text: str) -> str:
    normalized = " ".join(source_text.lower().split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"{tipo}:{start_s:.1f}-{end_s:.1f}:{digest}"
