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

WORKDIR /app/server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
