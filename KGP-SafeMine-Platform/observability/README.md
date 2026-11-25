# Langfuse tracing

## Recommended: Langfuse Cloud (team dashboard, no Docker) - since 21 Nov 2026

1. Sign up at https://cloud.langfuse.com (pick the region: EU or US), create a project, then Project settings -> API Keys -> Create.
2. In the project `.env`:
   ```
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_HOST=https://us.cloud.langfuse.com     # US project;  EU project: https://cloud.langfuse.com
   ```
   A 401 "Invalid credentials" with correct keys almost always means the wrong region in LANGFUSE_HOST.
3. Check: `python -m safemine.tracing` must print `'reachable': True, 'auth': True`.
4. Ask a question. Each answer shows "View this question's trace in Langfuse"; the trace has one agent root (real total latency), one
   generation per LLM call (planner, writer, critic, safety gate: duration and tokens), spans for tools / verify / critic and events for
   refusals, stripped injections and dropped filters.

**On/off switch (free-tier quota):** Settings -> Generation -> Tracing (Langfuse) -> "Send traces to Langfuse". Off takes effect at once
(the sidebar shows "Tracing paused"); "Save tracing setting" writes `LANGFUSE_ENABLED` to `.env`. The local history and
`data_processed/traces.jsonl` are always kept, and `python -m safemine.tracing replay` sends them later (same trace ids, no duplicates).

**SDK:** `langfuse>=5,<6` (OpenTelemetry). Langfuse Cloud shut down the old ingestion API (`/api/public/ingestion`) on 16 Nov 2026, so the
old `langfuse<3` SDK no longer records anything there (HTTP 410). The v5 SDK needs a Langfuse **v3+** server: the self-hosted stack below
runs `langfuse/langfuse:2` and will NOT accept these traces unless upgraded to v3 (which also needs ClickHouse, Redis and S3-compatible
storage; see the Langfuse self-hosting docs).

## Self-hosted (legacy, Langfuse v2: does not work with the v5 SDK)

1. Install Docker Desktop and start it.
2. Start Langfuse:
   ```powershell
   cd observability
   docker compose up -d
   ```
   Wait about a minute, then open http://localhost:3000. Sign in with `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` from `observability/.env`.
   The project "SafeMine agent" and its API keys already exist; the same keys are in the project `.env` (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`).
3. Start the app as usual (`streamlit run app/ui.py`) and ask questions. Each question appears under Tracing → Traces:
   spans for the plan, every tool call, verify and critic, events for refusals and repairs, and one generation with token counts.
4. Switch tracing off: empty the two keys in `.env`, or set `LANGFUSE_ENABLED=false`.

When the SafeMine app runs inside Docker, set `LANGFUSE_HOST=http://host.docker.internal:3000` in `.env` so it can reach this stack.
`observability/.env` holds generated secrets: keep it private. `data_processed/traces.jsonl` is still written as a local copy.

## Making sure every question is captured

* Each question (console, API, repeated/cached ones, refusals, abstentions) is saved to the history (`data_processed/sessions.sqlite`,
  shown in the Review Queue and dashboard) and sent to Langfuse as one trace, named by the session it belongs to.
* Langfuse does **not** restart by itself after Docker Desktop restarts. Run `start_all.bat` (project root) after every reboot.
  The console sidebar and `/health` show the tracing state; "Langfuse not reachable" means traces are being lost.
* Questions asked while Langfuse was down are still in `data_processed/traces.jsonl`. Send them again (safe to repeat: trace ids are the
  turn ids, so nothing is duplicated; timestamps are the time of re-sending):

  ```powershell
  ..\.venv\Scripts\python -m safemine.tracing replay
  ```

## Self-hosted Langfuse v4 on the AWS server (works with the v5 SDK)

`observability/docker-compose.v3.yml` is a slim copy of the official stack (web, worker, Postgres, ClickHouse, Redis, MinIO; about 2.4 GB of RAM).
On the EC2 server it lives in `~/langfuse/` (compose file + generated `.env`, mode 600); the app's `~/safemine/.env` has `LANGFUSE_HOST=http://host.docker.internal:3000`,
the project keys from `~/langfuse/.env` and `LANGFUSE_ENABLED=true`. Port 3000 is NOT open in the security group; open the UI through an SSH tunnel:
`ssh -i <your-key>.pem -L 3000:localhost:3000 ubuntu@<server-ip>`, then http://localhost:3000 (the email set in `LANGFUSE_INIT_USER_EMAIL`, password in `~/langfuse/.env`).
Check: `sudo docker compose exec -T ui python -m safemine.tracing` -> `'reachable': True, 'auth': True`.
