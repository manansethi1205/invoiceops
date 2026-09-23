FROM python:3.12-slim

WORKDIR /app
ARG INSTALL_DEV=false
ARG INSTALL_EVALUATION=false
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
       tesseract-ocr \
       tesseract-ocr-eng \
    && if [ "$INSTALL_EVALUATION" = "true" ]; then \
         apt-get install --no-install-recommends -y poppler-utils; \
       fi \
    && rm -rf /var/lib/apt/lists/*
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
COPY --from=ghcr.io/astral-sh/uv:0.8.0 /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY apps apps
COPY invoiceops invoiceops
COPY workers workers
RUN if [ "$INSTALL_EVALUATION" = "true" ]; then \
      uv sync --frozen --no-dev --group evaluation; \
    elif [ "$INSTALL_DEV" = "true" ]; then \
      uv sync --frozen; \
    else \
      uv sync --frozen --no-dev; \
    fi
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
COPY . .
RUN groupadd --gid 10001 invoiceops \
    && useradd --uid 10001 --gid 10001 --no-create-home \
       --home-dir /nonexistent --shell /usr/sbin/nologin invoiceops \
    && chown -R 10001:10001 /app
# A numeric runtime identity remains valid even if a container runtime cannot resolve /etc/passwd.
USER 10001:10001
