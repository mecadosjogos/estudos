from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import SessaoInvalida
from .routes import (
    ai,
    admin,
    assuntos,
    destaques,
    dissertativas,
    exams,
    export,
    feynman,
    glossary,
    guia_exercicios,
    jobs,
    lessons,
    library,
    login,
    materials,
    pages,
    review,
    search,
    subjects,
    uploads,
)

app = FastAPI(title="Estudos")


@app.exception_handler(SessaoInvalida)
async def _sessao_invalida_handler(request: Request, exc: SessaoInvalida):
    return RedirectResponse(url="/login", status_code=303)


STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/static/service-worker.js")
def service_worker():
    """Rota dedicada (não a StaticFiles genérica) só para poder mandar
    `Service-Worker-Allowed` -- sem esse header, um script servido de
    /static/ não pode pedir escopo /revisao (fora do próprio diretório),
    e o navegador recusa silenciosamente o registro com esse scope."""
    return FileResponse(
        STATIC_DIR / "service-worker.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/revisao"},
    )


class _RevalidatingStaticFiles(StaticFiles):
    """Sem `Cache-Control`, o navegador aplica cache heurístico e segue
    servindo o style.css antigo depois de um deploy (achado real: guia com
    os blocos novos no HTML, mas sem o CSS deles na tela). `no-cache` não
    é "não guardar": o navegador guarda e revalida pelo ETag a cada uso --
    304 barato quando nada mudou, arquivo novo logo após o deploy."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", _RevalidatingStaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(login.router)
app.include_router(pages.router)
app.include_router(admin.router)
app.include_router(subjects.router)
app.include_router(lessons.router)
app.include_router(uploads.router)
app.include_router(uploads.api_router)
app.include_router(uploads.direct_router)
app.include_router(jobs.router)
app.include_router(search.router)
app.include_router(ai.router)
app.include_router(review.router)
app.include_router(assuntos.router)
app.include_router(materials.router)
app.include_router(library.router)
app.include_router(glossary.router)
app.include_router(feynman.router)
app.include_router(dissertativas.router)
app.include_router(guia_exercicios.router)
app.include_router(exams.router)
app.include_router(export.router)
app.include_router(destaques.router)


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nDisallow: /"
