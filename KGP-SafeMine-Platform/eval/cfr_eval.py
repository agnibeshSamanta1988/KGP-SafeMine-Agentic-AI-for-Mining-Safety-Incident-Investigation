"""cfr_lookup check on the benchmark v2.0 regulation rows (Family B, deterministic, no LLM).

  Regulation Lookup       exact lookup of the cited section returns text (current edition)
  Section Identification  search by the quoted title finds the gold section in the top 5
  Time-Dependent Law      2008 annual edition and current text both resolve (as_of 2008-07-01 vs today)

Run:  .venv/bin/python -m eval.cfr_eval
"""
from __future__ import annotations

import json
import re
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

from eval.retrieval_eval import GOLDEN, load_rows  # noqa: E402
from safemine.tools.cfr_lookup import cfr_lookup  # noqa: E402


def main():
    out = []
    for r in load_rows(GOLDEN):
        m = re.match(r"^30 CFR (\d{1,3}\.\d+[a-z]?)", r["Primary Gold Evidence Source"].strip())
        if not m:
            continue
        sec, sub, q = m.group(1), r["Subtype"], r["Evaluation Query"]
        if sub == "Section Identification":
            title = (re.search(r'"([^"]+)"', q) or re.search(r"is (.+?) covered", q)).group(1)
            res = cfr_lookup(mode="search", query=title, k=5).get("results", [])
            ok, detail = any(x["section"] == sec for x in res), [x["section"] for x in res]
        elif sub == "Time-Dependent Law":
            old, new = cfr_lookup(mode="exact", section=sec, as_of="2008-07-01"), cfr_lookup(mode="exact", section=sec)
            ok = bool(old.get("text")) and old.get("edition") == "annual" and bool(new.get("text"))
            detail = [old.get("edition_date"), new.get("edition_date"), "changed" if old.get("text") != new.get("text") else "same"]
        else:
            res = cfr_lookup(mode="exact", section=sec)
            ok, detail = bool(res.get("text")), res.get("version_status")
        out.append({"id": r["Query ID"], "split": r["Split"], "subtype": sub, "section": sec, "ok": ok, "detail": detail})
        print(("PASS " if ok else "FAIL ") + f"{r['Query ID']} {sub:24} {sec:10} {detail}")
    n = sum(x["ok"] for x in out)
    print(f"\ncfr_lookup: {n}/{len(out)} pass")
    json.dump(out, open("eval/cfr_results_v2.json", "w"), indent=1)


if __name__ == "__main__":
    main()
