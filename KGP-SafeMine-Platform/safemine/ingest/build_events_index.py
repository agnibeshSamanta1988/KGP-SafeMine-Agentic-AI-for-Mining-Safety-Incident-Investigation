"""Copy the corpus event index (one row per MSHA fatality event, 665 rows) into data_processed/events_index.csv.

Why: accident_stats.corpus_events answers "how many fatality events does the corpus list for <year>?" and "how many do not
have a final report yet?". The DuckDB `fatal_events` table cannot answer that: it only holds the 655 events that have a PDF
dossier (10 events have none), and the Accidents table counts accident rows, not events.

Only non-sensitive columns are kept (event id, date, classification, mine, state, mine type, final-report flag).

Run:  python -m safemine.ingest.build_events_index
"""
from __future__ import annotations

import csv

from safemine import config

KEEP = ["event_id", "year", "incident_date", "classification", "mine", "state", "mine_type", "has_final_report", "pdf_dossier"]


def main() -> None:
    config.OUT.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open(config.EVENTS_INDEX, encoding="utf-8")))
    out = config.OUT / "events_index.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=KEEP)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in KEEP})
    print(f"{len(rows)} events -> {out}")


if __name__ == "__main__":
    main()
