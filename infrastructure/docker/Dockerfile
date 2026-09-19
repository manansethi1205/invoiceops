FROM python:3.12-slim

WORKDIR /app
ARG INSTALL_DEV=false
RUN apt-get update \
    && apt-get install --no-install-recommends -y tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
COPY --from=ghcr.io/astral-sh/uv:0.8.0 /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY apps apps
COPY invoiceops invoiceops
COPY workers workers
RUN if [ "$INSTALL_DEV" = "true" ]; then uv sync --frozen; else uv sync --frozen --no-dev; fi
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
COPY . .
RUN groupadd --system invoiceops \
    && useradd --system --gid invoiceops --home-dir /nonexistent --shell /usr/sbin/nologin invoiceops \
    && chown -R invoiceops:invoiceops /app
USER invoiceops
