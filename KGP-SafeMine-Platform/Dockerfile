# KGP-SafeMine: one image for the Streamlit UI and the FastAPI service (compose picks the command).
# Build:  docker compose build        Run:  docker compose up -d        UI http://localhost:8501   API http://localhost:8000/docs
#
# What is in the image: the code (safemine/, app/), the Streamlit config and the pinned Python packages (requirements.lock,
# CPU-only torch). What is NOT in the image, on purpose: .env and API keys, the endpoint CA certificates (certs/), the
# search indexes and DuckDB (data_processed/) and downloaded models. Compose supplies them at run time, so the image
# holds no secret and no restricted data and can be shared or pushed to a registry as is.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/home/app/.cache/huggingface \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# runtime library torch needs for CPU threading; non-root user (uid 1000) owns the app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin app

WORKDIR /app

# dependencies first: this layer is cached until requirements.lock changes
COPY requirements.lock .
RUN pip install -r requirements.lock --extra-index-url https://download.pytorch.org/whl/cpu

COPY --chown=app:app safemine safemine
COPY --chown=app:app app app
COPY --chown=app:app .streamlit .streamlit

# mount points (compose binds the real folders here) and the Hugging Face cache for the reranker / tokenizer
RUN mkdir -p /app/data_processed /app/certs /app/models /home/app/.cache/huggingface \
    && chown -R app:app /app /home/app

USER app
EXPOSE 8000 8501

# default command = the UI; compose overrides it for the API
CMD ["streamlit", "run", "app/ui.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
