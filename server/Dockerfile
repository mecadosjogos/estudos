FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server server
COPY shared shared

WORKDIR /app/server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
