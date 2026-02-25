FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates bash curl docker.io docker-cli \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app /app/app

ENV PYTHONUNBUFFERED=1
ENV PANEL_HOST=0.0.0.0
ENV PANEL_PORT=5100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5100"]
