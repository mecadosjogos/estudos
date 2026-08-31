"""Remonta o guia_md a partir dos campos estruturados (guia_titulo,
guia_arvore_json, GuiaSecao, GuiaTopico, guia_trechos_incompletos_json) --
chamado no fim do ingest pra manter Lesson.guia_md/guia_gerado_em como um
cache, no mesmo formato de sempre (título, árvore, sumário, corpo, trechos
incompletos), pra export/corpus.py, export/exam_export.py e a rota
/guia.md continuarem funcionando sem mudança nenhuma."""

from .schemas import GuiaArvoreNoOut, GuiaSecaoOut, GuiaTopicoOut


def _render_arvore(nodes: list[GuiaArvoreNoOut], nivel: int = 0) -> list[str]:
    lines = []
    for node in nodes:
        lines.append("  " * nivel + f"- {node.rotulo}")
        lines.extend(_render_arvore(node.filhos, nivel + 1))
    return lines


def build_guia_markdown(
    *,
    titulo: str,
    arvore: list[GuiaArvoreNoOut],
    topicos: list[GuiaTopicoOut],
    secoes: list[GuiaSecaoOut],
    trechos_incompletos: list[str],
) -> str:
    parts = [f"# {titulo}\n"]

    if arvore:
        parts.append("## Árvore de conhecimento\n")
        parts.append("\n".join(_render_arvore(arvore)) + "\n")

    if topicos:
        parts.append("## Sumário dos tópicos abordados\n")
        parts.append("\n".join(f"{i}. {t.titulo}" for i, t in enumerate(topicos, start=1)) + "\n")

    for i, secao in enumerate(secoes, start=1):
        parts.append(f"## {i}. {secao.titulo}\n")
        parts.append(secao.corpo.strip() + "\n")

    if trechos_incompletos:
        parts.append("## Trechos incompletos/inaudíveis\n")
        parts.append("\n".join(f"- {t}" for t in trechos_incompletos) + "\n")

    return "\n".join(parts).strip() + "\n"
