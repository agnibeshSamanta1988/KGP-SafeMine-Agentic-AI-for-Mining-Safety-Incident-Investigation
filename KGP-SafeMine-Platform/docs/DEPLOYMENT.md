# Deploying KGP-SafeMine on a server

This guide shows how to run the platform on a single Linux server with Docker, HTTPS and optional tracing. It uses placeholders
(`<server-ip>`, `app.example.com`); replace them with your own. The project was run this way on one cloud virtual machine
(Ubuntu, 2 vCPU, 8 GB RAM, 40 GB disk); the same Docker image runs locally (`docs/DOCKER.md`).

## 1. What you need

- A Linux server with Docker Engine and the Compose plugin (`sudo apt-get install -y docker.io docker-compose-v2` on Ubuntu).
  About 8 GB RAM is comfortable with Langfuse; the app alone is lighter. The image is about 3 GB.
- A domain name, or a free wildcard name such as `<server-ip-with-dashes>.sslip.io`, pointing at the server's fixed IP.
- Firewall: allow 22 (SSH, ideally only from your own IP), 80 and 443. Do **not** open 8000, 8501 or 3000.
- Your own keys (`.env`), login hash (`.streamlit/secrets.toml`) and built data (`data_processed/`). See the README.

## 2. Copy the project to the server

Copy these (and nothing else) to `~/safemine/`: `app/`, `safemine/`, `.streamlit/` (with your `secrets.toml`), `requirements.lock`,
`Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env`, `data_processed/`, and `certs/` if your endpoints need it.

```bash
tar -czf safemine.tgz app safemine .streamlit requirements.lock Dockerfile docker-compose.yml .dockerignore .env data_processed certs
scp -i <your-key>.pem safemine.tgz ubuntu@<server-ip>:/tmp/
ssh -i <your-key>.pem ubuntu@<server-ip> "mkdir -p ~/safemine && cd ~/safemine && tar -xzf /tmp/safemine.tgz"
```

Leave old `sessions.sqlite` and `traces.jsonl` out of `data_processed/` if you do not want to carry over chat history.

## 3. Build and start

```bash
cd ~/safemine
mkdir -p models certs
sudo docker compose build               # 8-10 minutes the first time (downloads CPU-only PyTorch)
sudo docker compose up -d ui            # add `api` to start the REST API as well
sudo docker compose ps                  # wait for "healthy"
```

After any change to `.env` or `secrets.toml`: `sudo docker compose up -d --force-recreate ui`. A running container keeps an old copy
of those files until it is recreated. After code changes: `sudo docker compose build ui && sudo docker compose up -d --force-recreate ui`.

## 4. HTTPS with Caddy

The compose file publishes the UI only on `127.0.0.1:8501`. Run Caddy 2 on the compose network, which obtains a Let's Encrypt
certificate automatically:

```bash
sudo docker run -d --restart unless-stopped --name caddy --network safemine_default \
  -p 80:80 -p 443:443 -v ~/safemine/Caddyfile:/etc/caddy/Caddyfile -v caddy_data:/data caddy:2
```

`~/safemine/Caddyfile`:

```
app.example.com {
  reverse_proxy ui:8501
}
```

The network name is `<folder name>_default` (`safemine_default` when the folder is `~/safemine`). The console itself requires a login
(`docs/AUTH.md`); passwords must never travel over plain HTTP.

## 5. Optional: tracing with Langfuse

Tracing is off unless `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set in `.env`. Two options (details in `observability/README.md`):

- **Langfuse Cloud:** create a project, put the two keys and `LANGFUSE_HOST` (EU or US region URL) in `.env`.
- **Self-hosted v4 stack:** copy `observability/docker-compose.v3.yml` to `~/langfuse/docker-compose.yml`, copy `observability/.env.example`
  to `~/langfuse/.env` and replace every `CHANGE_ME` with a random value, then `sudo docker compose up -d`. Put the project keys from that
  `.env` into the app's `.env` with `LANGFUSE_HOST=http://host.docker.internal:3000`. Keep port 3000 closed and reach the UI
  through an SSH tunnel (`ssh -L 3000:localhost:3000 ...`). The older `observability/docker-compose.yml` is Langfuse v2 and does not
  work with the `langfuse>=5` SDK.

Check: `sudo docker compose exec -T ui python -m safemine.tracing` should print `'reachable': True, 'auth': True`.

## 6. Verify

```bash
curl -s http://127.0.0.1:8501/_stcore/health          # on the server: ok
sudo docker compose up -d api && python3 eval/container_smoke.py http://localhost:8000   # run from the project folder; needs the api service
```

`GET /health` (API) lists missing keys, certificates or data files instead of failing on the first question.

## 7. Operating notes

- The hosted chat endpoint allows one active request per key; the UI and API share it, so do not run an evaluation while people use the app.
- `data_processed/_restricted/` holds the redaction name list: keep it on the server only, never in an image or a repository.
- Stop and start the server instance when idle to save cost; the app containers restart by themselves (`restart: unless-stopped`) and the Langfuse v4 services use `restart: always`.
- Day-to-day: `sudo docker ps`, `sudo docker logs <container>`.
