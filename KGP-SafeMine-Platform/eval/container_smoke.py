"""Smoke test for a RUNNING container (or local API): `docker compose up -d`, wait about a minute, then

    python eval/container_smoke.py [http://localhost:8000]

It asks questions that need each part of the stack and fails if any of them cannot do its job. Unlike /health it exercises the search
index, the reranker, the embedding endpoint and the model: a container that cannot read its index still reports "healthy" but answers
"no evidence" to every question that needs retrieval (this happened: the index recorded a Windows path that Linux could not open).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
CASES = [  # (label, question, must have evidence from search?)
    ("retrieval: named incident", "What root cause does the investigation report identify for the fatal electrical accident at American Eagle Mine on September 17, 2019?", True),
    ("retrieval: pattern", "What root causes did MSHA find for conveyor fatalities at surface mines since 2018?", True),
    ("statistics", "How many fatal accidents by classification since 2015?", False),
    ("30 CFR", "What does 30 CFR 56.14211 require?", False),
]


def ask(q: str, sid: str) -> dict:
    req = urllib.request.Request(BASE + "/ask", data=json.dumps({"question": q, "session_id": sid}).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=600))


def main() -> int:
    health = json.load(urllib.request.urlopen(BASE + "/health", timeout=20))
    print("health:", health)
    bad = 0
    for label, q, needs_search in CASES:
        t = time.time()
        r = ask(q, f"smoke-{int(t)}")
        errs = [e for e in r["trace"] if "error" in e["kind"]]
        searched = any(e["kind"] == "tool" and e.get("tool") == "hybrid_search" and e.get("n_evidence") for e in r["trace"])
        problems = []
        if r["status"] != "answered":
            problems.append(f"status {r['status']}")
        if errs:
            problems.append("errors: " + "; ".join(f"{e['kind']}: {str(e.get('error'))[:100]}" for e in errs))
        if needs_search and not searched:
            problems.append("no evidence came from the search index")
        bad += bool(problems)
        print(f"{'FAIL' if problems else 'ok  '} {label:28s} {r['status']:10s} {time.time() - t:5.1f}s  {'; '.join(problems)}")
    print("\n" + ("all checks passed" if not bad else f"{bad} check(s) failed"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
