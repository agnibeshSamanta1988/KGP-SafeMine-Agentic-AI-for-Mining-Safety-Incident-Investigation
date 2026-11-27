<div align="center">

<img src="app/assets/logo.png" alt="KGP-SafeMine" width="320">

# KGP-SafeMine

### AI-powered Mining Safety Intelligence Platform

**Evidence-grounded answers about mine accidents, fatality investigations and federal mining regulation, with a citation behind every claim.**

![Python](https://img.shields.io/badge/Python-3.14-13315C?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/UI-Streamlit-F2A900)
![FastAPI](https://img.shields.io/badge/API-FastAPI-13315C)
![Docker](https://img.shields.io/badge/Deploy-Docker-13315C?logo=docker&logoColor=white)
![Model](https://img.shields.io/badge/LLM-Qwen3--8B-F2A900)
![RAG](https://img.shields.io/badge/Architecture-Agentic%20RAG-13315C)

Group 19 · IIT Kharagpur Executive PG Programme in Generative AI and Agentic AI · Track B

[Overview](#1-overview) ·
[Architecture](#3-architecture) ·
[How it works](#4-how-a-question-is-answered) ·
[Safety](#7-safety-and-governance) ·
[Setup](#9-setup) ·
[Security](#13-security-notes-before-you-publish-or-deploy) ·
[Deploy](#10-deployment) ·
[Layout](#11-repository-layout)

</div>

> **Decision support only.** Answers are drafts for a qualified safety professional to check. They are not legal, regulatory or
> engineering advice, and the platform never assigns blame or certifies compliance.

---

## 1. Overview

Mine safety knowledge is spread across thousands of PDF investigation reports, millions of accident records and a large body of
regulation (30 CFR). A safety officer who asks *"what root causes did MSHA find for haul-truck fatalities?"* or *"what did this
standard say on the day of the accident?"* normally has to search all of it by hand.

KGP-SafeMine answers such questions in plain language and **proves each statement**: every factual sentence carries a citation to a
report passage, a database figure or the text of a regulation, and statements with an unverified regulation number, quotation, date or figure of two or more digits are removed
(other unsupported sentences are flagged). When the
evidence is missing, the platform says so instead of guessing.

It was built for **Track B** of a capstone programme: a multi-agent system running on a hosted model of at most 8 billion parameters
(**Qwen3-8B**), over US Mine Safety and Health Administration (MSHA) data.

### What it can do

| Capability | Example |
|---|---|
| **Ask in plain language** | "What root causes did MSHA find for haul truck fatalities at surface mines?" |
| **Statistics from the database** | "How many fatal accidents by classification?" (the model never writes SQL) |
| **Law as of a date** | "What did 30 CFR 56.14211 require in 2019?" (the edition in force on that date) |
| **Investigate one incident** | Evidence-backed brief for a named event, with a timeline and the standards cited |
| **Refuse and abstain safely** | Declines blame, compliance certification and live-emergency questions; abstains when evidence is thin |
| **Human review** | Flagged answers go to a non-blocking review queue (approve, flag, reject); exports are marked DRAFT |

---

## 2. The data

| Source | Used for |
|---|---|
| Fatality investigation dossiers (PDF, one per event) | The retrieval corpus: summary, final report, alert, supplements |
| Accident, mine, inspection and violation tables (Parquet) | Statistics in DuckDB |
| 30 CFR history (every dated version of every section) | "Law as of a date" lookups |
| Federal Register rules index | Rules in force or proposed |

The team's cleaned dataset holds **655 dossiers**, which become **10,990 chunks**; the CFR store holds **70,109 regulation records**.
The pipeline also redacts personal names in a second pass (see [Safety](#7-safety-and-governance)).
Details and every cleaning decision: [`docs/DATA_AND_CHUNKING.md`](docs/DATA_AND_CHUNKING.md).

> The cleaned dataset is in the sibling folder [`KGP-SafeMine-Data/`](../KGP-SafeMine-Data). The built indexes are **not** in the repository: you build them once. See [Setup](#9-setup).

### What is not in this repository

Code, configuration, evaluation files and the public dataset are published. You supply or build these yourself:

1. **API keys and endpoints.** Copy `.env.example` to `.env` and fill it in. No key is included.
2. **A login.** Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and add a bcrypt password hash
   (`python -m app.make_password_hash`). There is no default account. See [`docs/AUTH.md`](docs/AUTH.md).
3. **The built indexes.** The search indexes and database (`data_processed/`) are built from `../KGP-SafeMine-Data` (a cleaned
   snapshot of MSHA fatality investigation PDFs, accident Parquet tables and CFR history) with the pipeline in `safemine/ingest/`.
4. **Models.** `make models` downloads `BAAI/bge-small-en-v1.5` and `cross-encoder/ms-marco-MiniLM-L6-v2` from Hugging Face.
5. **TLS certificates** (`certs/`), only if your LLM or embedding endpoint uses a self-signed certificate.

---

## 3. Architecture

```mermaid
flowchart TB
    U([User]) --> UI["Streamlit console<br/>login · 9 pages"]
    U --> API["FastAPI service<br/>/ask · /review · /health"]
    UI --> SUP
    API --> SUP

    subgraph CORE["Agent layer  ·  safemine/agents"]
        SUP{{"Supervisor<br/>control flow · limits · fail-closed"}}
        SUP --> SAF[Safety]
        SUP --> PLN[Planner]
        SUP --> RET[Retrieval]
        SUP --> REG[Regulatory]
        SUP --> INV[Investigation]
        SUP --> VAL[Validator]
        SUP --> CRI[Critic]
        SUP --> REP[Report]
    end

    subgraph TOOLS["Tools  ·  safemine/tools"]
        T1[hybrid_search]
        T2[accident_stats]
        T3[cfr_lookup]
        T4[record_lookup]
        T5[verify_claims]
    end

    RET --> T1 & T2 & T4
    REG --> T3
    VAL --> T5

    subgraph DATA["Local data  ·  data_processed"]
        D1[("chunks + BM25<br/>+ dense index")]
        D2[("DuckDB<br/>accidents · CFR")]
        D3[("sessions · traces")]
    end

    T1 --> D1
    T2 & T3 & T4 --> D2
    REP --> D3

    INV -. prompts .-> LLM["Hosted LLM<br/>Qwen3-8B"]
    PLN -. prompts .-> LLM
    CRI -. prompts .-> LLM
    T1 -. embeddings .-> EMB["Embeddings<br/>bge-small-en-v1.5"]
    SUP -. traces .-> LF[("Langfuse<br/>optional")]
```

### Components

| Layer | Technology | Role |
|---|---|---|
| Console | Streamlit, bcrypt login, light / dark / device theme | Nine pages: Home, Safety Dashboard, AI Safety Assistant, Incident Investigation, Regulatory Intelligence, Knowledge Base, Reports & Export, Human Review Queue, Settings |
| API | FastAPI + Uvicorn | `POST /ask`, `POST /review`, `GET /health`; per-client rate limit and cache |
| Agents | Plain Python, typed messages | A supervisor and eight specialised agents |
| Language model | Qwen3-8B behind an OpenAI-compatible endpoint (8,192-token context) | Planning, drafting, critique. Other providers can be switched on in `.env` for development |
| Embeddings | `bge-small-en-v1.5`, 384 dimensions (hosted, or local on CPU) | Dense retrieval |
| Reranker | `cross-encoder/ms-marco-MiniLM-L6-v2` | Re-orders retrieved passages |
| Search | `rank_bm25` plus an exact NumPy cosine matrix | No vector database is needed at this corpus size |
| Structured data | DuckDB | Accident statistics and the dated CFR store |
| Observability | Langfuse v5 SDK (optional) and a local `traces.jsonl` | Every question, plan, tool call and agent message |
| Packaging | One Docker image for UI and API | Non-root, capabilities dropped, ports on localhost |

### The eight agents

| Agent | Owns |
|---|---|
| **Safety** | Input policy: rules R1 to R7 plus an LLM classifier, prompt-injection stripping, out-of-range dates |
| **Planner** | Intent, at most four tool steps, output format |
| **Retrieval** | `hybrid_search`, `accident_stats`, `record_lookup`; finding the one named incident |
| **Regulatory** | `cfr_lookup` (law as of a date); standards behind an incident |
| **Investigation** | Grounding a named incident, premise checks, cited drafting of answers and briefs |
| **Validator** | Citation repair, claim verification, grounding score, removal of sentences with unverified facts, claim map |
| **Critic** | Accept, revise or abstain; a support floor of 60 % means weaker answers are never accepted |
| **Report** | Final assembly: notes, answer-policy gate, name filter, human-review flag |

A **supervisor** coordinates them. Agents never call each other directly: every delegation is a typed message on a per-request bus,
which is shown in the console as "Agent messages" and recorded in the trace. Full reference: [`docs/AGENTS.md`](docs/AGENTS.md).

---

## 4. How a question is answered

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant S as Safety
    participant P as Planner
    participant X as Retrieval / Regulatory
    participant I as Investigation
    participant V as Validator
    participant C as Critic
    participant R as Report

    User->>S: question
    S-->>User: refuse (rules R1–R7) or continue
    S->>P: cleaned question
    P->>X: plan (at most 4 tool steps)
    X->>X: hybrid_search · accident_stats · cfr_lookup · record_lookup
    X->>I: evidence with ids [E1], [E2] …
    loop at most 2 revisions
        I->>V: cited draft
        V->>C: verified claims + support ratio
        C-->>I: revise (extra tool steps)
    end
    C->>R: accept, or abstain
    R-->>User: answer with citations, notes and review flag
```

1. **Screen.** Rules and a classifier refuse unsafe requests (victim names, blame, compliance certificates, live operational
   decisions, endorsing shortcuts, predictions, impersonating MSHA). Instructions hidden in the question are stripped, not obeyed.
2. **Plan.** The planner picks the tools: search the reports, run a whitelisted statistic, look up a regulation as of a date, or fetch
   one named incident. If the model fails, a deterministic heuristic plan is used.
3. **Retrieve.** Evidence is gathered and numbered (`[E1]`, `[E2]` …); retrieved text is screened for hidden instructions.
4. **Draft.** The investigation agent writes an answer in which every factual sentence cites evidence.
5. **Verify.** Deterministic checks (no model involved) confirm that each quote is verbatim, each number of two or more digits, date and CFR section appears
   in the cited evidence, and each sentence is cited. Sentences that fail these checks are removed; other weakly supported ones are flagged.
6. **Critique.** The critic accepts, asks for another round (at most two revisions), or abstains. Below a 60 % support ratio an
   answer is never accepted.
7. **Report.** Final assembly applies the answer policy and the name filter, adds notes and marks the answer for human review when needed.

### Hybrid retrieval

```mermaid
flowchart LR
    Q[Question] --> B["BM25<br/>top 30"]
    Q --> D["Dense bge-small<br/>top 30"]
    B --> F["Reciprocal rank<br/>fusion"]
    D --> F
    F --> X["MiniLM cross-encoder<br/>rerank top 20"]
    X --> E["6–8 evidence chunks<br/>normally at most 2 per incident"]
```

Chunks are **section-aware, up to about 450 tokens**: one chunk per root-cause and corrective-action pair (1,084 pairs), one per
enforcement citation, sub-headed discussion blocks, and a contextual header (date, mine, accident type, state, section) used only
for indexing so the citable text stays verbatim.

### The five tools

| Tool | What it does | Why it is built this way |
|---|---|---|
| `hybrid_search` | BM25 + dense search, reranked | Exact standard numbers match by keyword, paraphrases by meaning |
| `accident_stats` | Counts and trends from DuckDB | The model picks a whitelisted metric and filters; **it never writes SQL**, and arguments are bound as parameters |
| `cfr_lookup` | Text of a 30 CFR section as of a date | Law changes; an edition that was never collected cannot be quoted |
| `record_lookup` | One record by its identifier: an accident, inspection, violation, mine profile, last inspection, or the reports citing a 30 CFR section | Exact lookups come from the database, not from the model's memory |
| `verify_claims` | Quote, number, date and citation checks | Catches invented details without asking a model |

### Bounded and fail-closed

| Limit | Default |
|---|---|
| Tool steps per question | 10 |
| Critic revision rounds | 2 |
| Input token budget | 12,000 (24,000 for a brief) |
| Wall clock per question | 420 s |

If the validator, the report agent or incident grounding fails, or time runs out, the platform **abstains** rather than releasing an
unverified answer. The user never sees a traceback.

---

## 5. Console pages

| Group | Page | Purpose |
|---|---|---|
| Main | **Home** | Platform overview, measured results, data in use, workflow and disclaimer |
| Main | **Safety Dashboard** | Accident trends, causes, standards cited and activity |
| Main | **AI Safety Assistant** | Chat with cited answers, claim map, agent messages and a link to the trace |
| Analysis | **Incident Investigation** | Evidence-backed brief and timeline for one incident |
| Analysis | **Regulatory Intelligence** | Look up a standard, search standards, compliance check; law as of a date |
| Knowledge | **Knowledge Base** | What is indexed, corpus search, and file upload (stored, not searched) |
| Governance | **Reports & Export** | Download answers and briefs (marked DRAFT) |
| Governance | **Human Review Queue** | Approve, flag or reject answers that need a person |
| Governance | **Settings** | Provider, model, temperature, rate pause, tracing switch, health checks |

---

## 6. Evaluation

The repository includes the benchmark and runners (`eval/`). The **100-question golden set** (`eval/golden/`) was written before any
agent code; 14 questions are for development and **86 are a frozen test set** that was run once.

| Measure | Result | Source |
|---|---|---|
| End-to-end accuracy on the frozen test split (Qwen3-8B) | **52 / 86 (60.5 %)**, 95 % interval 50 % to 70 % | `eval/results/test_final.summary.json` |
| Factual questions in that split (incident analysis, source and 30 CFR) | **38 / 55**; the same model without retrieval got 0 / 55 | `eval/results/test_final.summary.json`; final report |
| Behaviour questions in that split (abstain, refuse, ignore an injection) | **5 / 17**, the weakest area, measured before the safety rebuild | `eval/results/test_final.summary.json` |
| Right report in the top 10 (53 report questions, hybrid + rerank) | **100 %**; first place 96.2 %; MRR 0.975 | `eval/retrieval_results_v2.json` |
| 30 CFR lookups (exact text, section by title, edition on a past date) | **16 / 16** | `eval/cfr_results_v2.json` |
| Prompt-injection attacks planted in retrieved evidence | **57 / 58 held** in each placement (end and middle of a document); the one that got through was a planted false fact | `eval/results/injection_*.json` |

The test split ended with 67 answered, 16 abstained and 3 refused. It was run once (19 November 2026), before the safety rebuild
and later fixes, and was not run again, so 60.5 % remains the reported test score.

**Measured after the test** (not new test scores):

* **Unsafe questions refused:** 84 of 86 on the 24 November re-run (86 of 86 in the 20 November log), on three question sets written by
  the team (`eval/safety_holdout*.csv`, `eval/safety_eval.py`). These sets are not independent.
* **RAG against no retrieval, same Qwen3-8B, all 100 questions:** token F1 46.0 % against 9.5 %; task success 77 % against 10 %. This
  run uses the improved pipeline and includes the 14 development questions. Details are in the final project report; its raw result
  files are not in this repository.

Run your own (the second command needs the data and a Qwen3-8B endpoint):

```bash
python -m eval.agent_eval --selftest      # scorer checks, no model, no network
python -m eval.agent_eval --split DEV     # the 14 development questions
```

---

## 7. Safety and governance

### Model card

| | KGP-SafeMine |
|---|---|
| Model and data | Qwen3-8B (course endpoint, not fine-tuned) with retrieval; public US MSHA reports and tables and 30 CFR, snapshot 30 October 2026 |
| Intended use | Decision support for a safety professional on US mining incidents, statistics and 30 CFR standards, including draft investigation briefs; a qualified person reviews before acting |
| Out of scope | Assigning fault or liability, certifying compliance or giving legal advice, real-time operating decisions, predicting accidents, official findings |
| Performance | Frozen test: 52 of 86 correct (60.5 %, 95 % interval 50 % to 70 %); factual 38 of 55; behaviour questions 5 of 17, before the safety rebuild |
| Failure modes | Of 34 failed test questions (tags overlap): reasoning error 12, over-abstention 12, retrieval miss 5, hallucination 4, unsafe answer 3, unsupported claim 2; no "Partial" verdict |
| Refusals | Rules R1 to R7 below; abstains when evidence is missing or the question is out of scope |
| Adversarial tests | Unsafe questions refused: 84 of 86 on the 24 November re-run (team-written sets). Planted prompt injections: 1 of 58 compromised per placement (2 before the new layers) |

### Refusal and abstention rules

* **Refuse:** R1 victim names and personal details; R2 blame, fault or liability; R3 certifying compliance or legal advice; R4 real-time
  operating decisions; R5 endorsing unsafe shortcuts; R6 predicting accidents or writing an official finding. R7: instructions inside a
  question are treated as data (the injected sentence is removed and the real question is answered).
* **Abstain:** the event is after the data snapshot, no incident is named, only a preliminary notice exists, or the question is out of scope.

### Controls

| Concern | Control |
|---|---|
| Unsafe requests | Rules R1 to R7 plus an LLM policy classifier |
| Prompt injection (direct and hidden in documents) | Eight layers: input guard, evidence screen, prompt hardening, tool grounding, claim verifier, prompt-leak filter, answer policy, visibility. See [`docs/INJECTION.md`](docs/INJECTION.md) |
| Hallucinated details | Deterministic claim verification; unverified details removed, other unsupported sentences flagged; support floor of 60 % |
| Personal data | Victims are replaced in the source data; pattern and name-recognition passes replace remaining names with placeholders and store the list privately for an output filter |
| Blame and compliance verdicts | Blocked by the answer policy |
| Unverified answers | Fail-closed abstention; human-review queue; DRAFT marking in exports |
| Access | bcrypt login with lock-out and inactivity timeout (`docs/AUTH.md`); no default account |
| Secrets | Never in the image: `.env`, `secrets.toml`, certificates and data are mounted at run time |
| Containers | Non-root user, all Linux capabilities dropped, `no-new-privileges`, ports bound to `127.0.0.1` |
| Auditability | Every question, plan, tool call and agent message is traced (Langfuse and a local file) |

---

## 8. Known limits

* The model is small (8B) and the context window is 8,192 tokens, so long dossiers are summarised from selected passages.
* Only the indexed sources are used. Items shown as "not indexed" in the Knowledge Base are not searched, and uploaded files are stored but not searched.
* Law answers depend on the CFR editions that were collected; a date outside them cannot be answered.
* Name redaction is pattern and model based. It reduces, but cannot guarantee zero, exposure of personal names; keep the restricted name list private.
* The source dataset is public MSHA material and can contain names; redaction happens when you build the indexes.
* The hosted endpoint allows one active request per key, so evaluation runs and live users share capacity.
* The claim-verification verdict "Partial" is never produced.
* Timelines are narratives, not structured timelines. Briefs, timelines and comparisons were checked only by a small probe, not a scored set.
* Some out-of-scope questions are answered instead of declined, and law that needs a Federal Register notice to interpret is answered poorly.
* A plain false statement planted in a document, worded like a report sentence, can still succeed.
* Scanned PDFs without a text layer, the pre-2008 archive, disaster reports and the policy manual are not indexed.
* Exact-date law exists only for Parts 56 and 57 (from 2017), 75 (from 2021) and 77 (from 2024); otherwise the annual edition (from
  July 2008) is returned and labelled as such.
* Scoring is lexical, and the test split is spent: a second independent benchmark is still needed.
* One server and no failover in the reference deployment; the REST API has no login, so do not expose it.

---

## 9. Setup

### What you need

| Item | Notes |
|---|---|
| Python **3.14** | Needed to download the models and build the indexes, also if you then run with Docker |
| Docker with Compose v2 (optional) | To run the console and API in containers; the image uses `python:3.14-slim` |
| A chat endpoint | OpenAI-compatible, serving Qwen3-8B (or another provider listed in `.env.example`) |
| An embedding endpoint | `bge-small-en-v1.5`, or set `EMBED_BACKEND=local` to run it on CPU |
| The `KGP-SafeMine-Data/` folder | Cleaned MSHA snapshot (see [Data](#2-the-data)), included in this repository next to this folder |

### Step by step

```bash
# 1. Environment
python -m venv .venv
.venv/bin/pip install -r requirements.txt            # Windows: .venv\Scripts\pip

# 2. Configuration (never commit these two files)
cp .env.example .env                                  # add keys and endpoints, and choose LLM_PROVIDER (see below)
mkdir -p .streamlit && cp .streamlit/secrets.toml.example .streamlit/secrets.toml
.venv/bin/python -m app.make_password_hash            # paste the printed hash into secrets.toml

# 3. Models (reranker and tokenizer, one time)
make models

# 4. Data: .env already points SAFEMINE_DATA at ../KGP-SafeMine-Data. Build the database and indexes
make data                                             # clean, chunk, DuckDB, BM25 + dense, name redaction, events index

# 5. Run
.venv/bin/streamlit run app/ui.py                     # console  http://localhost:8501
.venv/bin/uvicorn app.api:app --port 8000             # API docs http://localhost:8000/docs
.venv/bin/python -m safemine.cli "What does 30 CFR 56.14211 require?"
```

> **Choose the model.** `.env.example` ships with `LLM_PROVIDER=groq`, a development-only 20B model. Set **`LLM_PROVIDER=upgrad`** and fill
> in the `UPGRAD_*` values to use Qwen3-8B, the model behind every result in this README.

**Windows (PowerShell, from this folder).** The `Makefile` targets use the Linux/macOS path, so run the steps directly:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
python -m app.make_password_hash
# stop here: edit .env (set LLM_PROVIDER=upgrad and your keys) and paste the hash into .streamlit\secrets.toml
python -c "from huggingface_hub import snapshot_download as d; d('BAAI/bge-small-en-v1.5', local_dir='models/bge-small-en-v1.5'); d('cross-encoder/ms-marco-MiniLM-L6-v2', local_dir='models/ms-marco-MiniLM-L6-v2')"
python -m safemine.ingest.clean_pdfs
python -m safemine.ingest.chunk --strategy section --size 450
python -m safemine.ingest.build_duckdb
python -m safemine.ingest.build_indexes
python -m safemine.ingest.ner_redact detect
python -m safemine.ingest.ner_redact apply
python -m safemine.ingest.build_events_index
streamlit run app/ui.py
```

**Build the data.** The pipeline reads the dataset folder (`SAFEMINE_DATA`, here `../KGP-SafeMine-Data`) and writes
`data_processed/` (`SAFEMINE_OUT`). Expected layout and every cleaning decision are in
[`docs/DATA_AND_CHUNKING.md`](docs/DATA_AND_CHUNKING.md). Hosted embeddings add several minutes. The individual targets are in the `Makefile`
(`clean`, `chunks`, `duckdb`, `index`, `redact`, `events-index`). The `redact` step (name recognition) takes about 30 to 40 minutes on CPU and
downloads `dslim/distilbert-NER` once; do not skip it. The pipeline writes a restricted name list to `data_processed/_restricted/` for the
output filter: keep it private and never publish `data_processed/`.

Key settings in `.env`:

| Setting | Meaning |
|---|---|
| `LLM_PROVIDER` | `upgrad` (the hosted Qwen3-8B endpoint), `groq` (the value in `.env.example`), `openai`, `gemini`, `anthropic` |
| `EMBED_BACKEND` | `endpoint` or `local` |
| `MAX_STEPS`, `MAX_REVISIONS`, `TOKEN_BUDGET_PER_QUERY` | Agent limits |
| `LANGFUSE_*` | Tracing; leave the keys empty to switch it off |

### Check it works

```bash
pip install pytest                 # test runner, not part of requirements.txt (use the .venv)
python -m pytest tests -q          # see the note below about data and login file
python eval/container_smoke.py     # against a running API: asks retrieval, statistics and CFR questions
```

> Without `data_processed/` and `.streamlit/secrets.toml`, tests that exercise the real data or the login page fail or are skipped. Build the data and create the login file first for a clean run.

### Developing

* Console pages are in `app/views/`; agents in `safemine/agents/`; tools in `safemine/tools/`. Run `python -m pytest tests -q` after a change.
* The REST API is described at `http://localhost:8000/docs` while it runs. It has no login: do not expose it publicly.

### Troubleshooting

| Symptom | What to do |
|---|---|
| `DuckDB / chunk store / BM25 / dense index ... missing` | Build the data (step 4); check `SAFEMINE_DATA` in `.env` |
| Login page shows an error | Create `.streamlit/secrets.toml` with a bcrypt hash (step 2) |
| `CA certificate not found` | Put the file named in `.env` into `certs/`, or clear the variable for a public certificate |
| Embedding endpoint unreachable | Set `EMBED_BACKEND=local` (needs `models/`) |
| First question is slow | The search and rerank models load on first use |

More in [`docs/DOCKER.md`](docs/DOCKER.md).

---

## 10. Deployment

### Docker (local or server)

```bash
mkdir -p certs models data_processed        # compose mounts these folders
docker compose build
docker compose up -d
docker compose ps                           # ui and api should turn "healthy" in about 40 seconds
```

In Windows PowerShell, replace the first line with `New-Item -ItemType Directory -Force certs, models, data_processed`.
Build `data_processed/` first ([Setup](#9-setup), steps 3 and 4): the image does not build it.

Open **http://localhost:8501** (console) and **http://localhost:8000/docs** (API).
`.env`, `.streamlit/secrets.toml` and `data_processed/` must exist before `up`. They are mounted, never baked into the image.

### On a server with HTTPS

[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) covers a single Linux server: copying the project, building the image, an HTTPS reverse
proxy with Caddy, and optional self-hosted Langfuse tracing. [`docs/DOCKER.md`](docs/DOCKER.md) lists what each Docker file does and
how to read the `/health` messages.

### Tracing

Set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_HOST` in `.env` (Langfuse Cloud, or a self-hosted Langfuse server).
With no keys, tracing is off and a local `traces.jsonl` is still written.

* To self-host, use `observability/docker-compose.v3.yml`. The older `observability/docker-compose.yml` runs Langfuse v2, which does not
  accept traces from the v5 SDK.
* **Under Docker,** `docker-compose.yml` sets `LANGFUSE_HOST=http://host.docker.internal:3000` (a Langfuse on the same machine), which
  overrides `.env`. To use Langfuse Cloud, change or remove that line.

---

## 11. Repository layout

```text
KGP-SafeMine-Platform/
├── app/                      Streamlit console and FastAPI service
│   ├── ui.py · nav.py        entry point and navigation
│   ├── views/                the pages (home, dashboard, assistant, investigation, ...)
│   ├── auth.py               bcrypt login, lock-out, timeout
│   └── api.py                /ask  /review  /health
├── safemine/
│   ├── agents/               supervisor + 8 agents, typed message bus
│   ├── agent/                LLM client, safety guard, injection screen, policy
│   ├── tools/                hybrid_search · accident_stats · cfr_lookup · record_lookup · verify_claims
│   ├── ingest/               offline pipeline: clean PDFs, redact, chunk, DuckDB, indexes
│   ├── config.py             all settings (read from .env)
│   └── tracing.py            Langfuse and local traces
├── tests/                    unit, UI, login, injection and failure tests
├── eval/                     benchmark runner, golden set, hold-out checks, frozen results
├── docs/                     AGENTS · AUTH · DATA_AND_CHUNKING · DOCKER · INJECTION · DEPLOYMENT
├── observability/            optional self-hosted Langfuse stacks
├── Dockerfile · docker-compose.yml · requirements.lock
└── .env.example · .streamlit/secrets.toml.example
```

---

## 12. Documentation index

| Document | Read it for |
|---|---|
| [`docs/AGENTS.md`](docs/AGENTS.md) | Agents, message flow, error handling, claim map |
| [`docs/DATA_AND_CHUNKING.md`](docs/DATA_AND_CHUNKING.md) | Source data, cleaning, redaction, chunking and retrieval results |
| [`docs/INJECTION.md`](docs/INJECTION.md) | Prompt-injection defence layers and test results |
| [`docs/AUTH.md`](docs/AUTH.md) | Login setup and changing passwords |
| [`docs/DOCKER.md`](docs/DOCKER.md) | Container files, health checks, troubleshooting |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Server deployment with HTTPS and tracing |
| [`observability/README.md`](observability/README.md) | Langfuse tracing options |

---

## 13. Security notes before you publish or deploy

- Never commit `.env`, `.streamlit/secrets.toml`, `observability/.env`, `certs/` or `data_processed/` (all are in `.gitignore`).
- Ports are bound to `127.0.0.1`. Put a TLS reverse proxy in front before exposing the console (see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)).
- Rotate any key that was ever pasted into a file that was shared.

---

<div align="center">

**KGP-SafeMine** · evidence first, or no answer.

</div>
