"""Cliente do Google Drive/Docs, injetável (mesmo padrão de ai/client.py —
PLANO.md, Integridade: clientes externos atrás de interface, com fixtures
gravadas, senão os testes de sync/vinculação exigiriam credencial real).
A transcrição de páginas de livro (fase 10) não tem um cliente equivalente
— não usa a API de visão, usa o Claude Code lendo a foto direto (ver
RUNBOOK.md, "Transcrever páginas"). A implementação real deste cliente
usa Service Account
(setup único, sem login, sem token expirando — ver PLANO.md, "Google Docs").

Também mora aqui a orquestração da sync em si (`sync_drive_folder`): listar
os docs da pasta raiz + de cada matéria com `drive_folder_id` configurado,
pular o que não mudou desde a última vez (`gdoc_modified_time` já bate com
o `modifiedTime` da API — sync incremental, PLANO.md), converter pra
Markdown e tentar vincular. Sem scheduler embutido: um cron/systemd timer
batendo em `POST /materials/sync` a cada ~10 min é decisão de deploy, não
de código — mesma filosofia do botão manual de backup (fase 1).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Lesson, Material, MaterialUse, Subject
from .html_to_md import html_to_markdown
from .matcher import match_lesson, match_subject


@dataclass
class DriveFile:
    id: str
    name: str
    modified_time: datetime
    parents: list[str] = field(default_factory=list)


class GoogleDriveClient(ABC):
    @abstractmethod
    def list_docs(self, folder_id: str) -> list[DriveFile]:
        """Lista os Google Docs dentro de uma pasta. Não recursivo — "por
        pasta" no PLANO.md é o parent direto, sem varrer subpastas."""

    @abstractmethod
    def export_html(self, file_id: str) -> str:
        """Exporta o conteúdo do doc como HTML — fonte de `html_to_md.py`."""


class FakeGoogleDriveClient(GoogleDriveClient):
    """Para testes: devolve arquivos e HTML pré-cadastrados em vez de
    chamar a API do Drive de verdade."""

    def __init__(
        self,
        files_by_folder: dict[str, list[DriveFile]] | None = None,
        html_by_id: dict[str, str] | None = None,
    ):
        self.files_by_folder = files_by_folder or {}
        self.html_by_id = html_by_id or {}
        self.list_calls: list[str] = []
        self.export_calls: list[str] = []

    def list_docs(self, folder_id: str) -> list[DriveFile]:
        self.list_calls.append(folder_id)
        return self.files_by_folder.get(folder_id, [])

    def export_html(self, file_id: str) -> str:
        self.export_calls.append(file_id)
        return self.html_by_id.get(file_id, "")


class RealGoogleDriveClient(GoogleDriveClient):
    """Service Account (PLANO.md, "Google Docs"): `files.list` pedindo só
    id/name/modifiedTime/parents — uma chamada, resposta minúscula — e
    `files.export` em text/html pros Docs."""

    def __init__(self, service_account_json: str):
        import json

        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        info = json.loads(service_account_json)
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )
        self._service = build("drive", "v3", credentials=credentials)

    def list_docs(self, folder_id: str) -> list[DriveFile]:
        query = (
            f"'{folder_id}' in parents and "
            "mimeType = 'application/vnd.google-apps.document' and trashed = false"
        )
        results: list[DriveFile] = []
        page_token = None
        while True:
            response = (
                self._service.files()
                .list(q=query, fields="nextPageToken, files(id, name, modifiedTime, parents)", pageToken=page_token)
                .execute()
            )
            for f in response.get("files", []):
                results.append(
                    DriveFile(
                        id=f["id"],
                        name=f["name"],
                        modified_time=datetime.fromisoformat(f["modifiedTime"].replace("Z", "+00:00")),
                        parents=f.get("parents", []),
                    )
                )
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return results

    def export_html(self, file_id: str) -> str:
        content = self._service.files().export(fileId=file_id, mimeType="text/html").execute()
        return content.decode("utf-8") if isinstance(content, bytes) else content


def build_create_doc_url(modelo_id: str, titulo: str, folder_id: str | None) -> str:
    """Link de cópia de modelo (PLANO.md, "Google Docs") — nunca criação
    pela API: uma service account não tem cota de armazenamento e o Google
    recusa criar em conta pessoal. O link custa um toque e não tem essa
    fragilidade; criado o doc, a sync o encontra e vincula sozinha."""
    from urllib.parse import quote

    url = f"https://docs.google.com/document/d/{modelo_id}/copy?title={quote(titulo)}"
    if folder_id:
        url += f"&folderId={quote(folder_id)}"
    return url


def extract_doc_id(url: str) -> str | None:
    """Tira o file id de um link de Google Doc colado à mão (formatos
    .../document/d/<id>/edit, .../document/d/<id>/edit?tab=..., etc.)."""
    import re

    match = re.search(r"/document/d/([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else None


def get_drive_client() -> GoogleDriveClient:
    from .. import config

    if not config.GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON não configurado — sync do Drive indisponível")
    return RealGoogleDriveClient(config.GOOGLE_SERVICE_ACCOUNT_JSON)


def _same_moment(a: datetime | None, b: datetime | None) -> bool:
    """Compara instantes ignorando timezone: o SQLite não guarda tzinfo em
    DateTime(timezone=True) -- reler um `gdoc_modified_time` salvo volta
    naive, e comparar direto contra o aware que a API devolve sempre daria
    falso, quebrando a sync incremental. A API do Drive só devolve UTC, e
    é isso que salvamos, então descartar o tzinfo dos dois lados é seguro."""
    if a is None or b is None:
        return a is b
    return a.replace(tzinfo=None) == b.replace(tzinfo=None)


def sync_drive_folder(session: Session, client: GoogleDriveClient, root_folder_id: str) -> dict:
    """Sincroniza a pasta raiz + a pasta de cada matéria aberta. Devolve um
    resumo (sincronizados/falhas/total) pra tela de estado."""
    subjects = list(session.scalars(select(Subject).where(Subject.encerrada_em.is_(None))))

    folder_ids = [root_folder_id] + [s.drive_folder_id for s in subjects if s.drive_folder_id]
    drive_files: dict[str, DriveFile] = {}
    for folder_id in folder_ids:
        for drive_file in client.list_docs(folder_id):
            drive_files[drive_file.id] = drive_file  # a mesma pasta pode aparecer 2x (raiz + subject)

    synced = failed = skipped = 0
    for drive_file in drive_files.values():
        existing = session.scalar(select(Material).where(Material.gdoc_id == drive_file.id))
        if existing is not None and _same_moment(existing.gdoc_modified_time, drive_file.modified_time):
            skipped += 1
            continue  # incremental: nada mudou desde a última sync

        material = existing or Material(origem="gdoc", gdoc_id=drive_file.id, titulo=drive_file.name)
        material.titulo = drive_file.name
        material.gdoc_modified_time = drive_file.modified_time
        material.synced_at = datetime.now(timezone.utc)

        try:
            html = client.export_html(drive_file.id)
            material.conteudo_md = html_to_markdown(html)
            material.status = "ok"
            material.sync_error = None
            material.indexado_em = datetime.now(timezone.utc)
            synced += 1
        except Exception as exc:
            # Um doc com erro (permissão revogada, exportação falhou) não
            # pode travar a sync dos outros — vira status "erro", visível
            # na página de estado, e a sync segue.
            material.status = "erro"
            material.sync_error = str(exc)
            failed += 1

        if existing is None:
            session.add(material)
        session.flush()

        _link_material(session, material, drive_file, subjects)

    session.commit()
    return {"synced": synced, "failed": failed, "skipped": skipped, "total": len(drive_files)}


def _link_material(session: Session, material: Material, drive_file: DriveFile, subjects: list[Subject]) -> None:
    already_linked = session.scalar(select(MaterialUse.id).where(MaterialUse.material_id == material.id))
    if already_linked is not None:
        return  # já tem vínculo (mesmo que só por matéria) -- não refaz nem sobrescreve escolha manual

    subject = match_subject(drive_file, subjects)
    if subject is None:
        return  # sem pasta reconhecida -- cai em "Não vinculados", resolve na mão

    lessons = list(session.scalars(select(Lesson).where(Lesson.subject_id == subject.id)))
    lesson = match_lesson(drive_file, lessons)
    session.add(MaterialUse(material_id=material.id, subject_id=subject.id, lesson_id=lesson.id if lesson else None))
