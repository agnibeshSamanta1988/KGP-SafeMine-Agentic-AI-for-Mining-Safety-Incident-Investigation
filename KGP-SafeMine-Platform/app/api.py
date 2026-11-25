"""FastAPI service.  .venv/bin/uvicorn app.api:app --port 8000"""
import os
import time
import uuid
import warnings
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

warnings.filterwarnings("ignore")
from safemine import config  # noqa: E402
from safemine.agent import orchestrator as O  # noqa: E402
from safemine.agent.llm import Usage  # noqa: E402
from safemine.agent.orchestrator import Agent  # noqa: E402

from safemine.tools.hybrid_search import warmup  # noqa: E402

# default model = Qwen3-8B whenever its key works (same rule as the console); API_LLM_PROVIDER overrides it explicitly
config.set_provider(os.getenv("API_LLM_PROVIDER") or ("upgrad" if config.provider_ready("upgrad") else config.LLM_PROVIDER))
warmup()   # load indexes and models in the background: the first question should not wait for them
app = FastAPI(title="KGP-SafeMine", version="0.1-poc")
agent = Agent()
_hits: dict[str, deque] = defaultdict(deque)
_cache: dict[str, dict] = {}
RATE = (10, 60)  # 10 requests / 60 s per client


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    session_id: str = "default"


class Review(BaseModel):
    turn_id: str
    decision: str = Field(pattern="^(approve|flag|reject)$")


@app.post("/ask")
def ask(body: Ask, request: Request):
    ip = request.client.host if request.client else "?"
    q = _hits[ip]
    now = time.time()
    while q and now - q[0] > RATE[1]:
        q.popleft()
    if len(q) >= RATE[0]:
        raise HTTPException(429, "rate limit: 10 questions per minute")
    q.append(now)
    key = body.question.strip().lower()
    if key in _cache:
        # a repeated question is served from memory, but it is still a turn: it gets its own id, is saved to the history and traced
        t0 = time.time()
        src = _cache[key]
        res = {k: v for k, v in src.items() if k not in ("turn_id", "session_id", "latency_s", "usage", "agent_trail")}
        res["trace"] = [{"t": 0.0, "kind": "cache_hit", "source_turn": src.get("turn_id")}]   # no tool or model call ran for this turn
        res["cached"] = True
        return O.finalize(agent.store, res, body.session_id, uuid.uuid4().hex[:12], body.question, Usage(), t0)
    res = agent.run(body.question, session_id=body.session_id)
    if res["status"] == "answered":
        _cache[key] = res
    return res


@app.post("/review")
def review(body: Review):
    if not agent.store.set_review(body.turn_id, body.decision):
        raise HTTPException(404, "no such turn")
    return {"ok": True}


@app.get("/health")
def health():
    problems = config.startup_checks()
    if problems:
        raise HTTPException(503, {"ok": False, "problems": problems})
    from safemine import tracing
    return {"ok": True, "tracing": tracing.status(block=True)}
