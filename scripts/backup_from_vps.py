"""Baixa um backup do banco (sem a tabela `user`) e o mp3 de cada aula da
VPS de produção, e grava dentro de data-backup/ neste repositório -- pra
que commit+push já sirva de versionamento de backup (decisão do usuário:
o conteúdo é "só conhecimento de curso", tudo bem ser público; a tabela
`user`, que carrega hash de senha, é removida antes de gravar).

Login por usuário+senha (não ACCESS_TOKEN -- esse é só a credencial de
máquina do worker/Atalho iOS, rotas diferentes). Uso:

    python scripts/backup_from_vps.py
    python scripts/backup_from_vps.py --server-url http://127.0.0.1:8000   # testar local primeiro

Credenciais via BACKUP_ADMIN_USERNAME/BACKUP_ADMIN_PASSWORD no .env da
raiz, ou perguntadas interativamente se ausentes -- nunca hardcoded aqui.
"""

import argparse
import getpass
import os
import sqlite3
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = REPO_ROOT / "data-backup"
DEFAULT_SERVER_URL = "https://drwyver.mecadosjogos.app.br"


def _log(msg: str) -> None:
    print(f"[backup] {msg}", flush=True)


def _login(client: httpx.Client, server_url: str) -> None:
    username = os.environ.get("BACKUP_ADMIN_USERNAME") or input("Usuário admin: ")
    password = os.environ.get("BACKUP_ADMIN_PASSWORD") or getpass.getpass("Senha: ")
    response = client.post(
        f"{server_url}/login", data={"username": username, "senha": password}, follow_redirects=False, timeout=30
    )
    if response.status_code != 303 or "estudos_session" not in client.cookies:
        raise SystemExit("Login falhou -- confira usuário/senha (ou se a conta tem papel admin).")
    _log(f"login ok como \"{username}\"")


def _download_database(client: httpx.Client, server_url: str) -> Path:
    dest = BACKUP_DIR / "estudos.db"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with client.stream("GET", f"{server_url}/admin/backups/latest.db", timeout=60) as response:
        response.raise_for_status()
        with dest.open("wb") as f:
            for chunk in response.iter_bytes(1024 * 1024):
                f.write(chunk)
    _log(f"banco baixado ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
    return dest


def _strip_user_table(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS user")
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()
    _log("tabela user removida da cópia (hash de senha não vai pro repositório)")


def _download_audio(client: httpx.Client, server_url: str) -> None:
    audio_dir = BACKUP_DIR / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    response = client.get(f"{server_url}/admin/lessons.json", timeout=30)
    response.raise_for_status()
    lessons = response.json()

    to_fetch = [l for l in lessons if l["has_audio"]]
    _log(f"{len(to_fetch)} aula(s) com áudio de {len(lessons)} no total")

    total_bytes = 0
    for lesson in to_fetch:
        dest = audio_dir / f"lesson-{lesson['id']}.mp3"
        with client.stream("GET", f"{server_url}/lessons/{lesson['id']}/audio", timeout=300) as resp:
            resp.raise_for_status()
            with dest.open("wb") as f:
                for chunk in resp.iter_bytes(1024 * 1024):
                    f.write(chunk)
        size = dest.stat().st_size
        total_bytes += size
        _log(f"  aula {lesson['id']} \"{lesson['titulo']}\" ({size / 1024 / 1024:.1f} MB)")

    _log(f"áudio total: {total_bytes / 1024 / 1024:.1f} MB")

    # Aulas que perderam o mp3 (ex.: reprocessadas, id mudou) não devem
    # deixar arquivo órfão no repositório.
    valid_names = {f"lesson-{l['id']}.mp3" for l in to_fetch}
    for existing in audio_dir.glob("lesson-*.mp3"):
        if existing.name not in valid_names:
            existing.unlink()
            _log(f"  removido (não existe mais na VPS): {existing.name}")


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")

    parser = argparse.ArgumentParser(description="Backup da VPS pro repositório")
    parser.add_argument("--server-url", default=None, help="default: produção")
    args = parser.parse_args()

    server_url = (args.server_url or os.environ.get("SERVER_URL") or DEFAULT_SERVER_URL).rstrip("/")
    _log(f"servidor: {server_url}")

    with httpx.Client() as client:
        _login(client, server_url)
        db_path = _download_database(client, server_url)
        _strip_user_table(db_path)
        _download_audio(client, server_url)

    _log("pronto. Revise e publique quando quiser:")
    _log("  git add data-backup")
    _log('  git commit -m "Atualiza backup de dados"')
    _log("  git push")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        sys.exit(f"[backup] Falhou: {exc.response.status_code} em {exc.request.url}")
