FROM python:3.12-slim

# Sem isso, stdout do Python fica bufferizado dentro do container e os logs
# só aparecem em `docker logs` com atraso (ou nunca, se o buffer não encher)
# — inclusive tracebacks de erro, o que torna qualquer investigação às cegas.
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server server
COPY shared shared
COPY scripts scripts

# A partir daqui, nada disso é usado pelo servidor em si -- é conteúdo
# estático empacotado só pra GET /admin/instalar-worker.zip (bootstrap de
# uma máquina de worker nova). COPY .claude/skills, não .claude inteiro:
# o resto de .claude/ é estado de sessão local, nunca deveria entrar numa
# imagem (mesmo comentário já em .gitignore sobre isso).
COPY worker worker
COPY .claude/skills .claude/skills
COPY docs docs
COPY RUNBOOK.md PLANO.md CLAUDE.md .env.example ./
COPY disparar-skill.ps1 iniciar-servidor-testes.bat \
     processar-aulas.ps1 processar-aulas.bat \
     transcrever-paginas.ps1 transcrever-paginas.bat ./

WORKDIR /app/server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
