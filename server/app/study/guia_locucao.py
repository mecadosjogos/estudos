"""Locução do "Dominar o guia": o texto falado da pergunta e da resposta de
cada exercício, e o controle de quais áudios (narrados pelo TTS local --
tts-service/, alvo `tts_exercicios` da fila) estão em dia.

O texto falado é montado AQUI, no servidor, e é o mesmo que vai pro
Chatterbox (worker/main.py::process_tts_exercicios_job) e pra voz do
navegador enquanto o mp3 não existe -- uma fonte só, então o que se ouve
no fallback é exatamente o que o áudio definitivo vai dizer.

Um mp3 vale enquanto o hash guardado na questão
(`GuiaExercicio.audio_*_hash`) bate com o hash do texto falado atual --
mesma ideia da chave de derivação (PLANO.md, "Integridade"): editar a
questão ou mudar uma regra de fala abaixo deixa o áudio velho sozinho, e o
próximo pedido de locução o refaz.
"""

import hashlib
import json
import re
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from ..models import GuiaExercicio, GuiaExercicioProgresso
from shared.text import texto_para_fala  # depois de `config`, que põe a raiz do repo no sys.path

PARTES = ("pergunta", "resposta")

# Quantos áudios um job `tts_exercicios` narra antes de devolver a GPU.
# Uma aula tem centenas de questões (~2 áudios cada); narrar tudo num job
# só seguraria a GPU por uma hora, com transcrição nova esperando atrás.
# Em lotes, a fila do worker volta a olhar gpu_worker entre um e outro --
# e `concluir` reenfileira o resto sozinho (routes/jobs.py).
LOTE_MAXIMO = 40

_LACUNA_RE = re.compile(r"_{2,}")

_ORDINAIS = (
    "Primeiro", "Segundo", "Terceiro", "Quarto", "Quinto",
    "Sexto", "Sétimo", "Oitavo", "Nono", "Décimo",
)


def _flatten_arvore(node: dict, prefix: str = "") -> list[str]:
    if not isinstance(node, dict):
        return []
    lines = [f"{prefix}{node.get('rotulo', '')}"]
    for filho in node.get("filhos", []) or []:
        lines.extend(_flatten_arvore(filho, prefix + "— "))
    return lines


def gabarito_lines(tipo: str, gabarito: dict) -> list[str]:
    """Linhas do gabarito como aparecem na tela da prática."""
    if tipo == "definicao":
        return [gabarito.get("resposta", "")]
    if tipo == "cloze":
        respostas = gabarito.get("respostas", [])
        # Compat com exercícios gerados antes desta correção, que
        # guardavam a frase com lacuna aqui em vez de em `pergunta`.
        linhas = [gabarito["texto_com_lacunas"]] if gabarito.get("texto_com_lacunas") else []
        if respostas:
            linhas.append("Respostas: " + ", ".join(respostas))
        return linhas
    if tipo == "lista_ordenada":
        return [f"{i + 1}. {item}" for i, item in enumerate(gabarito.get("itens_em_ordem", []))]
    if tipo == "hierarquia":
        return _flatten_arvore(gabarito.get("arvore_alvo", {}))
    if tipo == "discriminacao":
        linhas = [f"{gabarito.get('termo_a', '')} × {gabarito.get('termo_b', '')}"]
        if gabarito.get("eixo"):
            linhas.append(gabarito["eixo"])
        return linhas
    if tipo == "recordacao_livre":
        return gabarito.get("pontos_esperados", [])
    if tipo == "aplicacao_caso":
        linhas = [gabarito.get("caso", "")]
        if gabarito.get("conceito_correto"):
            linhas.append("Conceito correto: " + gabarito["conceito_correto"])
        return linhas
    return [json.dumps(gabarito, ensure_ascii=False)]


# --- texto falado ----------------------------------------------------------


def _limpar_para_fala(texto: str) -> str:
    # A mesma limpeza da narração do guia (shared/text.py): um símbolo que
    # o TTS lê errado lá lê errado aqui também.
    return texto_para_fala(texto)


def _frases(partes: list[str]) -> str:
    """Junta trechos em frases, sem ponto dobrado quando o trecho já fecha."""
    limpos = [p.strip() for p in partes if p and p.strip()]
    return " ".join(p if p[-1] in ".!?:;" else p + "." for p in limpos)


def _falar_arvore(node: dict) -> list[str]:
    """Cada nó com filhos vira uma frase "nó: filho, filho, filho." --
    falar a lista achatada com travessões não dá pra acompanhar de ouvido."""
    if not isinstance(node, dict):
        return []
    filhos = [f for f in node.get("filhos", []) or [] if isinstance(f, dict)]
    if not filhos:
        return []
    frases = [f"{node.get('rotulo', '')}: " + ", ".join(f.get("rotulo", "") for f in filhos)]
    for filho in filhos:
        frases.extend(_falar_arvore(filho))
    return frases


def texto_pergunta(exercicio: GuiaExercicio) -> str:
    return _limpar_para_fala(_LACUNA_RE.sub(" lacuna ", exercicio.pergunta))


def texto_resposta(exercicio: GuiaExercicio) -> str:
    tipo = exercicio.tipo
    gabarito = json.loads(exercicio.gabarito_json)

    if tipo == "cloze":
        # Só os termos das lacunas, como na tela. Ler a frase inteira
        # preenchida soava como a pergunta sendo lida de novo antes da
        # resposta. Sem `texto_com_lacunas` (formato antigo): a frase dele
        # é a pergunta, não a resposta.
        respostas = [r for r in gabarito.get("respostas", []) if r and r.strip()]
        rotulo = "Resposta: " if len(respostas) == 1 else "Respostas: "
        texto = _frases([rotulo + ", ".join(respostas)]) if respostas else ""
    elif tipo == "lista_ordenada":
        itens = gabarito.get("itens_em_ordem", [])
        texto = _frases(
            [f"{_ORDINAIS[i] if i < len(_ORDINAIS) else f'Item {i + 1}'}: {item}" for i, item in enumerate(itens)]
        )
    elif tipo == "hierarquia":
        texto = _frases(_falar_arvore(gabarito.get("arvore_alvo", {})))
    elif tipo == "aplicacao_caso":
        # O conceito é a resposta; o caso comentado vem depois, como explicação.
        texto = _frases([gabarito.get("conceito_correto", ""), gabarito.get("caso", "")])
    else:
        texto = _frases(gabarito_lines(tipo, gabarito))
    return _limpar_para_fala(texto)


def texto_falado(exercicio: GuiaExercicio, parte: str) -> str:
    return texto_pergunta(exercicio) if parte == "pergunta" else texto_resposta(exercicio)


# Entra no hash junto com o texto: subir a versão invalida todos os mp3 de
# uma vez quando o que muda é o jeito de narrar, não o texto. 2: o
# tts-service passou a descartar o balbucio que o Chatterbox gerava depois
# do fim do texto -- áudios da versão 1 podem tê-lo.
VERSAO_VOZ = 2


def hash_fala(texto: str) -> str:
    return hashlib.sha256(f"v{VERSAO_VOZ}\n{texto}".encode("utf-8")).hexdigest()[:16]


# --- áudio em disco ------------------------------------------------------------


def caminho_audio(lesson_id: int, exercicio_id: int, parte: str) -> Path:
    return config.GUIA_AUDIO_DIR / f"lesson-{lesson_id}" / "exercicios" / f"{exercicio_id}-{parte}.mp3"


def _hash_guardado(exercicio: GuiaExercicio, parte: str) -> str | None:
    return exercicio.audio_pergunta_hash if parte == "pergunta" else exercicio.audio_resposta_hash


def registrar_audio(exercicio: GuiaExercicio, parte: str, hash_: str) -> None:
    if parte == "pergunta":
        exercicio.audio_pergunta_hash = hash_
    else:
        exercicio.audio_resposta_hash = hash_


def audio_em_dia(exercicio: GuiaExercicio, parte: str) -> bool:
    guardado = _hash_guardado(exercicio, parte)
    return (
        guardado is not None
        and guardado == hash_fala(texto_falado(exercicio, parte))
        and caminho_audio(exercicio.lesson_id, exercicio.id, parte).exists()
    )


def audio_url(exercicio: GuiaExercicio, parte: str) -> str | None:
    """URL do mp3, ou None se não houver áudio em dia. O `?v=` muda junto
    com o texto, então o navegador nunca toca um mp3 velho do cache."""
    if not audio_em_dia(exercicio, parte):
        return None
    return (
        f"/lessons/{exercicio.lesson_id}/guia/exercicios/{exercicio.id}/audio/{parte}.mp3"
        f"?v={_hash_guardado(exercicio, parte)}"
    )


def itens_pendentes(session: Session, lesson_id: int, limite: int | None = None) -> list[dict]:
    """Áudios que faltam (ou ficaram velhos) nas questões aceitas da aula.
    Questões que estão na mesa de alguém vêm primeiro, pela posição em que
    voltam -- a questão da tela e as próximas ficam prontas antes do resto."""
    proxima_posicao = (
        select(
            GuiaExercicioProgresso.exercicio_id,
            func.min(GuiaExercicioProgresso.posicao_alvo).label("posicao"),
        )
        .where(GuiaExercicioProgresso.na_mesa.is_(True))
        .group_by(GuiaExercicioProgresso.exercicio_id)
        .subquery()
    )
    linhas = session.execute(
        select(GuiaExercicio, proxima_posicao.c.posicao)
        .outerjoin(proxima_posicao, proxima_posicao.c.exercicio_id == GuiaExercicio.id)
        .where(
            GuiaExercicio.lesson_id == lesson_id,
            GuiaExercicio.status == "aceito",
            GuiaExercicio.orfao_em.is_(None),
        )
        .order_by(proxima_posicao.c.posicao.is_(None), proxima_posicao.c.posicao, GuiaExercicio.id)
    ).all()

    itens: list[dict] = []
    for exercicio, _posicao in linhas:
        for parte in PARTES:
            if audio_em_dia(exercicio, parte):
                continue
            texto = texto_falado(exercicio, parte)
            itens.append({"exercicio_id": exercicio.id, "parte": parte, "texto": texto, "hash": hash_fala(texto)})
            if limite is not None and len(itens) >= limite:
                return itens
    return itens
