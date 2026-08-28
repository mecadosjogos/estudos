"""Assunto -- global, atravessa materias e semestres (PLANO.md, fase 8).

Nasce com as mesmas ferramentas do glossario porque vai errar do mesmo
jeito: a IA propõe "Capacidade" numa aula e "Capacidade de Fato" noutra,
achando que são coisas diferentes -- sem fundir/renomear/separar desde o
início, em dois meses são 60 assuntos quase-iguais."""

import difflib
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Assunto, AssuntoCobertura, LessonAssunto


def normalize_slug(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "assunto"


def similar_slugs(slug: str, outros: list[str], *, threshold: float = 0.6, limit: int = 3) -> list[str]:
    """Candidatos a duplicata pra sugerir fusão na aprovação -- não é
    detecção de colisão (slug exato já é único no banco), é a IA propondo
    "Capacidade" numa aula e "Capacidade de Fato" noutra achando que são
    coisas diferentes. `difflib` sobre o slug, não Jaccard de tokens
    (ai/signals.py::_normalize_tokens): "negocio-juridico" x
    "negocios-juridicos" não compartilham token nenhum e zerariam ali; aqui
    pegam por razão de caracteres. O(n×m) -- roda uma vez por render da
    tela de aprovação, não é caminho quente."""
    scored = []
    for outro in outros:
        if outro == slug:
            continue
        if outro.startswith(slug + "-") or slug.startswith(outro + "-"):
            score = 1.0
        else:
            score = difflib.SequenceMatcher(None, slug, outro).ratio()
        if score >= threshold:
            scored.append((score, outro))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [outro for _, outro in scored[:limit]]


def annotate_arvore_checklist(nodes: list[dict], accepted_slugs: set[str]) -> list[dict]:
    """Marca folhas da árvore de conhecimento do guia sem Assunto aceito
    correspondente (checklist leve). Só folhas: nós intermediários são
    categorias que o professor usou pra organizar ("Direito público"), não
    tópicos estudáveis -- marcá-los geraria destaque constante, já que o
    padrão de "uma ou duas palavras por nó" faz a maioria deles nunca virar
    um Assunto de verdade. Casamento por slug exato (sem `similar_slugs`) --
    mais simples e evita marcar errado por aproximação; recalibra depois se
    sobrar ruído."""
    annotated = []
    for node in nodes:
        filhos = annotate_arvore_checklist(node.get("filhos", []), accepted_slugs)
        is_leaf = not filhos
        sem_assunto = is_leaf and normalize_slug(node["rotulo"]) not in accepted_slugs
        annotated.append({"rotulo": node["rotulo"], "filhos": filhos, "sem_assunto": sem_assunto})
    return annotated


def find_or_create_assunto(session: Session, titulo: str) -> Assunto:
    """Casamento por slug -- é o que impede duas grafias do mesmo assunto
    virarem dois registros (mesmo padrão do glossário)."""
    slug = normalize_slug(titulo)
    existing = session.scalar(select(Assunto).where(Assunto.slug == slug))
    if existing is not None:
        return existing
    assunto = Assunto(slug=slug, titulo=titulo.strip())
    session.add(assunto)
    session.flush()
    return assunto


def ensure_cobertura(
    session: Session, assunto_id: int, subject_id: int, origem: str = "ia", status: str = "dado"
) -> AssuntoCobertura:
    """Idempotente pra baixo, nunca pra cima: uma cobertura que já existe
    NUNCA é rebaixada (fase 14: importar a ementa, que sempre chama com
    `status="pendente"`, não pode derrubar uma cobertura que já veio de
    aula de volta pra "pendente"). Mas o inverso PODE acontecer -- se a
    cobertura existente estava "pendente" (só a ementa sabia do tópico) e
    esta chamada é `status="dado"` (uma aula de verdade acabou de
    confirmar o assunto), ela é promovida na hora. Sem isso, aceitar a
    proposta de uma aula pra um tópico que já estava na ementa deixaria a
    cobertura "pendente" pra sempre, mesmo já dada."""
    existing = session.scalar(
        select(AssuntoCobertura).where(
            AssuntoCobertura.assunto_id == assunto_id, AssuntoCobertura.subject_id == subject_id
        )
    )
    if existing is not None:
        if status == "dado" and existing.status == "pendente":
            existing.status = "dado"
        return existing
    cobertura = AssuntoCobertura(assunto_id=assunto_id, subject_id=subject_id, origem=origem, status=status)
    session.add(cobertura)
    session.flush()
    return cobertura


def merge_assuntos(session: Session, source_id: int, target_id: int) -> None:
    """Migra vínculos e coberturas de source pra target e apaga source --
    nada fica órfão (PLANO.md: 'fundir dois termos quase-duplicados e
    confirmar que tudo migrou')."""
    if source_id == target_id:
        return

    for link in session.scalars(select(LessonAssunto).where(LessonAssunto.assunto_id == source_id)):
        link.assunto_id = target_id

    target_subjects = {
        row.subject_id
        for row in session.scalars(select(AssuntoCobertura).where(AssuntoCobertura.assunto_id == target_id))
    }
    for cobertura in session.scalars(select(AssuntoCobertura).where(AssuntoCobertura.assunto_id == source_id)):
        if cobertura.subject_id in target_subjects:
            session.delete(cobertura)
        else:
            cobertura.assunto_id = target_id

    source = session.get(Assunto, source_id)
    session.delete(source)
    session.flush()
