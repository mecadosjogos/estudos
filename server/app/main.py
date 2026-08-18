from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .auth import session_middleware
from .routes import ai, admin, assuntos, jobs, lessons, pages, review, search, subjects, uploads

app = FastAPI(title="Estudos")

app.middleware("http")(session_middleware)

app.mount(
    "/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static"
)

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


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nDisallow: /"
