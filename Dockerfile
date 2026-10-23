# The AI service and workflows (Python): ingestion incl. OCR, matching, rules, chat, evidence crops.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-deu git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY config ./config
COPY world ./world
COPY heldout ./heldout
COPY evals ./evals
COPY models ./models
ENV BLE_ROOT=/app PYTHONUNBUFFERED=1
RUN useradd -m ble && mkdir -p /app/data /app/truth /app/reports /app/models && chown -R ble /app
USER ble
EXPOSE 8001
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')"
CMD ["ble", "serve", "--host", "0.0.0.0", "--port", "8001"]
