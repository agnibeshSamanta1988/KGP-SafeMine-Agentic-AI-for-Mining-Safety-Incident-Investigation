"""Verified, dynamically computed facts about the data behind KGP-SafeMine (used by the Home page).

Everything here is read from the processed corpus and DuckDB tables, never typed in. The raw-document folders (PDF counts of the policy
handbooks, major-disaster reports, reference statistics) exist only on the developer machine, so their counts come from
`data_processed/data_manifest.json`, written by `python -m app.meta` (and refreshed on the fly when the raw folder is reachable).
A value that cannot be determined is returned as None and shown as "not available", never guessed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import streamlit as st  # noqa: E402

from safemine import config  # noqa: E402

MANIFEST = config.OUT / "data_manifest.json"
RAW_DIRS = {"fatality_files": "fatality_investigations", "major_disaster_reports": "major_disaster_investigations",
            "policy_documents": "policy_and_guidance", "reference_statistics_files": "reference_statistics",
            "regulation_files": "regulations", "structured_files": "structured_data"}


def _raw_root() -> Path | None:
    for p in (config.ROOT.parent / "KGP-SafeMine-Data", config.ROOT / "data"):
        if p.exists() and (p / "regulations").exists():
            return p
    return None


def build_manifest() -> dict:
    """Count the raw files per source folder (only possible where the raw folder exists)."""
    root = _raw_root()
    if root is None:
        return {}
    out = {k: sum(1 for f in (root / d).rglob("*") if f.is_file()) for k, d in RAW_DIRS.items() if (root / d).exists()}
    pol = root / "policy_and_guidance"
    out["policy_titles"] = sorted(f.stem.replace("_", " ") for f in pol.glob("*.pdf")) if pol.exists() else []
    out["generated"] = datetime.now().strftime("%Y-%m-%d")
    return out


def raw_counts() -> dict:
    live = build_manifest()
    if live:
        try:
            MANIFEST.write_text(json.dumps(live, indent=1), encoding="utf-8")
        except OSError:
            pass
        return live
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _q(con, sql: str):
    try:
        return con.execute(sql).fetchall()
    except Exception:  # noqa: BLE001  a missing table or column means "not available", not a crash
        return None


def _span(con, table: str, col: str) -> tuple | None:
    r = _q(con, f"select min(cast({col} as varchar)), max(cast({col} as varchar)) from {table}")
    return (r[0][0], r[0][1]) if r and r[0][0] else None


def _us_year(s: str) -> str:
    """'01/01/2000' -> '2000' ; '2000' stays."""
    return s[-4:] if "/" in s else s[:4]


@st.cache_data(show_spinner="Loading platform facts …", ttl=600)
def data_facts() -> dict:
    """The facts the Home page shows. Cached for ten minutes; keys whose source is missing are simply absent."""
    f: dict = {"problems": []}
    db = config.DUCKDB_PATH
    if not Path(db).exists():
        f["problems"].append("DuckDB file missing")
        return f
    import duckdb
    con = duckdb.connect(str(db), read_only=True)
    try:
        def n(t):
            r = _q(con, f"select count(*) from {t}")
            return r[0][0] if r else None
        for k, t in (("accidents", "accidents"), ("mines", "mines"), ("violations", "violations"), ("inspections", "inspections"),
                     ("production", "mines_prod_yearly"), ("orders", "orders_107a"), ("fr_rules", "fr_rules"), ("fatal_events", "fatal_events"),
                     ("cfr_rows", "cfr_sections")):
            f[k] = n(t)
        f["span_accidents"] = _span(con, "accidents", "CAL_YR")          # the date columns are MM/DD/YYYY text: min/max would sort wrongly
        f["span_violations"] = _span(con, "violations", "CAL_YR")
        f["span_fatal"] = _span(con, "fatal_events", "year")
        f["span_inspections"] = _span(con, "inspections", "CAL_YR")
        f["span_production"] = _span(con, "mines_prod_yearly", "CALENDAR_YR")
        f["span_fr"] = _span(con, "fr_rules", "publication_date")
        r = _q(con, "select count(distinct MINE_ID || '-' || CALENDAR_YR), count(distinct MINE_ID) from mines_prod_yearly")   # rows are per mine, sub-unit AND year
        f["production_mine_years"], f["production_mines"] = (r[0][0], r[0][1]) if r else (None, None)
        r = _q(con, "select count(distinct edition_date), count(distinct part || '-' || section), min(edition_date), max(edition_date) from cfr_sections")
        if r:
            f["cfr_editions"], f["cfr_sections"], f["cfr_first"], f["cfr_last"] = r[0]
        r = _q(con, "select count(distinct part) from cfr_sections where edition='current'")
        f["cfr_parts_current"] = r[0][0] if r else None
        r = _q(con, "select edition_date from cfr_sections where edition='current' limit 1")
        f["cfr_current_date"] = str(r[0][0]) if r else None
    finally:
        con.close()
    # corpus of investigation reports (documents and retrievable passages)
    docs = config.OUT / "docs.jsonl"
    if docs.exists():
        by: dict[str, int] = {}
        for line in docs.open(encoding="utf-8"):
            if line.strip():
                t = json.loads(line).get("doc_type", "?")
                by[t] = by.get(t, 0) + 1
        f["docs_by_type"] = by
        f["docs_total"] = sum(by.values())
    ch = Path(config.CHUNKS_JSONL)
    if ch.exists():
        f["chunks"] = sum(1 for line in ch.open(encoding="utf-8") if line.strip())
    ev = config.OUT / "events_index.csv"
    if ev.exists():
        f["events_indexed"] = max(0, sum(1 for _ in ev.open(encoding="utf-8")) - 1)
    for k, p in (("db_updated", Path(db)), ("corpus_updated", ch)):
        if p.exists():
            f[k] = datetime.fromtimestamp(p.stat().st_mtime).strftime("%d %b %Y")
    try:
        from safemine.agent.orchestrator import SNAPSHOT_END
        f["snapshot"] = SNAPSHOT_END.strftime("%d %B %Y")
    except Exception:  # noqa: BLE001
        pass
    f["raw"] = raw_counts()
    return f


def years(span: tuple | None) -> str:
    return "not available" if not span else (f"{_us_year(str(span[0]))}–{_us_year(str(span[1]))}")


def num(v) -> str:
    return "n/a" if v is None else f"{int(v):,}"


if __name__ == "__main__":
    m = build_manifest()
    MANIFEST.write_text(json.dumps(m, indent=1), encoding="utf-8")
    print(json.dumps(m, indent=1))
