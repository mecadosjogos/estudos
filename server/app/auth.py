"""Login por usuário+senha, com cadastro pendente de aprovação (PLANO.md,
seção "Acesso" -- o "Convite" que ali foi deliberadamente adiado pro
pós-v1, agora construído).

Sessão continua sendo um cookie HttpOnly assinado (itsdangerous), válido
por 1 ano -- só troca a forma de obtê-lo: login em `/login`, não mais o
link mágico `?k=<TOKEN>`. `require_session_or_token` continua intocado
para os dois clientes de máquina (worker de transcrição, Atalho do iOS)
que não têm como fazer login interativo.
"""

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from . import config
from .db import get_session
from .models import User

_serializer = URLSafeTimedSerializer(config.SESSION_SECRET, salt="estudos-session")


class SessaoInvalida(Exception):
    """Levantada por require_session quando não há sessão válida -- um
    exception handler em main.py converte isto em redirect pra /login.
    require_session_or_token (worker/Atalho iOS) NUNCA levanta isto:
    esses clientes esperam um 401 puro, não uma página HTML de redirect."""


def make_session_cookie_value(user_id: int) -> str:
    return _serializer.dumps({"user_id": user_id})


def set_session_cookie(response, user_id: int, request: Request) -> None:
    response.set_cookie(
        config.SESSION_COOKIE_NAME,
        make_session_cookie_value(user_id),
        max_age=config.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )


def _read_session_user_id(request: Request) -> int | None:
    value = request.cookies.get(config.SESSION_COOKIE_NAME)
    if not value:
        return None
    try:
        data = _serializer.loads(value, max_age=config.SESSION_MAX_AGE)
    except BadSignature:
        return None
    return data.get("user_id")


def get_current_user(request: Request, session: Session) -> User | None:
    """Resolve o usuário da sessão, se houver -- e só se ainda estiver
    com acesso válido (aprovado, dentro do prazo). Revogar ou deixar
    vencer o acesso temporário de alguém já derruba a próxima requisição
    dessa pessoa, sem precisar de tabela de sessão nem job de limpeza."""
    user_id = _read_session_user_id(request)
    if user_id is None:
        return None
    user = session.get(User, user_id)
    if user is None or user.status != "aprovado":
        return None
    if user.expira_em is not None and user.expira_em <= datetime.now(timezone.utc):
        return None
    return user


def require_session(request: Request, session: Session = Depends(get_session)) -> User:
    user = get_current_user(request, session)
    if user is None:
        raise SessaoInvalida()
    request.state.user = user
    return user


def require_admin(user: User = Depends(require_session)) -> User:
    if user.papel != "admin":
        raise HTTPException(status_code=403, detail="Só administradores acessam esta página")
    return user


def require_session_or_token(request: Request, session: Session = Depends(get_session)) -> None:
    """Para endpoints chamados por clientes sem navegador (worker de
    transcrição, Atalho do iOS): aceita o cookie de sessão normal ou o
    cabeçalho `Authorization: Bearer <ACCESS_TOKEN>`."""
    if get_current_user(request, session) is not None:
        return
    header = request.headers.get("authorization", "")
    if config.ACCESS_TOKEN and header == f"Bearer {config.ACCESS_TOKEN}":
        return
    raise HTTPException(status_code=401, detail="Sessão inválida")
