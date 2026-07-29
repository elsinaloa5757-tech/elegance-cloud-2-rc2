FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ELEGANCE_ENV=production \
    ELEGANCE_DATA_DIR=/data

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system elegance \
    && adduser --system --ingroup elegance --home /app elegance \
    && mkdir -p /data \
    && chown -R elegance:elegance /app /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=elegance:elegance . .

USER elegance
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl --fail --silent http://127.0.0.1:${PORT:-8000}/api/system/status >/dev/null || exit 1
CMD ["sh","-c","uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
