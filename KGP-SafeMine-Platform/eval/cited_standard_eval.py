"""Held-out check for "which 30 CFR standard did MSHA cite after the <date> fatality at <mine>?" questions.

The 100-question benchmark has only a handful of these (and TEST is spent), so this builds fresh ones from the corpus itself:
  * events with a final report whose ENFORCEMENT chunks say "violation of 30 CFR <section>"
  * every event used anywhere in the benchmark is excluded
  * gold = the set of sections cited as violated in that event's own chunks; the answer must contain at least one of them
It measures the mechanism (does the agent retrieve the incident and read its citations), not wording.

Run:  python -m eval.cited_standard_eval [--n 20] [--seed 5] [--tag name]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
import warnings
from collections import defaultdict
from datetime import datetime

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

TEMPLATES = [
    "Which 30 CFR standard did MSHA cite as violated after the {d} fatality at {m}?",
    "Under which 30 CFR provision was the operator cited following the fatal accident at {m} on {d}?",
    "What 30 CFR section appears in the citation issued for the fatality at {m} on {d}?",
]
EVENT = re.compile(r"(\d{4}/[a-z0-9-]+)")
VIOL = re.compile(r"violation of 30 CFR\s*§?\s*(\d{2,3}\.\d+)", re.I)


def build(n: int, seed: int) -> list[dict]:
    used = set()
    for r in csv.DictReader(open("eval/golden/KGP_SafeMine_100_Golden_Evaluation_Queries.csv", encoding="utf-8-sig")):
        used.update(EVENT.findall(r["Primary Gold Evidence Source"] + " " + r["Gold Reference Answer / Key Points"]))
    ev = defaultdict(lambda: {"gold": set(), "mine": None, "date": None})
    for line in open("data_processed/chunks.jsonl", encoding="utf8"):
        c = json.loads(line)
        if c["doc_type"] != "final_report" or c["section"] != "ENFORCEMENT" or c["event_id"] in used:
            continue
        found = VIOL.findall(c["text"])
        if found and c.get("mine_name") and c.get("date"):
            e = ev[c["event_id"]]
            e["gold"].update(found)
            e["mine"], e["date"] = c["mine_name"], c["date"]
    ids = sorted(ev)
    random.Random(seed).shuffle(ids)
    out = []
    for i, eid in enumerate(ids[:n]):
        d = datetime.strptime(ev[eid]["date"], "%Y-%m-%d")
        q = TEMPLATES[i % 3].format(d=f"{d:%B} {d.day}, {d.year}", m=ev[eid]["mine"])
        out.append({"event": eid, "query": q, "gold": sorted(ev[eid]["gold"])})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--tag", default="run")
    a = ap.parse_args()
    from safemine.agent.orchestrator import Agent
    items, ag, ok, rows = build(a.n, a.seed), None, 0, []
    ag = Agent()
    for it in items:
        t0 = time.time()
        r = ag.run(it["query"], session_id=f"cited-{a.tag}-{it['event']}")
        ans = re.sub(r"\n*---\n\*Decision support.*", "", r["answer"], flags=re.S)
        hit = r["status"] == "answered" and any(g in ans for g in it["gold"])
        ok += hit
        rows.append({**it, "status": r["status"], "hit": hit, "answer": ans[:300]})
        print(f"{'PASS' if hit else 'fail'} {r['status']:9} {r['latency_s']:>5}s gold={it['gold']} | {it['query'][:70]}", flush=True)
    print(f"\ncited-standard hold-out [{a.tag}]: {ok}/{len(items)} = {ok / len(items):.0%}  "
          f"(answered {sum(r['status'] == 'answered' for r in rows)}, abstained {sum(r['status'] == 'abstained' for r in rows)})")
    json.dump(rows, open(f"eval/results/cited_standard_{a.tag}.json", "w"), indent=1)


if __name__ == "__main__":
    main()
