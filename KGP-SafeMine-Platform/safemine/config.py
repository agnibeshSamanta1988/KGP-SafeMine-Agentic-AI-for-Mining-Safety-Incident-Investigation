"""Central configuration. Reads .env if python-dotenv is installed."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# Cleaned team dataset (GitHub: KGP-SafeMine-Data/): one PDF dossier per fatality event, Parquet tables,
# versioned CFR store. Models are not in the dataset any more -> ./models (bge-small, MiniLM reranker).
DATA = ROOT / os.getenv("SAFEMINE_DATA", "KGP-SafeMine-Data")
OUT = ROOT / os.getenv("SAFEMINE_OUT", "data_processed")
REPORTS_DIR = DATA / "fatality_investigations"
EVENTS_INDEX = REPORTS_DIR / "events_index.csv"
STRUCTURED_DIR = DATA / "structured_data"
REG_DIR = DATA / "regulations"
MODELS = ROOT / os.getenv("SAFEMINE_MODELS", "models")

DOCS_JSONL = OUT / "docs.jsonl"            # one cleaned, redacted document per report
CHUNKS_JSONL = OUT / "chunks.jsonl"        # canonical chunk store
BM25_PKL = OUT / "bm25.pkl"
DENSE_NPY = OUT / "dense.npy"
DUCKDB_PATH = OUT / "safemine.duckdb"
REDACTION_DIR = OUT / "_restricted"        # name lists: never logged, never sent to the LLM

# ---- LLM provider switch -------------------------------------------------------------------
# LLM_PROVIDER=upgrad  -> course endpoint, Qwen/Qwen3-8B (the graded system)
# LLM_PROVIDER=groq    -> Groq free tier, openai/gpt-oss-20b (dev/testing only: 20B > the 8B Track B cap)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "upgrad").lower()
PROVIDERS = {
    "upgrad": {
        "base_url": os.getenv("UPGRAD_BASE_URL", ""),
        "api_key": os.getenv("UPGRAD_API_KEY", ""),
        "model": os.getenv("UPGRAD_MODEL", "Qwen/Qwen3-8B"),
        "ca_cert": os.getenv("UPGRAD_CA_CERT", ""),      # group .crt file (self-signed endpoint)
        "max_tokens_cap": 1024,                            # endpoint rejects > 1024
        "context_window": 8192,                            # prompt + output per call (learner guide)
        "max_concurrent": 1,                               # 1 active request per group key, else 429
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        "no_think_tag": True,
    },
    "groq": {
        "base_url": os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        "api_key": os.getenv("GROQ_API_KEY", ""),
        "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
        "ca_cert": "",
        "max_tokens_cap": 4096,
        "context_window": 8192,            # NOT the model window (131k): the free tier rejects a request above ~8k tokens (HTTP 413), so budget like Qwen
        "max_concurrent": 4,
        "extra_body": {"reasoning_effort": os.getenv("GROQ_REASONING_EFFORT", "low")},
        "no_think_tag": False,
    },
}
# Optional hosted providers (OpenAI-compatible chat endpoints). Not part of the graded Track B system; for comparison and demos.
def _hosted(prefix, base, model):
    return {"base_url": os.getenv(f"{prefix}_BASE_URL", base), "api_key": os.getenv(f"{prefix}_API_KEY", ""),
            "model": os.getenv(f"{prefix}_MODEL", model), "ca_cert": "", "max_tokens_cap": 4096, "context_window": 128000,
            "max_concurrent": 4, "extra_body": {}, "no_think_tag": False}


PROVIDERS["openai"] = _hosted("OPENAI", "https://api.openai.com/v1", "gpt-4o-mini")
PROVIDERS["gemini"] = _hosted("GEMINI", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash")
PROVIDERS["anthropic"] = _hosted("ANTHROPIC", "https://api.anthropic.com/v1/", "claude-sonnet-5-5")
DISPLAY = {"upgrad": "Qwen3-8B", "groq": "Groq gpt-oss-20b", "openai": "OpenAI", "gemini": "Google Gemini", "anthropic": "Anthropic Claude"}
TEMPERATURE = min(1.0, max(0.0, float(os.getenv("LLM_TEMPERATURE", "0.1"))))   # applied to every LLM call
if LLM_PROVIDER not in PROVIDERS:
    raise ValueError(f"LLM_PROVIDER must be one of {list(PROVIDERS)}, got {LLM_PROVIDER!r}")
P: dict = {}
LLM_BASE_URL = LLM_API_KEY = LLM_MODEL = LLM_CA_CERT = ""


def set_provider(name: str, api_key: str | None = None) -> None:
    """Switch the LLM at runtime (UI button). Modules read config.P / config.LLM_* at call time, so the next
    question uses the new provider. `api_key` overrides the key from .env for this process only."""
    global LLM_PROVIDER, P, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_CA_CERT
    if name not in PROVIDERS:
        raise ValueError(f"LLM_PROVIDER must be one of {list(PROVIDERS)}, got {name!r}")
    if api_key:
        PROVIDERS[name]["api_key"] = api_key.strip()
    LLM_PROVIDER, P = name, PROVIDERS[name]
    LLM_BASE_URL, LLM_API_KEY, LLM_MODEL = P["base_url"], P["api_key"], P["model"]
    LLM_CA_CERT = P["ca_cert"]
    if LLM_CA_CERT and not Path(LLM_CA_CERT).is_absolute():
        LLM_CA_CERT = str(ROOT / LLM_CA_CERT)


def provider_ready(name: str) -> bool:
    p = PROVIDERS[name]
    return bool(p["base_url"]) and bool(p["api_key"]) and "REPLACE" not in p["api_key"] and "REPLACE" not in p["base_url"]


set_provider(LLM_PROVIDER)

# ---- pause between LLM calls (stay under free-tier rate limits; Groq gpt-oss-20b free tier = 30 requests/min) ----
# Enforced as a minimum gap between the start of consecutive calls, across all questions in this process.
LLM_SLEEP_ENABLED = os.getenv("LLM_SLEEP_ENABLED", "true").lower() == "true"
LLM_SLEEP_SECONDS = float(os.getenv("LLM_SLEEP_SECONDS", "2.0"))
LLM_DISABLE_THINKING = os.getenv("LLM_DISABLE_THINKING", "true").lower() == "true"

EMBED_BACKEND = os.getenv("EMBED_BACKEND", "local")
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "")
EMBED_API_KEY = os.getenv("EMBED_API_KEY", "")
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-small-en-v1.5")
EMBED_CA_CERT = os.getenv("EMBED_CA_CERT", "")
if EMBED_CA_CERT and not Path(EMBED_CA_CERT).is_absolute():
    EMBED_CA_CERT = str(ROOT / EMBED_CA_CERT)

# multi-agent layer (safemine/agents): "multi" = specialised agents + supervisor, "legacy" = the original single state machine
AGENT_MODE = os.getenv("AGENT_MODE", "multi").lower()
AGENT_DEADLINE_S = float(os.getenv("AGENT_DEADLINE_S", "420"))          # wall-clock limit per question (0 = none)
STRICT_GROUNDING = os.getenv("AGENT_STRICT_GROUNDING", "false").lower() == "true"   # weakly grounded cited sentences count as unsupported
GROUNDING_MIN = float(os.getenv("AGENT_GROUNDING_MIN", "0.35"))
MAX_STEPS = int(os.getenv("MAX_STEPS", 10))
MAX_REVISIONS = int(os.getenv("MAX_REVISIONS", 2))
TOKEN_BUDGET = int(os.getenv("TOKEN_BUDGET_PER_QUERY", 12000))


def startup_checks() -> list[str]:
    """Problems that would make the app fail or silently degrade (empty list = ready). Used by /health and the UI so a
    container with a missing mount or key says so, instead of failing on the first question with a TLS traceback."""
    problems = []
    for label, p in (("DuckDB", DUCKDB_PATH), ("chunk store", CHUNKS_JSONL), ("BM25 index", BM25_PKL), ("dense index", DENSE_NPY),
                     ("corpus event index", OUT / "events_index.csv")):
        if not Path(p).exists():
            problems.append(f"{label} missing: {Path(p).name} (mount ./data_processed)")
    if not llm_configured():
        problems.append(f"no usable key for LLM provider '{LLM_PROVIDER}' (set it in .env; the offline mock would answer instead)")
    elif LLM_CA_CERT and not Path(LLM_CA_CERT).exists():
        problems.append(f"LLM CA certificate not found: {LLM_CA_CERT} (mount ./certs)")
    if EMBED_BACKEND == "endpoint":
        if not EMBED_API_KEY or "REPLACE" in EMBED_API_KEY:
            problems.append("EMBED_API_KEY is not set")
        if EMBED_CA_CERT and not Path(EMBED_CA_CERT).exists():
            problems.append(f"embeddings CA certificate not found: {EMBED_CA_CERT} (mount ./certs)")
    return problems


def llm_configured() -> bool:
    return provider_ready(LLM_PROVIDER)


def llm_label() -> str:
    name = LLM_MODEL if LLM_PROVIDER == "upgrad" else f"{DISPLAY.get(LLM_PROVIDER, LLM_PROVIDER)} · {LLM_MODEL}"
    return name if llm_configured() else f"{DISPLAY.get(LLM_PROVIDER, LLM_PROVIDER)}: API key missing (offline mock)"
