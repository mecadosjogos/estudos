from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..auth import get_current_user, require_session, set_session_cookie
from ..db import get_session
from ..models import User
from ..security import hash_password, verify_password

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _url_escape(text: str) -> str:
    from urllib.parse import quote

    return quote(text[:200])


@router.get("/login")
def login_form(request: Request, session: Session = Depends(get_session)):
    if get_current_user(request, session) is not None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    senha: str = Form(...),
    session: Session = Depends(get_session),
):
    user = session.scalar(select(User).where(User.username == username.strip()))

    # Mensagem genérica pra usuário inexistente ou senha errada -- de
    # propósito, pra não deixar um visitante descobrir por tentativa se um
    # username existe.
    if user is None or not verify_password(senha, user.senha_hash):
        erro = "Usuário ou senha incorretos."
    elif user.status == "pendente":
        erro = "Cadastro aguardando aprovação do administrador."
    elif user.status in ("recusado", "revogado"):
        erro = "Acesso não autorizado. Fale com o administrador."
    elif user.expira_em is not None and user.expira_em <= datetime.now(timezone.utc).replace(tzinfo=None):
        erro = "Acesso temporário expirado. Fale com o administrador."
    else:
        response = RedirectResponse(url="/", status_code=303)
        set_session_cookie(response, user.id, request)
        return response

    return RedirectResponse(url=f"/login?erro={_url_escape(erro)}", status_code=303)


@router.get("/registrar")
def registrar_form(request: Request, session: Session = Depends(get_session)):
    if get_current_user(request, session) is not None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "registrar.html", {})


@router.post("/registrar")
def registrar_submit(
    username: str = Form(...),
    senha: str = Form(...),
    confirmar_senha: str = Form(...),
    session: Session = Depends(get_session),
):
    username = username.strip()
    if not username or not senha:
        erro = "Preencha usuário e senha."
    elif senha != confirmar_senha:
        erro = "As senhas não coincidem."
    elif session.scalar(select(User.id).where(User.username == username)) is not None:
        erro = "Esse nome de usuário já existe."
    else:
        session.add(User(username=username, senha_hash=hash_password(senha), papel="usuario", status="pendente"))
        session.commit()
        return RedirectResponse(url="/login?cadastro=1", status_code=303)

    return RedirectResponse(url=f"/registrar?erro={_url_escape(erro)}", status_code=303)


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(config.SESSION_COOKIE_NAME)
    return response


@router.get("/conta/senha")
def trocar_senha_form(request: Request, user: User = Depends(require_session)):
    return templates.TemplateResponse(request, "trocar_senha.html", {})


@router.post("/conta/senha")
def trocar_senha_submit(
    senha_atual: str = Form(...),
    nova_senha: str = Form(...),
    confirmar_nova_senha: str = Form(...),
    user: User = Depends(require_session),
    session: Session = Depends(get_session),
):
    if not verify_password(senha_atual, user.senha_hash):
        erro = "Senha atual incorreta."
    elif nova_senha != confirmar_nova_senha:
        erro = "As senhas novas não coincidem."
    elif len(nova_senha) < 4:
        erro = "Senha nova muito curta."
    else:
        user.senha_hash = hash_password(nova_senha)
        session.commit()
        return RedirectResponse(url="/conta/senha?sucesso=1", status_code=303)

    return RedirectResponse(url=f"/conta/senha?erro={_url_escape(erro)}", status_code=303)
