"""Autenticação por token único trocado por cookie de sessão (PLANO.md, seção Acesso).

Sem tela de login: o primeiro acesso é `/?k=<ACCESS_TOKEN>`. O servidor troca a chave
por um cookie HttpOnly assinado e redireciona removendo o `?k=` da URL, para não vazar
no histórico nem em `Referer`. Válido por 1 ano.
"""

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from starlette.responses import RedirectResponse

from . import config

_serializer = URLSafeTimedSerializer(config.SESSION_SECRET, salt="estudos-session")


def make_session_cookie_value(device: str = "admin") -> str:
    return _serializer.dumps({"device": device})


def verify_session_cookie(value: str | None) -> bool:
    if not value:
        return False
    try:
        _serializer.loads(value, max_age=config.SESSION_MAX_AGE)
        return True
    except BadSignature:
        return False


def has_valid_session(request: Request) -> bool:
    return verify_session_cookie(request.cookies.get(config.SESSION_COOKIE_NAME))


def require_session(request: Request) -> None:
    if not has_valid_session(request):
        raise HTTPException(status_code=401, detail="Sessão inválida — acesse com ?k=<token>")


def require_session_or_token(request: Request) -> None:
    """Para endpoints chamados por clientes sem navegador (Atalho do iOS): aceita
    o cookie de sessão normal ou o cabeçalho `Authorization: Bearer <ACCESS_TOKEN>`,
    que o Atalho consegue enviar sem passar pela troca de cookie."""
    if has_valid_session(request):
        return
    header = request.headers.get("authorization", "")
    if config.ACCESS_TOKEN and header == f"Bearer {config.ACCESS_TOKEN}":
        return
    raise HTTPException(status_code=401, detail="Sessão inválida")


async def session_middleware(request: Request, call_next):
    """Troca `?k=<TOKEN>` por cookie e redireciona limpando a URL.

    Roda antes de qualquer verificação de rota protegida.
    """
    token = request.query_params.get("k")
    if token is not None:
        if config.ACCESS_TOKEN and token == config.ACCESS_TOKEN:
            clean_path = request.url.path
            remaining = {k: v for k, v in request.query_params.items() if k != "k"}
            if remaining:
                from urllib.parse import urlencode

                clean_path = f"{clean_path}?{urlencode(remaining)}"
            response = RedirectResponse(url=clean_path)
            response.set_cookie(
                config.SESSION_COOKIE_NAME,
                make_session_cookie_value(),
                max_age=config.SESSION_MAX_AGE,
                httponly=True,
                samesite="lax",
                secure=request.url.scheme == "https",
            )
            return response
        # token presente mas inválido — segue sem autenticar, a rota protegida recusa

    return await call_next(request)
