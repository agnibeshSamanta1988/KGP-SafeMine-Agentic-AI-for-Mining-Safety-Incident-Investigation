"""Held-out check for identifier questions (accident by DOCUMENT_NO, inspection by EVENT_NO, mine by MINE_ID, last inspection
before a date, fatality reports citing a standard). The benchmark has no such questions, so they are generated from the
DuckDB tables with the gold read from the same rows: a pass means the agent fetched the right record and reported it.

Run:  python -m eval.record_lookup_eval [--seed 3] [--tag name]
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")


def fmt_dates(mdy: str) -> list[str]:
    d = datetime.strptime(mdy, "%m/%d/%Y")
    return [mdy, d.strftime("%Y-%m-%d"), f"{d:%B} {d.day}, {d.year}", f"{d:%B} {d.day:02d}, {d.year}", f"{d.day} {d:%B} {d.year}"]


def build(seed: int) -> list[dict]:
    from safemine.tools.accident_stats import _con
    con, rnd, out = _con(), random.Random(seed), []
    acc = con.execute("""SELECT DOCUMENT_NO, ACCIDENT_DT, CLASSIFICATION FROM accidents WHERE is_fatal AND CAL_YR >= '2005'
                         AND DOCUMENT_NO IN (SELECT DOCUMENT_NO FROM accidents GROUP BY 1 HAVING count(*) = 1)""").fetchall()
    for doc, dt, cls in rnd.sample(acc, 4):
        out.append({"kind": "accident", "q": f"What was the classification and the date of the accident with document number {doc}?",
                    "must_all": [[cls.lower()], [x.lower() for x in fmt_dates(dt)]]})
    ins = con.execute("""SELECT EVENT_NO, INSPECTION_BEGIN_DT, ACTIVITY FROM inspections WHERE CAL_YR >= '2015'
                         AND EVENT_NO IN (SELECT EVENT_NO FROM inspections GROUP BY 1 HAVING count(*) = 1)""").fetchall()
    for ev, dt, act in rnd.sample(ins, 4):
        out.append({"kind": "inspection", "q": f"What was the activity type of the inspection with event number {ev}, and when did it begin?",
                    "must_all": [[act.lower()], [x.lower() for x in fmt_dates(dt)]]})
    mines = con.execute("""SELECT MINE_ID, CURRENT_MINE_NAME, CURRENT_MINE_TYPE FROM mines WHERE CURRENT_MINE_STATUS = 'Active'
                           AND length(CURRENT_MINE_NAME) > 5""").fetchall()
    for mid, name, mtype in rnd.sample(mines, 4):
        out.append({"kind": "mine", "q": f"What is the name and mine type of mine ID {mid}?", "must_all": [[name.lower().replace(",", "")], [mtype.lower()]]})
    cand = con.execute("""SELECT MINE_ID, count(*) n FROM inspections WHERE CAL_YR >= '2012' GROUP BY 1 HAVING n BETWEEN 8 AND 30""").fetchall()
    for mid, _ in rnd.sample(cand, 3):
        before = "01/01/2020"
        row = con.execute("""SELECT INSPECTION_BEGIN_DT FROM inspections WHERE MINE_ID = ? AND try_strptime(INSPECTION_BEGIN_DT,'%m/%d/%Y') < DATE '2020-01-01'
                             ORDER BY try_strptime(INSPECTION_BEGIN_DT,'%m/%d/%Y') DESC LIMIT 1""", [mid]).fetchone()
        if row:
            out.append({"kind": "last_inspection", "q": f"When did the last inspection at mine ID {mid} begin before January 1, 2020?",
                        "must_all": [[x.lower() for x in fmt_dates(row[0])]]})
    secs = con.execute("""SELECT s, count(*) n FROM (SELECT unnest(string_split(cfr_cited, ',')) s FROM fatal_events WHERE cfr_cited <> '')
                          GROUP BY 1 HAVING n BETWEEN 3 AND 60""").fetchall()
    for sec, n in rnd.sample(secs, 3):
        out.append({"kind": "reports_citing", "q": f"How many fatality reports cited 30 CFR {sec}?", "must_all": [[str(n)]], "number": True})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--tag", default="run")
    a = ap.parse_args()
    from safemine.agent.orchestrator import Agent
    ag, items, ok, rows = Agent(), build(a.seed), 0, []
    for i, it in enumerate(items):
        r = ag.run(it["q"], session_id=f"rec-{a.tag}-{i}")
        ans = re.sub(r"\n*---\n\*Decision support.*", "", r["answer"], flags=re.S).lower().replace(",", "")
        good = r["status"] == "answered" and all(
            any((re.search(rf"(?<![\d.]){re.escape(x)}(?!\d)", ans) if it.get("number") else x in ans) for x in alts) for alts in it["must_all"])
        ok += good
        rows.append({"kind": it["kind"], "q": it["q"], "status": r["status"], "pass": good, "answer": ans[:240]})
        print(f"{'PASS' if good else 'fail'} {it['kind']:16} {r['status']:9} {r['latency_s']:>5}s | {it['q'][:75]}", flush=True)
    print(f"\nrecord_lookup hold-out [{a.tag}]: {ok}/{len(items)} = {ok / len(items):.0%}")
    json.dump(rows, open(f"eval/results/record_lookup_{a.tag}.json", "w"), indent=1)


if __name__ == "__main__":
    main()
