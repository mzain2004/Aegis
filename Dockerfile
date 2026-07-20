# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Create a non-root user for security hardening
RUN groupadd -g 10001 vetoops && \
    useradd -r -u 10001 -g vetoops -d /app vetoops

COPY --chown=vetoops:vetoops . .

# Persist SQLite (and similar) under /app/data for container volume mounts.
RUN mkdir -p /app/data && chown -R vetoops:vetoops /app

USER vetoops

EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
