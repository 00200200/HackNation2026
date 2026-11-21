# Backend API. The frontend image lives in frontend/Dockerfile.
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0 \
    PATH="/app/.venv/bin:$PATH"

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY prawdowid ./prawdowid
# The corpus the search index is built from (`python -m prawdowid.index`), and the directory for the
# embedding model; compose.prod.yaml mounts a volume there so the model is downloaded only once.
COPY corpus/evidence.jsonl ./corpus/evidence.jsonl
ENV FASTEMBED_CACHE_PATH=/models \
    HF_HOME=/models/hf
RUN mkdir -p /models /var/lib/prawdowid && chown nobody /models /var/lib/prawdowid

USER nobody
EXPOSE 8000
# Only the frontend container reaches this port (not published), so trusting its
# X-Forwarded-For is safe; the rate limit then sees the real client IP.
CMD ["uvicorn", "prawdowid.app:app", "--host", "0.0.0.0", "--port", "8000", "--forwarded-allow-ips", "*"]
