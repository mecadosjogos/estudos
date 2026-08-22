"""Monta o HTML da aula editada pra virar PDF (fase 14) -- reaproveita o
mesmo `glossary_html` já calculado pra tela (`routes/ai.py::edited_lesson`),
sem os elementos interativos (áudio, botões) que não fazem sentido no
papel."""

import html


def build_edited_lesson_html(lesson, blocks, glossary_html: dict[int, str]) -> str:
    parts = [f"<h1>{html.escape(lesson.titulo)}</h1>", f"<p class='muted'>{lesson.data.isoformat()}</p>"]
    if lesson.resumo:
        parts.append(f"<h2>Resumo</h2><p>{html.escape(lesson.resumo)}</p>")
    for block in blocks:
        badge = f"<span class='badge'>{html.escape(block.tipo)}</span>"
        texto = glossary_html.get(block.id, html.escape(block.texto))
        parts.append(f"<p>{badge}</p><p>{texto}</p>")
    return "".join(parts)
