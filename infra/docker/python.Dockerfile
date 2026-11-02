# Imagen de la API y del worker (§5 Operación). La misma imagen sirve a ambos:
# docker-compose cambia solo el comando, así API y worker usan exactamente el mismo código.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TF_CPP_MIN_LOG_LEVEL=2 \
    NEUROLAB_HOST=0.0.0.0 \
    NEUROLAB_DATA_DIR=/data

WORKDIR /app

COPY services/api/requirements.txt services/api/requirements.txt
RUN pip install --no-cache-dir -r services/api/requirements.txt

COPY services/api services/api
COPY workers workers
COPY infra/migrations infra/migrations

# Proceso sin privilegios; /data es el volumen de datasets y artefactos.
RUN useradd --create-home --uid 10001 neurolab && mkdir -p /data && chown neurolab /data
USER neurolab

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')" || exit 1

CMD ["python", "services/api/app/main.py"]
