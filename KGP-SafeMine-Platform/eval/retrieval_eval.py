"""Retrieval-only evaluation (Track B: measure recall@k separately from answer quality).

Query sources:
  --golden (default)  team benchmark v2.0, eval/golden/KGP_SafeMine_100_Golden_Evaluation_Queries.csv (100 queries,
                      DEV 14 / TEST 86). Retrieval is scored on the rows whose "Primary Gold Evidence Source" is an
                      MSHA fatality report ("MSHA fatality report 2019/september-17-2019-fatality (doc#ROOT CAUSE
                      ANALYSIS)"); CFR rows are checked with cfr_lookup (eval/cfr_eval.py); abstention, refusal and
                      statistics rows need the end-to-end agent run.
  --proxy N           synthetic: fatality-alert summary -> same event's final report.

Metrics
  event level: Recall@1/5/10, MRR@10, nDCG@10 (ranking of distinct events)
  section level: Ev@8 = the 8 evidence chunks the agent actually reads (default hybrid_search settings) contain the
                 gold event's gold section (ROOT CAUSE ANALYSIS -> ROOT_CAUSE, ENFORCEMENT ACTIONS -> ENFORCEMENT,
                 OVERVIEW -> SUMMARY); only rows that name a section.
Configs: one per --tags (chunk strategy) x {bm25, bm25+rerank, hybrid, hybrid+rerank}.

Examples:
  .venv/bin/python -m eval.retrieval_eval                         # all report rows, section450
  .venv/bin/python -m eval.retrieval_eval --split DEV --tags "" fixed450
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sys
import time
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

from safemine import config  # noqa: E402
from safemine.tools.hybrid_search import Retriever, SearchArgs  # noqa: E402


GOLDEN = "eval/golden/KGP_SafeMine_100_Golden_Evaluation_Queries.csv"
REPORT_SRC = re.compile(r"^MSHA fatality report (\d{4}/[a-z0-9-]+)(?:\s*\(doc#([A-Z ]+)\))?")
SECTION_MAP = {"ROOT CAUSE ANALYSIS": "ROOT_CAUSE", "ENFORCEMENT ACTIONS": "ENFORCEMENT", "OVERVIEW": "SUMMARY",
               "CONCLUSION": "SUMMARY", "DISCUSSION": "DISCUSSION", "DESCRIPTION OF THE ACCIDENT": "DESCRIPTION",
               "INVESTIGATION OF THE ACCIDENT": "INVESTIGATION", "GENERAL INFORMATION": "GENERAL_INFORMATION"}


def load_rows(path=GOLDEN):
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))


def load_golden(path=GOLDEN, split=None):
    """Benchmark v2.0 rows with a fatality-report gold -> [{id, q, gold:{event}, section, family, subtype, split}]."""
    out = []
    for r in load_rows(path):
        if split and r["Split"].upper() != split.upper():
            continue
        m = REPORT_SRC.match(r["Primary Gold Evidence Source"].strip())
        if not m:
            continue
        out.append({"id": r["Query ID"], "q": r["Evaluation Query"], "gold": {m.group(1)},
                    "section": SECTION_MAP.get((m.group(2) or "").strip()), "family": r["Task Family"].split(":")[0],
                    "subtype": r["Subtype"], "split": r["Split"]})
    return out


def proxy_queries(n, seed=7):
    docs = [json.loads(l) for l in open(config.DOCS_JSONL)]
    finals = {d["event_id"] for d in docs if d["doc_type"] == "final_report"}
    qs = []
    for d in docs:
        if d["doc_type"] != "fatality_alert" or d["event_id"] not in finals:
            continue
        s = " ".join(p for b in d["sections"]["ALERT_SUMMARY"] for p in b["paras"])
        s = re.sub(r"^MINE FATALITY\s*[–-]\s*", "", s)
        s = re.sub(r"On\s+\w+\s+\d{1,2},\s+\d{4},?\s*", "", s)
        s = re.sub(r"\b(19|20)\d\d\b", "", s)
        if len(s) > 60:
            qs.append({"q": s[:400], "gold": {d["event_id"]}})
    random.Random(seed).shuffle(qs)
    return qs[:n]


def metrics(ranked_events, gold):
    first = next((i for i, e in enumerate(ranked_events[:10]) if e in gold), None)
    dcg = sum(1 / math.log2(i + 2) for i, e in enumerate(ranked_events[:10]) if e in gold)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(gold), 10)))
    return {"R@1": float(first == 0), "R@5": float(first is not None and first < 5), "R@10": float(first is not None),
            "MRR": 1 / (first + 1) if first is not None else 0.0, "nDCG@10": dcg / idcg if idcg else 0.0}


def evidence_hit(ret, q, rerank, dense, event, section, k=8):
    """Do the k evidence chunks the agent reads (default search, all doc types) contain event+section?"""
    ret.reranker = ret._rr if rerank else None
    saved = ret.dense
    if not dense:
        ret.dense = None
    res = ret.search(SearchArgs(query=q[:500], k=k))
    ret.dense = saved
    return float(any(c["event_id"] == event and c["section"] == section for c in res))


def ranked_events(ret, q, rerank, dense):
    a = SearchArgs(query=q[:500], doc_types=["final_report", "preliminary_report"], k=12)
    ret.reranker = ret._rr if rerank else None
    saved = ret.dense
    if not dense:
        ret.dense = None
    res = ret.search(a, per_event=1)
    ret.dense = saved
    seen, out = set(), []
    for c in res:
        if c["event_id"] not in seen:
            seen.add(c["event_id"])
            out.append(c["event_id"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", default=GOLDEN)
    ap.add_argument("--split", default=None, help="DEV | TEST (default: both)")
    ap.add_argument("--proxy", type=int, default=0)
    ap.add_argument("--tags", nargs="+", default=[""])
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--out", default="eval/retrieval_results_v2.json")
    a = ap.parse_args()
    qs = proxy_queries(a.proxy) if a.proxy else load_golden(a.golden, a.split)
    print(f"{len(qs)} queries ({'proxy' if a.proxy else 'benchmark v2.0, split=' + (a.split or 'DEV+TEST')})")
    table = []
    for tag in a.tags:
        ret = Retriever(tag=tag, use_rerank=not a.no_rerank)
        ret._rr = ret.reranker
        modes = [("bm25", False, False)] + ([("bm25+rerank", True, False)] if ret._rr else [])
        if ret.dense is not None:
            modes += [("hybrid", False, True)] + ([("hybrid+rerank", True, True)] if ret._rr else [])
        for name, rr, dn in modes:
            t = time.time()
            agg, bycat, ev, misses = {}, {}, [], []
            for q in qs:
                m = metrics(ranked_events(ret, q["q"], rr, dn), q["gold"])
                for k, v in m.items():
                    agg[k] = agg.get(k, 0) + v
                c = bycat.setdefault(q.get("subtype") or "proxy", [0, 0])
                c[0] += m["R@5"]; c[1] += 1
                if not m["R@10"]:
                    misses.append(q.get("id"))
                if q.get("section") and tag in ("", "default", "section450"):
                    ev.append(evidence_hit(ret, q["q"], rr, dn, next(iter(q["gold"])), q["section"]))
            row = {"chunks": tag or "section450", "retriever": name, "n": len(qs),
                   **{k: round(v / len(qs), 3) for k, v in agg.items()},
                   **({"Ev@8_section": round(sum(ev) / len(ev), 3), "n_section": len(ev)} if ev else {}),
                   "s/query": round((time.time() - t) / len(qs), 2),
                   "R@5_by_subtype": {k: round(v[0] / v[1], 3) for k, v in bycat.items()},
                   "missed_R@10": misses}
            table.append(row)
            print(row, flush=True)
    json.dump(table, open(a.out, "w"), indent=1)
    print("saved", a.out)


if __name__ == "__main__":
    main()
