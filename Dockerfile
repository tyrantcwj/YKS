FROM python:3.12-slim

ARG APP_VERSION=dev
ARG APP_COMMIT=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION} \
    APP_COMMIT=${APP_COMMIT}

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY docker/yks-entrypoint.sh ./yks-entrypoint.sh
RUN pip install --no-cache-dir .
RUN printf '{"version":"%s","commit":"%s","builtAt":""}\n' "$APP_VERSION" "$APP_COMMIT" > /app/app-version.json \
    && sed -i 's/\r$//' /app/yks-entrypoint.sh \
    && chmod +x /app/yks-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=5).read()" || exit 1

CMD ["/app/yks-entrypoint.sh"]
