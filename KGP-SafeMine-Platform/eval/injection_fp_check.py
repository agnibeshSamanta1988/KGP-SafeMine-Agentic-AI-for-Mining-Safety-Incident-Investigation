"""False-positive check for the evidence cleaner: run it over the WHOLE corpus (10,990 report chunks) and the 30 CFR store, and over answers
the system already gave. Every sentence it would remove is a real sentence lost, so the target is zero.

    python eval/injection_fp_check.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from safemine import config  # noqa: E402
from safemine.agent import injection  # noqa: E402


def main() -> int:
    kinds, samples, n_sent_removed, n_chunks_hit = Counter(), [], 0, 0
    total = 0
    for line in open(config.CHUNKS_JSONL, encoding="utf-8"):
        c = json.loads(line)
        total += 1
        cleaned, n, ks = injection.clean(c["text"])
        if n:
            n_chunks_hit += 1
            n_sent_removed += n
            kinds.update(ks)
            if len(samples) < 12:
                for sent in injection._SPLIT.split(injection.normalize(c["text"])):
                    k = injection.classify(sent)
                    if k:
                        samples.append((k, c["chunk_id"], sent.strip()[:200]))
    print(f"report chunks scanned: {total} | chunks with a removal: {n_chunks_hit} | sentences removed: {n_sent_removed} | by rule: {dict(kinds)}")
    import duckdb
    con = duckdb.connect(str(config.DUCKDB_PATH), read_only=True)
    rows = con.execute("select section, text from cfr_sections").fetchall()
    cfr_hit = 0
    for sec, text in rows:
        _, n, ks = injection.clean(text or "")
        if n:
            cfr_hit += 1
            kinds.update(ks)
            if len(samples) < 24:
                for sent in injection._SPLIT.split(injection.normalize(text)):
                    k = injection.classify(sent)
                    if k:
                        samples.append((k, "30 CFR " + sec, sent.strip()[:200]))
    print(f"CFR sections scanned: {len(rows)} | sections with a removal: {cfr_hit}")
    import sqlite3
    db = sqlite3.connect(config.OUT / "sessions.sqlite")
    ans = [r[0] for r in db.execute("select answer from turns where status='answered'")]
    leaked = sum(1 for a in ans if any(injection.has_prompt_text(s) for s in injection._SPLIT.split(a) if s.strip()))
    print(f"stored answers checked for the prompt-leak filter: {len(ans)} | flagged: {leaked}")
    for k, where, s in samples:
        print(f"  [{k}] {where}: {s}")
    return 1 if (n_sent_removed or cfr_hit or leaked) else 0


if __name__ == "__main__":
    sys.exit(main())
