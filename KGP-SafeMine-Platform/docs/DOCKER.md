# Running KGP-SafeMine in Docker

One image serves both the Streamlit UI (port 8501) and the FastAPI service (port 8000). **Secrets and data are never in the
image**: `.env`, the CA certificates, the search indexes and the restricted name list are mounted at run time, and
`.dockerignore` is an allowlist so none of them can be copied in by accident.

## Start

```bash
# 1. next to docker-compose.yml you need:
#      .env             API keys (copy .env.example). Set LLM_PROVIDER and the matching key.
#      certs/           CA certificate files for your endpoints, only if they use a self-signed TLS certificate (names set in .env)
#      data_processed/  chunks.jsonl, bm25.pkl, dense.npy, safemine.duckdb, events_index.csv (build it first: see the data section of the README)
docker compose build
docker compose up -d
docker compose ps          # both services should turn "healthy" (about 40 s)
```

UI: http://localhost:8501  ·  API docs: http://localhost:8000/docs  ·  logs: `docker compose logs -f ui`

The first question downloads the reranker and the tokenizer from Hugging Face (about 90 MB); they are cached in the
`hf-cache` volume, so later starts are fast. To work offline, run `make models` once so `./models` holds them.

## What each file does

| File | Role |
|---|---|
| `Dockerfile` | `python:3.14-slim`, non-root user (uid 1000), pinned packages from `requirements.lock` (CPU-only torch) |
| `requirements.lock` | exact versions resolved for Linux / CPython 3.14; regenerate after changing `requirements.txt` |
| `docker-compose.yml` | `ui` + `api` services, mounts, health checks, `no-new-privileges`, all capabilities dropped, ports on 127.0.0.1 only |
| `.dockerignore` | allowlist: only `safemine/`, `app/`, `.streamlit/` and `requirements.lock` enter the build context |

## When something is wrong

`GET /health` (and the banner at the top of the UI) lists what is missing instead of failing on the first question:

| `/health` says | Fix |
|---|---|
| `LLM CA certificate not found ... (mount ./certs)` | put the CA file named in `UPGRAD_CA_CERT` / `EMBED_CA_CERT` in `./certs` (or clear those variables if your endpoint uses a public certificate) |
| `DuckDB / chunk store / BM25 / dense index / corpus event index missing` | mount the built `./data_processed` |
| `no usable key for LLM provider` or `EMBED_API_KEY is not set` | fill `.env`, then `docker compose up -d` |

A status of 503 makes `docker compose ps` show the service as unhealthy.

## Notes

- **One shared key:** the course endpoint allows one active request per key. The UI and the API share it, so do not run an
  evaluation while someone is using the app.
- **Linux file permissions:** the container user is uid 1000. If yours differs, start with
  `APP_UID=$(id -u) APP_GID=$(id -g) docker compose up -d` so `data_processed/` (session database, traces) stays writable.
- **Exposing it beyond your machine:** ports are bound to localhost on purpose. Put a TLS reverse proxy and authentication in
  front first; the app has a per-IP rate limit and a cache but no login.
- **Restricted data:** `data_processed/_restricted/names.json` (the redaction list) stays on the host. Do not push the
  image together with a data volume.

## Smoke test (do this after every build)

`/health` only checks that files exist. It does not prove search works. After `docker compose up -d` and about a minute:

```powershell
..\.venv\Scripts\python eval/container_smoke.py
```

It asks four questions (two that need the search index, one statistics, one 30 CFR) and fails if any cannot answer or any tool errors.
History: an earlier image reported healthy while every search failed, because the index recorded a Windows path (`F:\...\chunks.jsonl`)
that Linux could not open; the agent then answered "I could not find evidence" to every question that needs retrieval.
The first search after a start is slower while indexes and models load (they now preload in the background).

The API and the console both default to Qwen3-8B when its key works; set `API_LLM_PROVIDER` to force another provider for the API.
