import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, db
from ..auth import require_session
from ..db import get_session
from ..library.gdocs import build_create_doc_url, extract_doc_id, get_drive_client
from ..library.html_to_md import html_to_markdown
from ..models import (
    Assunto,
    AudioSegment,
    GuiaSecao,
    GuiaTopico,
    Lesson,
    LessonAssunto,
    Material,
    MaterialUse,
    Subject,
    Transcript,
    TranscriptionJob,
    TranscriptSegment,
)
from ..transcript_confidence import is_suspicious_segment
from .jobs import claim_job_by_id, ensure_pending_job, ingest_result

router = APIRouter(prefix="/lessons", dependencies=[Depends(require_session)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _pode_editar_audio(lesson: Lesson, latest_job: TranscriptionJob | None) -> bool:
    """Adicionar/excluir/reordenar segmento só é seguro antes da transcrição
    existir -- depois disso, mudar o áudio sem reprocessar deixaria a
    transcrição dessincronizada da fonte. Também bloqueado com job
    'claimed': o worker já baixou a lista de segmentos daquele momento, e
    editar durante a transcrição faria a mudança nunca chegar nela."""
    if lesson.transcript is not None:
        return False
    if latest_job is not None and latest_job.status == "claimed":
        return False
    return True


def _latest_job(session: Session, lesson_id: int) -> TranscriptionJob | None:
    return session.scalar(
        select(TranscriptionJob)
        .where(TranscriptionJob.lesson_id == lesson_id)
        .order_by(TranscriptionJob.criado_em.desc())
        .limit(1)
    )


@router.get("/{lesson_id}")
def lesson_detail(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    all_subjects = session.scalars(select(Subject).order_by(Subject.nome)).all()
    latest_job = _latest_job(session, lesson_id)

    materials = session.scalars(
        select(Material).join(MaterialUse, MaterialUse.material_id == Material.id).where(MaterialUse.lesson_id == lesson_id)
    ).all()

    criar_doc_url = None
    if lesson.subject.doc_modelo_id:
        titulo = f"{lesson.data.isoformat()} {lesson.titulo}"
        criar_doc_url = build_create_doc_url(lesson.subject.doc_modelo_id, titulo, lesson.subject.drive_folder_id)

    return templates.TemplateResponse(
        request,
        "lesson_detail.html",
        {
            "lesson": lesson,
            "all_subjects": all_subjects,
            "latest_job": latest_job,
            "materials": materials,
            "criar_doc_url": criar_doc_url,
            "pode_editar_audio": _pode_editar_audio(lesson, latest_job),
        },
    )


@router.post("/{lesson_id}/audio/{segment_id}/mover")
def move_audio_segment(
    lesson_id: int, segment_id: int, direcao: str = Form(...), session: Session = Depends(get_session)
):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    if not _pode_editar_audio(lesson, _latest_job(session, lesson_id)):
        raise HTTPException(status_code=409, detail="áudio não pode mais ser editado depois da transcrição")

    segments = sorted(lesson.audio_segments, key=lambda s: s.ordem)
    idx = next((i for i, s in enumerate(segments) if s.id == segment_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="segmento não encontrado")

    swap_idx = idx - 1 if direcao == "cima" else idx + 1
    if 0 <= swap_idx < len(segments):
        segments[idx].ordem, segments[swap_idx].ordem = segments[swap_idx].ordem, segments[idx].ordem
        session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}", status_code=303)


@router.post("/{lesson_id}/audio/{segment_id}/excluir")
def delete_audio_segment(lesson_id: int, segment_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    if not _pode_editar_audio(lesson, _latest_job(session, lesson_id)):
        raise HTTPException(status_code=409, detail="áudio não pode mais ser editado depois da transcrição")

    segment = session.get(AudioSegment, segment_id)
    if segment is None or segment.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="segmento não encontrado")

    Path(segment.storage_path).unlink(missing_ok=True)
    lesson.audio_segments.remove(segment)
    session.flush()

    # Renumera o que sobrou pra não deixar buraco na sequência.
    remaining = sorted(lesson.audio_segments, key=lambda s: s.ordem)
    for i, s in enumerate(remaining, start=1):
        s.ordem = i

    if not remaining:
        # Sem segmento nenhum, nenhum job pendente faz sentido -- evita o
        # worker reivindicar um job pra concatenar uma lista vazia.
        for job in lesson.jobs:
            if job.status == "pending":
                session.delete(job)

    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}", status_code=303)


@router.post("/{lesson_id}")
def update_lesson(
    lesson_id: int,
    titulo: str = Form(...),
    data: str = Form(...),
    google_doc_url: str = Form(""),
    session: Session = Depends(get_session),
):
    lesson = session.get(Lesson, lesson_id)
    if lesson is not None:
        lesson.titulo = titulo.strip()
        lesson.data = datetime.strptime(data, "%Y-%m-%d").date()
        lesson.google_doc_url = google_doc_url.strip() or None
        session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}", status_code=303)


@router.post("/{lesson_id}/material-aula")
def update_material_aula(
    lesson_id: int,
    texto: str = Form(""),
    session: Session = Depends(get_session),
):
    """Fonte em aula fora do áudio (lousa, anotações coladas por você) --
    texto primário, não artefato derivado, sem deriv_key. `.strip()` só
    tira borda; indentação interna do texto colado fica intacta."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is not None:
        lesson.material_aula_texto = texto.strip() or None
        session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}", status_code=303)


@router.post("/{lesson_id}/material-aula/buscar-link")
def fetch_material_aula_from_link(
    lesson_id: int,
    url: str = Form(...),
    session: Session = Depends(get_session),
):
    """Busca o conteúdo de um Google Doc colado e sobrescreve
    `material_aula_texto` -- alternativa a colar o texto direto, útil
    porque copiar/colar na mão perde a indentação de listas aninhadas (o
    clipboard "texto puro" do navegador não carrega isso; exportar via API
    e converter com html_to_markdown, sim). Mesmo cliente/conversão do
    sync de materiais (library/gdocs.py), sem virar Material/MaterialUse --
    é conteúdo de uma aula só."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")

    doc_id = extract_doc_id(url)
    if doc_id is None:
        return RedirectResponse(
            url=f"/lessons/{lesson_id}?erro_material=Link+n%C3%A3o+parece+um+Google+Doc",
            status_code=303,
        )

    try:
        client = get_drive_client()
        html = client.export_html(doc_id)
        texto = html_to_markdown(html)
    except Exception as exc:
        from urllib.parse import quote

        return RedirectResponse(
            url=f"/lessons/{lesson_id}?erro_material={quote(f'Falha ao buscar o doc: {exc}')}",
            status_code=303,
        )

    lesson.material_aula_url = url.strip()
    lesson.material_aula_texto = texto.strip() or None
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}", status_code=303)


@router.post("/{lesson_id}/move")
def move_lesson(lesson_id: int, subject_id: int = Form(...), session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is not None:
        # Cards e definições ligados à aula seguem por FK — não há nada para migrar
        # à parte, já que nenhum dos dois carrega subject_id próprio (ver PLANO.md,
        # Integridade #3: matéria não é atributo do trecho).
        lesson.subject_id = subject_id
        session.commit()
    return RedirectResponse(url=f"/subjects/{subject_id}", status_code=303)


@router.post("/{lesson_id}/iniciar-transcricao")
def start_transcription(lesson_id: int, session: Session = Depends(get_session)):
    """Botão manual pra quando a aula tem áudio mas nunca ganhou job — cobre
    tanto o caso raro (upload antigo, de antes do enfileiramento automático)
    quanto o caso comum de reprocessar do zero."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    if not lesson.audio_segments:
        raise HTTPException(status_code=400, detail="aula sem áudio")
    if lesson.transcript is not None and lesson.transcript.aprovado_em is not None:
        raise HTTPException(
            status_code=409,
            detail="transcrição aprovada — reabra a revisão antes de retranscrever",
        )

    ensure_pending_job(session, lesson_id, target="gpu_worker")
    return RedirectResponse(url=f"/lessons/{lesson_id}", status_code=303)


@router.post("/{lesson_id}/transcrever-na-vps")
def transcribe_on_vps(lesson_id: int, session: Session = Depends(get_session)):
    """Válvula de emergência (PLANO.md): quando nenhum worker de GPU está
    ligado, transcreve na própria CPU da VPS com modelo médio — mais lento e
    um pouco pior em termo técnico, mas acionado por você, nunca automático."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    if not lesson.audio_segments:
        raise HTTPException(status_code=400, detail="aula sem áudio")
    if lesson.transcript is not None and lesson.transcript.aprovado_em is not None:
        raise HTTPException(
            status_code=409,
            detail="transcrição aprovada — reabra a revisão antes de retranscrever",
        )

    job = ensure_pending_job(session, lesson_id, target="vps_cpu")

    threading.Thread(target=_run_vps_cpu_job, args=(job.id,), daemon=True).start()
    return RedirectResponse(url=f"/lessons/{lesson_id}", status_code=303)


def _run_vps_cpu_job(job_id: int) -> None:
    """Roda numa thread separada porque a transcrição em CPU é lenta (minutos
    a dezenas de minutos) e não pode bloquear o loop de eventos do FastAPI.
    Usa sua própria sessão de banco — nunca compartilhar sessão entre threads."""
    from shared.audio import compress_to_mp3, concat_audio_files
    from shared.transcriber import WhisperTranscriber

    session = db.holder.SessionLocal()
    work_dir = config.UPLOAD_STAGING_DIR / f"vps-job-{job_id}"
    try:
        job = claim_job_by_id(session, job_id, worker_name="vps-cpu")
        if job is None:
            return

        segments = sorted(job.lesson.audio_segments, key=lambda s: s.ordem)
        audio_paths = [Path(s.storage_path) for s in segments]

        work_dir.mkdir(parents=True, exist_ok=True)
        concatenated = work_dir / "concatenated.wav"
        concat_audio_files(audio_paths, concatenated)

        transcriber = WhisperTranscriber(
            model_size=config.WHISPER_VPS_MODEL,
            device="cpu",
            compute_type=config.WHISPER_VPS_COMPUTE_TYPE,
        )
        output = transcriber.transcribe(str(concatenated))

        mp3_path = work_dir / "audio.mp3"
        compress_to_mp3(concatenated, mp3_path)

        with mp3_path.open("rb") as f:
            ingest_result(
                session,
                job,
                engine=f"faster-whisper-{config.WHISPER_VPS_MODEL}-cpu",
                worker_name="vps-cpu",
                duration_s=output.duration_s,
                full_text=output.full_text,
                segments=[
                    {
                        "idx": s.idx,
                        "start_s": s.start_s,
                        "end_s": s.end_s,
                        "text": s.text,
                        "words": [
                            {"text": w.text, "start_s": w.start_s, "end_s": w.end_s, "probability": w.probability}
                            for w in s.words
                        ],
                    }
                    for s in output.segments
                ],
                mp3_bytes_iter=iter(lambda: f.read(1024 * 1024), b""),
            )
    except Exception as exc:  # noqa: BLE001 — job de fundo: erro vira status "failed", nunca some silencioso
        job = session.get(TranscriptionJob, job_id)
        if job is not None:
            job.status = "failed"
            job.error = str(exc)
            session.commit()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        session.close()


@router.get("/{lesson_id}/transcricao")
def lesson_transcript(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    """A leitura de verdade (fase 5): transcrição com player sincronizado —
    tocar um parágrafo pula o áudio, o trecho atual se destaca sozinho."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.transcript is None:
        raise HTTPException(status_code=404, detail="transcrição não encontrada")

    ordered_segments = lesson.transcript.segments  # já vem ordenado por idx (models.py)
    low_confidence_ids = {
        seg.id for i, seg in enumerate(ordered_segments) if is_suspicious_segment(ordered_segments, i)
    }
    segments_json = json.dumps(
        [
            {
                "idx": s.idx, "start_s": s.start_s, "end_s": s.end_s, "text": s.text,
                "low_confidence": s.id in low_confidence_ids,
            }
            for s in lesson.transcript.segments
        ]
    )
    return templates.TemplateResponse(
        request,
        "lesson_transcript.html",
        {
            "lesson": lesson,
            "transcript": lesson.transcript,
            "segments_json": segments_json,
            "low_confidence_ids": low_confidence_ids,
            "has_audio_file": (config.MEDIA_WEB_DIR / f"lesson-{lesson_id}.mp3").exists(),
            "aprovado": lesson.transcript.aprovado_em is not None,
        },
    )


@router.post("/{lesson_id}/transcricao/segments/{segment_id}")
def edit_transcript_segment(
    lesson_id: int, segment_id: int, texto: str = Form(...), session: Session = Depends(get_session)
):
    """Edição inline de um trecho (fase 8): o Whisper erra, e tudo que vem
    depois -- guia, aula editada, cards -- herda o erro se ninguém
    corrigir aqui primeiro. Bloqueado depois de aprovar (reabra a revisão
    pra editar de novo)."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.transcript is None:
        raise HTTPException(status_code=404, detail="transcrição não encontrada")

    segment = session.get(TranscriptSegment, segment_id)
    if segment is None or segment.transcript_id != lesson.transcript.id:
        raise HTTPException(status_code=404, detail="trecho não encontrado")

    if lesson.transcript.aprovado_em is not None:
        raise HTTPException(
            status_code=409, detail="transcrição aprovada — reabra a revisão antes de editar"
        )

    texto = texto.strip()
    if not texto:
        raise HTTPException(status_code=400, detail="texto não pode ficar vazio")

    segment.text = texto
    segment.editado_em = datetime.now(timezone.utc)

    # full_text é o que alimenta guia/aula editada/window.py -- sem
    # recompor aqui, a correção fica presa no segmento e nunca chega na IA.
    ordered = sorted(lesson.transcript.segments, key=lambda s: s.idx)
    lesson.transcript.full_text = " ".join(s.text for s in ordered)

    session.commit()
    return {"ok": True, "text": segment.text}


@router.post("/{lesson_id}/transcricao/aprovar")
def approve_transcript(lesson_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.transcript is None:
        raise HTTPException(status_code=404, detail="transcrição não encontrada")
    lesson.transcript.aprovado_em = datetime.now(timezone.utc)
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/transcricao", status_code=303)


@router.post("/{lesson_id}/transcricao/reabrir")
def reopen_transcript(lesson_id: int, session: Session = Depends(get_session)):
    """Único jeito de voltar a editar ou retranscrever depois de aprovar —
    de propósito um passo separado e explícito, não algo que outro botão
    faz de lambuja."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.transcript is None:
        raise HTTPException(status_code=404, detail="transcrição não encontrada")
    lesson.transcript.aprovado_em = None
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/transcricao", status_code=303)


@router.get("/{lesson_id}/transcricao.txt")
def download_transcript_txt(lesson_id: int, session: Session = Depends(get_session)):
    """Texto puro da transcrição, sem timestamp — mesma fonte do
    `scripts/export_transcript.py` (Transcript.full_text), só que pelo
    navegador em vez de `docker compose exec`."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.transcript is None:
        raise HTTPException(status_code=404, detail="transcrição não encontrada")

    filename = f"transcricao-{lesson_id}.txt"
    return PlainTextResponse(
        lesson.transcript.full_text,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{lesson_id}/guia")
def view_guia(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    import markdown as markdown_lib

    from ..assuntos import annotate_arvore_checklist, normalize_slug

    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.guia_md is None:
        raise HTTPException(status_code=404, detail="guia de aula não gerado ainda")

    secoes = session.scalars(
        select(GuiaSecao).where(GuiaSecao.lesson_id == lesson_id).order_by(GuiaSecao.ordem)
    ).all()

    # Aula processada antes da estruturação do guia (ou nunca reprocessada
    # desde então): sem GuiaSecao, cai no template antigo servindo
    # guia_md como sempre foi -- nenhuma aula precisa de conversão, ela só
    # "sobe" de versão quando reprocessada de verdade.
    if not secoes:
        guia_html = markdown_lib.markdown(lesson.guia_md, extensions=["extra"])
        return templates.TemplateResponse(request, "guia_legado.html", {"lesson": lesson, "guia_html": guia_html})

    topicos_rows = session.scalars(
        select(GuiaTopico)
        .where(GuiaTopico.lesson_id == lesson_id, GuiaTopico.orfao_em.is_(None))
        .order_by(GuiaTopico.ordem)
    ).all()
    secao_by_slug = {normalize_slug(s.titulo): s for s in secoes}

    topicos = []
    for numero, t in enumerate(topicos_rows, start=1):
        target = secao_by_slug.get(t.secao_alvo_slug) if t.secao_alvo_slug else None
        desatualizado = bool(t.secao_alvo_slug) and target is None
        if target is None:
            target = secoes[numero - 1] if numero - 1 < len(secoes) else secoes[-1]
        topicos.append(
            {
                "id": t.id,
                "numero": numero,
                "titulo": t.titulo,
                "secao_numero": secoes.index(target) + 1,
                "desatualizado": desatualizado,
            }
        )

    topicos_perdidos = session.scalars(
        select(GuiaTopico)
        .where(
            GuiaTopico.lesson_id == lesson_id,
            GuiaTopico.orfao_em.is_not(None),
            GuiaTopico.editado_em.is_not(None),
        )
        .order_by(GuiaTopico.ordem)
    ).all()

    secoes_view = [
        {
            "numero": i,
            "titulo": s.titulo,
            "html": markdown_lib.markdown(s.corpo, extensions=["extra"]),
            "audio_start_s": s.audio_start_s,
            "audio_end_s": s.audio_end_s,
        }
        for i, s in enumerate(secoes, start=1)
    ]

    accepted_slugs = set(
        session.scalars(
            select(Assunto.slug)
            .join(LessonAssunto, LessonAssunto.assunto_id == Assunto.id)
            .where(LessonAssunto.lesson_id == lesson_id, LessonAssunto.status == "aceito")
        )
    )
    arvore = annotate_arvore_checklist(json.loads(lesson.guia_arvore_json or "[]"), accepted_slugs)
    trechos_incompletos = json.loads(lesson.guia_trechos_incompletos_json or "[]")

    # Narração em áudio (TTS local via GPU, tts-service/): em dia quando
    # gerada depois da última vez que o guia mudou -- mesma comparação de
    # "carimbo de versão" que o resto do guia usa (nunca hash de conteúdo).
    # Um mp3 só pra aula inteira (toca contínuo, não recarrega arquivo por
    # seção); narração pode ser parcial (process_tts_job sobe o que
    # conseguiu narrar mesmo se uma seção falhar) -- por isso cada seção só
    # tem link de "ouvir esta seção" se `audio_start_s` estiver preenchido,
    # não só porque `guia_audio_gerado_em` está em dia.
    audio_pronto = (
        lesson.guia_audio_gerado_em is not None and lesson.guia_audio_gerado_em >= lesson.guia_gerado_em
    )

    ultimo_job_audio = session.scalar(
        select(TranscriptionJob)
        .where(TranscriptionJob.lesson_id == lesson_id, TranscriptionJob.target == "tts_guia")
        .order_by(TranscriptionJob.criado_em.desc())
        .limit(1)
    )
    audio_gerando = not audio_pronto and ultimo_job_audio is not None and ultimo_job_audio.status in (
        "pending",
        "claimed",
    )
    audio_falhou = not audio_pronto and ultimo_job_audio is not None and ultimo_job_audio.status == "failed"

    return templates.TemplateResponse(
        request,
        "guia.html",
        {
            "lesson": lesson,
            "arvore": arvore,
            "topicos": topicos,
            "topicos_perdidos": topicos_perdidos,
            "secoes": secoes_view,
            "trechos_incompletos": trechos_incompletos,
            "audio_pronto": audio_pronto,
            "audio_gerando": audio_gerando,
            "audio_falhou": audio_falhou,
            "audio_erro": ultimo_job_audio.error if audio_falhou else None,
        },
    )


@router.post("/{lesson_id}/guia/renarrar")
def renarrar_guia(lesson_id: int, session: Session = Depends(get_session)):
    """Recoloca só a narração (`tts_guia`) na fila -- sem tocar em guia_md,
    resumo, cards ou qualquer outro campo. Existe separado de "reprocessar
    a aula" porque a lógica de narração (limpeza de Markdown antes do TTS,
    voz, etc.) muda sem que o conteúdo do guia precise mudar junto -- nesses
    casos reprocessar com IA de novo seria desperdício e risco (reescreveria
    resumo/cards/mapa à toa). `ensure_pending_job` é idempotente: clicar de
    novo com um job já pendente não duplica."""
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.guia_md is None:
        raise HTTPException(status_code=404, detail="guia de aula não gerado ainda")
    ensure_pending_job(session, lesson_id, target="tts_guia")
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia", status_code=303)


@router.get("/{lesson_id}/guia/audio.mp3")
def guia_audio(lesson_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    path = config.GUIA_AUDIO_DIR / f"lesson-{lesson_id}" / "guia.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="áudio do guia não encontrado")
    return FileResponse(path, media_type="audio/mpeg")


@router.post("/{lesson_id}/guia/topicos/{topico_id}/secao-alvo")
def set_guia_topico_secao_alvo(
    lesson_id: int, topico_id: int, secao_ordem: int = Form(...), session: Session = Depends(get_session)
):
    """Correção manual do alvo do sumário: a IA numera sumário e seções na
    mesma ordem quase sempre, mas quando falha pra uma aula em particular,
    você aponta manualmente. Guardado pelo título normalizado da seção (não
    pelo número), porque GuiaSecao não tem identidade estável entre
    reprocessamentos -- ver ai/pipeline.py e models.py::GuiaTopico."""
    from ..assuntos import normalize_slug

    topico = session.get(GuiaTopico, topico_id)
    if topico is None or topico.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="tópico não encontrado")

    secoes = session.scalars(
        select(GuiaSecao).where(GuiaSecao.lesson_id == lesson_id).order_by(GuiaSecao.ordem)
    ).all()
    if secao_ordem < 1 or secao_ordem > len(secoes):
        raise HTTPException(status_code=400, detail="número de seção inválido")

    topico.secao_alvo_slug = normalize_slug(secoes[secao_ordem - 1].titulo)
    topico.editado_em = datetime.now(timezone.utc)
    session.commit()
    return RedirectResponse(url=f"/lessons/{lesson_id}/guia#topico-{topico.id}", status_code=303)


@router.get("/{lesson_id}/mapa")
def view_mapa(request: Request, lesson_id: int, session: Session = Depends(get_session)):
    from ..glossary.mermaid import link_mermaid_nodes_to_glossary

    lesson = session.get(Lesson, lesson_id)
    if lesson is None or not lesson.mapa_mermaid:
        raise HTTPException(status_code=404, detail="mapa de taxonomia não gerado ainda")

    mermaid_src = link_mermaid_nodes_to_glossary(lesson.mapa_mermaid, session)
    return templates.TemplateResponse(request, "mapa.html", {"lesson": lesson, "mermaid_src": mermaid_src})


@router.get("/{lesson_id}/guia.md")
def download_guia_md(lesson_id: int, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None or lesson.guia_md is None:
        raise HTTPException(status_code=404, detail="guia de aula não gerado ainda")

    filename = f"guia-aula-{lesson_id}.md"
    return PlainTextResponse(
        lesson.guia_md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{lesson_id}/audio")
def lesson_audio(lesson_id: int):
    path = config.MEDIA_WEB_DIR / f"lesson-{lesson_id}.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="áudio não encontrado")
    return FileResponse(path, media_type="audio/mpeg")


class PositionBody(BaseModel):
    posicao_s: float


@router.post("/{lesson_id}/posicao")
def save_position(lesson_id: int, body: PositionBody, session: Session = Depends(get_session)):
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="aula não encontrada")
    lesson.posicao_s = max(0.0, body.posicao_s)
    session.commit()
    return {"ok": True}
