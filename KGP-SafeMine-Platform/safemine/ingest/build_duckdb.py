"""Step 3: structured + regulatory layer -> one read-only DuckDB file.

Source: the cleaned team dataset (KGP-SafeMine-Data/), Parquet tables with every column as text.

Tables
  accidents          structured_data/Accidents.parquet, only the columns the agent needs
  mines              Mines.parquet (subset)
  inspections        Inspections.parquet (subset)
  mines_prod_yearly  MinesProdYearly.parquet (hours/employees for injury rates)
  violations         Violations.parquet (subset) -- skipped if it is a Git-LFS pointer stub
  orders_107a        OrdersIssued.parquet (107(a) imminent-danger orders)
  fatal_events       one row per MSHA fatality event (from docs.jsonl): joins reports <-> accidents
  cfr_sections       versioned law store, one row per (section version x edition it appears in):
                     regulations/cfr_history/cfr_section_versions.jsonl -> edition current/snapshot/annual
  fr_rules           regulations/federal_register/federal_register_rules_index.csv (in force / proposed)

CONTROLLER/OPERATOR names are kept (companies or public mine controllers).

Run:  .venv/bin/python -m safemine.ingest.build_duckdb
"""
from __future__ import annotations

import csv
import json
import re
import shutil
from pathlib import Path

import duckdb

from safemine import config

COLS = {
    "Accidents": ["MINE_ID", "CONTROLLER_NAME", "OPERATOR_NAME", "DOCUMENT_NO", "SUBUNIT", "ACCIDENT_DT", "CAL_YR",
                  "ACCIDENT_TIME", "DEGREE_INJURY_CD", "DEGREE_INJURY", "UG_LOCATION", "UG_MINING_METHOD", "MINING_EQUIP",
                  "EQUIP_MFR_NAME", "CLASSIFICATION", "ACCIDENT_TYPE", "NO_INJURIES", "TOT_EXPER", "MINE_EXPER", "JOB_EXPER",
                  "OCCUPATION", "ACTIVITY", "INJURY_SOURCE", "NATURE_INJURY", "INJ_BODY_PART", "DAYS_LOST", "COAL_METAL_IND",
                  "NARRATIVE"],
    "Mines": ["MINE_ID", "CURRENT_MINE_NAME", "COAL_METAL_IND", "CURRENT_MINE_TYPE", "CURRENT_MINE_STATUS",
              "CURRENT_CONTROLLER_NAME", "CURRENT_OPERATOR_NAME", "STATE", "FIPS_CNTY_NM", "DISTRICT", "PRIMARY_SIC",
              "PRIMARY_CANVASS", "NO_EMPLOYEES", "LATITUDE", "LONGITUDE"],
    "Inspections": ["EVENT_NO", "MINE_ID", "INSPECTION_BEGIN_DT", "INSPECTION_END_DT", "CAL_YR", "ACTIVITY",
                    "NBR_INSPECTOR", "SUM(TOTAL_INSP_HOURS)"],
    "MinesProdYearly": ["MINE_ID", "CALENDAR_YR", "SUBUNIT_DESC", "ANNUAL_HRS", "ANNUAL_COAL_PROD", "AVG_ANNUAL_EMPL", "C_M_IND"],
    "Violations": ["MINE_ID", "VIOLATION_NO", "EVENT_NO", "VIOLATION_ISSUE_DT", "CAL_YR", "PART_SECTION", "SECTION_OF_ACT",
                   "SIG_SUB", "LIKELIHOOD", "INJ_ILLNESS", "NEGLIGENCE", "PROPOSED_PENALTY", "CONTESTED_IND", "COAL_METAL_IND"],
}
TABLE = {"Accidents": "accidents", "Mines": "mines", "Inspections": "inspections",
         "MinesProdYearly": "mines_prod_yearly", "Violations": "violations"}


def is_lfs_stub(p: Path) -> bool:
    return p.stat().st_size < 1024 and p.read_bytes().startswith(b"version https://git-lfs")


def load_msha(con, tmp: Path = None):
    for name, cols in COLS.items():
        f = config.STRUCTURED_DIR / f"{name}.parquet"
        if not f.exists() or is_lfs_stub(f):
            print(f"  SKIP {name}: missing or Git-LFS pointer stub (run `git lfs pull`)")
            continue
        have = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{f}')").fetchall()}
        keep = [c for c in cols if c in have]
        sel = ", ".join(f'"{c}" AS "{c.replace("SUM(", "").replace(")", "")}"' for c in keep)
        con.execute(f"CREATE OR REPLACE TABLE {TABLE[name]} AS SELECT {sel} FROM read_parquet('{f}')")
        n = con.execute(f"SELECT count(*) FROM {TABLE[name]}").fetchone()[0]
        print(f"  {TABLE[name]}: {n:,} rows, {len(keep)} cols")
    f = config.STRUCTURED_DIR / "OrdersIssued.parquet"
    if f.exists() and not is_lfs_stub(f):
        con.execute(f"CREATE OR REPLACE TABLE orders_107a AS SELECT * FROM read_parquet('{f}')")
        print(f"  orders_107a: {con.execute('SELECT count(*) FROM orders_107a').fetchone()[0]:,} rows")
    # typed helper columns
    con.execute("""ALTER TABLE accidents ADD COLUMN accident_date DATE;
                   UPDATE accidents SET accident_date = try_strptime(ACCIDENT_DT, '%m/%d/%Y');
                   ALTER TABLE accidents ADD COLUMN is_fatal BOOLEAN;
                   UPDATE accidents SET is_fatal = (DEGREE_INJURY_CD = '01');""")


def load_fatal_events(con):
    rows = []
    for line in open(config.DOCS_JSONL):
        d = json.loads(line)
        if d["doc_type"] not in ("final_report", "preliminary_report"):
            continue
        m = d["meta"]
        rows.append((d["event_id"], d["doc_type"], d["year"], m.get("classification") or m.get("classification_report"),
                     m.get("mine_type") or m.get("mine_category"), m.get("material") or m.get("commodity"), m.get("state"),
                     m.get("mine_id"), m.get("mine_name"), m.get("operator") or m.get("controller"),
                     m.get("date_iso") or m.get("accident_date_text") or m.get("incident_datetime"), ",".join(d["cfr_cited"]),
                     len(d["root_causes"]), d["source_path"]))
    con.execute("""CREATE OR REPLACE TABLE fatal_events (event_id VARCHAR, status VARCHAR, year INT, classification VARCHAR,
                   mine_type VARCHAR, material VARCHAR, state VARCHAR, mine_id VARCHAR, mine_name VARCHAR, operator VARCHAR,
                   date_text VARCHAR, cfr_cited VARCHAR, n_root_causes INT, source_path VARCHAR)""")
    con.executemany("INSERT INTO fatal_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.execute("""ALTER TABLE fatal_events ADD COLUMN event_date DATE;
                   UPDATE fatal_events SET event_date = coalesce(try_cast(date_text AS DATE),
                       try_strptime(regexp_extract(date_text, '[A-Z][a-z]+ \\d{1,2}, \\d{4}'), '%B %d, %Y'));""")
    print(f"  fatal_events: {len(rows)}")


CURRENT_EDITION = "2026-10-30"   # eCFR date of the current text in the dataset


def load_cfr(con):
    """cfr_section_versions.jsonl stores each distinct text once with the editions it appears in ('seen_in').
    Expand to one row per edition so cfr_lookup can pick 'latest edition on or before the incident date'."""
    rows = []
    src = config.REG_DIR / "cfr_history" / "cfr_section_versions.jsonl"
    for line in open(src, encoding="utf-8"):
        r = json.loads(line)
        sec, head, text = r["section"], (r.get("heading") or "").strip(), r["text"]
        part = sec.split(".")[0]
        for lab in r["seen_in"]:
            kind, rest = lab.split("-", 1)
            if kind == "annual":
                rows.append((part, sec, head, text, "annual", f"{rest}-07-01", lab))
            elif kind == "ecfr":
                rows.append((part, sec, head, text, "snapshot", rest, lab))
        if r.get("is_current"):
            rows.append((part, sec, head, text, "current", CURRENT_EDITION, "current"))
    con.execute("""CREATE OR REPLACE TABLE cfr_sections (part VARCHAR, section VARCHAR, subject VARCHAR, text VARCHAR,
                   edition VARCHAR, edition_date DATE, source_file VARCHAR)""")
    con.executemany("INSERT INTO cfr_sections VALUES (?,?,?,?,?,?,?)", rows)
    print(f"  cfr_sections: {len(rows):,} section-edition rows")


def load_fr(con):
    src = config.REG_DIR / "federal_register" / "federal_register_rules_index.csv"
    rows = []
    for r in csv.DictReader(open(src, encoding="utf-8")):
        try:
            parts = ",".join(str(c.get("part")) for c in json.loads(r.get("cfr_references") or "[]") if c.get("part"))
        except json.JSONDecodeError:
            parts = ""
        kind = "proposed" if "propos" in (r.get("kind") or "").lower() else "final"
        rows.append((r["document_number"], kind, r.get("title"), r.get("publication_date") or None,
                     r.get("effective_on") or None, r.get("action"), (r.get("abstract") or "")[:2000], parts, r.get("html_url")))
    con.execute("""CREATE OR REPLACE TABLE fr_rules (document_number VARCHAR, kind VARCHAR, title VARCHAR, publication_date DATE,
                   effective_on DATE, action VARCHAR, abstract VARCHAR, cfr_parts VARCHAR, html_url VARCHAR)""")
    con.executemany("INSERT INTO fr_rules VALUES (?,?,?,?,?,?,?,?,?)", rows)
    print(f"  fr_rules: {len(rows)} ({sum(r[1] == 'final' for r in rows)} final)")


def main():
    config.OUT.mkdir(parents=True, exist_ok=True)
    tmp = config.OUT / "_tmp"
    tmp.mkdir(exist_ok=True)
    con = duckdb.connect(str(config.DUCKDB_PATH))
    try:
        print("MSHA open data:")
        load_msha(con, tmp)
        print("Fatality events / law store / rule status:")
        load_fatal_events(con)
        load_cfr(con)
        load_fr(con)
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
    print("wrote", config.DUCKDB_PATH)


if __name__ == "__main__":
    main()
