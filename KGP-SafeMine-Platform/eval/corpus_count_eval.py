"""Held-out check for "how many fatality events does the corpus list ..." questions, generated from the event index
(data_processed/events_index.csv); gold = the count computed straight from that file.

Run:  python -m eval.corpus_count_eval [--seed 4] [--tag name]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import warnings
from collections import Counter

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")


def build(seed: int) -> list[dict]:
    rows = list(csv.DictReader(open("data_processed/events_index.csv", encoding="utf-8")))
    rnd, out = random.Random(seed), []
    years = sorted({r["year"] for r in rows})
    for y in rnd.sample(years, 4):
        n = sum(r["year"] == y for r in rows)
        out.append({"q": f"How many fatality events does the MSHA fatality-report corpus list for {y}?", "gold": n})
    for y in rnd.sample([y for y in years if int(y) >= 2020], 2):
        n = sum(r["year"] == y and r["has_final_report"] == "False" for r in rows)
        out.append({"q": f"How many of the {y} fatality events in the corpus do not have a final report yet?", "gold": n})
    for y in rnd.sample([y for y in years if int(y) >= 2015], 2):
        n = sum(r["year"] == y and r["has_final_report"] == "True" for r in rows)
        out.append({"q": f"What is the number of fatality events in the corpus index for {y} that have a final investigation report?", "gold": n})
    top = Counter(r["classification"] for r in rows).most_common(4)
    for cls, _ in rnd.sample(top, 2):
        y = rnd.choice(years)
        n = sum(r["year"] == y and r["classification"] == cls for r in rows)
        out.append({"q": f"How many events in the corpus are classified as {cls.lower()} in {y}?", "gold": n})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=4)
    ap.add_argument("--tag", default="run")
    a = ap.parse_args()
    from safemine.agent.orchestrator import Agent
    ag, items, ok, rows = Agent(), build(a.seed), 0, []
    for i, it in enumerate(items):
        r = ag.run(it["q"], session_id=f"cc-{a.tag}-{i}")
        ans = re.sub(r"\n*---\n\*Decision support.*", "", r["answer"], flags=re.S)
        good = r["status"] == "answered" and re.search(rf"(?<![\d.]){it['gold']}(?!\d)", ans.replace(",", "")) is not None
        ok += good
        rows.append({**it, "status": r["status"], "pass": good, "answer": ans[:200]})
        print(f"{'PASS' if good else 'fail'} gold={it['gold']:>3} {r['status']:9} {r['latency_s']:>5}s | {it['q'][:78]}", flush=True)
    print(f"\ncorpus-count hold-out [{a.tag}]: {ok}/{len(items)} = {ok / len(items):.0%}")
    json.dump(rows, open(f"eval/results/corpus_count_{a.tag}.json", "w"), indent=1)


if __name__ == "__main__":
    main()
