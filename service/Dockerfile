# syntax=docker/dockerfile:1.7
# PPE detection service image: Python 3.13 slim, ONNX Runtime on CPU, non-root.
#
#   docker build -t ppe-service:dev .
#
# Behind a TLS-intercepting proxy, pass its CA bundle as an optional BuildKit
# secret. It is mounted only for the RUN steps that download, and never copied
# into a layer:
#   docker build --secret id=extra_ca,src=/path/to/proxy-ca.crt -t ppe-service:dev .
# Without the secret the build uses the image's own CA store.

ARG PYTHON_IMAGE=python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

# 1. Dependencies from the hashed lock file into a virtualenv.
FROM ${PYTHON_IMAGE} AS deps
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
COPY requirements.lock /tmp/requirements.lock
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-deps --require-hashes -r /tmp/requirements.lock \
    && /opt/venv/bin/pip uninstall -y pip

# 2. The model, downloaded and refused unless its SHA-256 matches the manifest.
FROM ${PYTHON_IMAGE} AS model
# A local path, file:// or http(s):// location; empty means the manifest's source.
ARG MODEL_SOURCE=""
WORKDIR /build
COPY registry/manifest.json registry/manifest.json
COPY src/ppe_service/__init__.py src/ppe_service/registry.py src/ppe_service/
COPY scripts/fetch_model.py scripts/fetch_model.py
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi \
    && python scripts/fetch_model.py ${MODEL_SOURCE:+--source "$MODEL_SOURCE"}

# 3. Runtime: no build tools, no pip, non-root, model checksum checked again.
FROM ${PYTHON_IMAGE} AS runtime
LABEL org.opencontainers.image.title="ppe-service" \
      org.opencontainers.image.description="PPE detector (YOLOv8s, ONNX, 320 px, int8) behind FastAPI" \
      org.opencontainers.image.source="https://github.com/ZulfaqarHafez/ppe-serving"
RUN groupadd --system --gid 10001 ppe \
    && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin ppe
COPY --from=deps /opt/venv /opt/venv
WORKDIR /app
COPY registry/manifest.json registry/manifest.json
COPY scripts/fetch_model.py scripts/fetch_model.py
COPY src src
COPY --from=model /build/models/ppe_yolov8s_320_int8dyn.onnx models/ppe_yolov8s_320_int8dyn.onnx
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PPE_MODEL_PATH=/app/models/ppe_yolov8s_320_int8dyn.onnx \
    PPE_MANIFEST_PATH=/app/registry/manifest.json
# Second check, on the file that actually ships; byte-compile so a read-only
# root filesystem costs nothing at start.
RUN python scripts/fetch_model.py --verify-only models/ppe_yolov8s_320_int8dyn.onnx \
    && python -m compileall -q src
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2).status != 200)"]
# The server verifies the checksum a third time at start and exits 3 on a mismatch.
ENTRYPOINT ["python", "-m", "ppe_service"]
