"""accident_stats: analytical queries over DuckDB.

The LLM never writes SQL. It picks a whitelisted `metric` and filters; arguments are validated by pydantic
and bound as SQL parameters. This removes SQL-injection and malformed-SQL failure modes for a small model.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

import duckdb
from pydantic import BaseModel, Field

from safemine import config

GROUPABLE = {
    "classification": "a.CLASSIFICATION", "accident_type": "a.ACCIDENT_TYPE", "equipment": "a.MINING_EQUIP",
    "occupation": "a.OCCUPATION", "activity": "a.ACTIVITY", "injury_source": "a.INJURY_SOURCE",
    "nature_injury": "a.NATURE_INJURY", "year": "a.CAL_YR", "state": "m.STATE", "coal_metal": "a.COAL_METAL_IND",
    "mine_type": "m.CURRENT_MINE_TYPE", "subunit": "a.SUBUNIT", "degree_injury": "a.DEGREE_INJURY",
}


class StatsArgs(BaseModel):
    metric: Literal["count_by", "yearly_trend", "mine_profile", "fatal_events_by", "violations_by", "corpus_events"] = "count_by"
    group_by: Optional[Literal[tuple(GROUPABLE) + ("has_final_report",)]] = "classification"  # type: ignore[valid-type]
    has_final_report: Optional[bool] = None   # corpus_events only: True = events with a final report, False = without
    fatal_only: bool = True
    year_from: Optional[int] = Field(None, ge=2000, le=2030)
    year_to: Optional[int] = Field(None, ge=2000, le=2030)
    classification: Optional[str] = None
    accident_type: Optional[str] = None
    equipment: Optional[str] = None
    state: Optional[str] = Field(None, max_length=2, description="2-letter code, e.g. WV")
    coal_metal: Optional[Literal["C", "M"]] = None
    mine_id: Optional[str] = Field(None, pattern=r"^\d{7}$")
    top_n: int = Field(10, ge=1, le=25)


@lru_cache(maxsize=1)
def _con():
    return duckdb.connect(str(config.DUCKDB_PATH), read_only=True)


def _where(a: StatsArgs):
    w, p = ["1=1"], []
    if a.fatal_only:
        w.append("a.is_fatal")
    if a.year_from:
        w.append("CAST(a.CAL_YR AS INT) >= ?"); p.append(a.year_from)
    if a.year_to:
        w.append("CAST(a.CAL_YR AS INT) <= ?"); p.append(a.year_to)
    for field, col in (("classification", "a.CLASSIFICATION"), ("accident_type", "a.ACCIDENT_TYPE"), ("equipment", "a.MINING_EQUIP")):
        v = getattr(a, field)
        if v:
            w.append(f"{col} ILIKE ?"); p.append(f"%{v}%")
    if a.state:
        w.append("m.STATE = ?"); p.append(a.state.upper())
    if a.coal_metal:
        w.append("a.COAL_METAL_IND = ?"); p.append(a.coal_metal)
    if a.mine_id:
        w.append("a.MINE_ID = ?"); p.append(a.mine_id)
    return " AND ".join(w), p


YEAR_ALIASES = ("year", "calendar_year", "cal_yr", "yr", "years")


def _corpus_events(a: StatsArgs, ignored: list[str]) -> dict:
    """Number of fatality EVENTS in the corpus index (events_index.csv: 665 events, 655 with a PDF dossier, 10 without).
    Not accident rows (the Accidents table counts injured persons) and not the 655 of fatal_events (no dossier = missing)."""
    path = config.OUT / "events_index.csv"
    if not path.exists():
        return {"error": "events index missing: run `python -m safemine.ingest.build_events_index`"}
    w, p = ["1=1"], []
    if a.year_from:
        w.append("CAST(year AS INT) >= ?"); p.append(a.year_from)
    if a.year_to:
        w.append("CAST(year AS INT) <= ?"); p.append(a.year_to)
    if a.classification:
        w.append("classification ILIKE ?"); p.append(f"%{a.classification}%")
    if a.has_final_report is not None:
        w.append("lower(has_final_report) = ?"); p.append("true" if a.has_final_report else "false")
    src = f"read_csv_auto('{path.as_posix()}', all_varchar=true)"
    where = " AND ".join(w)
    con = _con()
    total = con.execute(f"SELECT count(*) FROM {src} WHERE {where}", p).fetchone()[0]
    col = {"classification": "classification", "year": "year", "has_final_report": "has_final_report"}.get(a.group_by or "", "classification")
    rows = con.execute(f"SELECT {col} AS key, count(*) AS n FROM {src} WHERE {where} GROUP BY 1 ORDER BY n DESC LIMIT {a.top_n}", p).fetchdf().to_dict("records")
    # one plain sentence the 8B writer can quote: it mis-assembled the numbers from the JSON on its own (said 10, not 5)
    span = (f" in {a.year_from}" if a.year_from and a.year_from == a.year_to else
            f" from {a.year_from} to {a.year_to}" if a.year_from and a.year_to else "")
    cls = f" classified as {a.classification}" if a.classification else ""
    fin = {True: " that have a final investigation report", False: " that do not have a final investigation report"}.get(a.has_final_report, "")
    out = {"summary": f"The corpus index lists {total} fatality events{span}{cls}{fin}.",
           "metric": "corpus_events", "args": a.model_dump(exclude_none=True), "total_matching_records": total, "rows": rows,
           "unit": "fatality EVENTS (one per fatality investigation) in the report corpus index",
           "source": "MSHA fatality-investigation corpus index (events_index.csv), snapshot 2026-10-30",
           "note": "Counts events, not accident rows or victims. The index lists 665 events: 655 with a PDF dossier and 10 without."}
    if ignored:
        out["ignored_args_not_applied"] = ignored
    return out


def accident_stats(**kwargs) -> dict:
    kwargs = dict(kwargs)
    # The 8B Planner writes {"year": 2019}; pydantic used to drop that key silently and the query ran over ALL years.
    for alias in YEAR_ALIASES:
        v = kwargs.pop(alias, None)
        if v is not None and not kwargs.get("year_from") and not kwargs.get("year_to"):
            try:
                kwargs["year_from"] = kwargs["year_to"] = int(v)
            except (TypeError, ValueError):
                pass
    ignored = sorted(k for k in kwargs if k not in StatsArgs.model_fields)
    a = StatsArgs(**{k: v for k, v in kwargs.items() if k in StatsArgs.model_fields})
    if a.metric == "corpus_events":
        return _corpus_events(a, ignored)
    con = _con()
    where, params = _where(a)
    base = "FROM accidents a LEFT JOIN mines m USING (MINE_ID)"
    if a.metric == "count_by":
        col = GROUPABLE[a.group_by or "classification"]
        sql = f"SELECT {col} AS key, count(*) AS n {base} WHERE {where} GROUP BY 1 ORDER BY n DESC LIMIT {a.top_n}"
    elif a.metric == "yearly_trend":
        sql = f"SELECT CAST(a.CAL_YR AS INT) AS year, count(*) AS n {base} WHERE {where} GROUP BY 1 ORDER BY 1"
    elif a.metric == "fatal_events_by":
        # MSHA fatality *events* (report level, 2008+), not accident rows
        col = {"classification": "classification", "state": "state", "year": "year", "mine_type": "mine_type"}.get(a.group_by or "", "classification")
        w, p = ["status = 'final_report'"], []
        if a.year_from:
            w.append("year >= ?"); p.append(a.year_from)
        if a.year_to:
            w.append("year <= ?"); p.append(a.year_to)
        if a.classification:
            w.append("classification ILIKE ?"); p.append(f"%{a.classification}%")
        sql, params = (f"SELECT {col} AS key, count(*) AS n FROM fatal_events WHERE {' AND '.join(w)} "
                       f"GROUP BY 1 ORDER BY n DESC LIMIT {a.top_n}"), p
    elif a.metric == "violations_by":
        # citations issued, grouped by standard (PART_SECTION) or year; filters: mine_id, years, state, coal_metal
        col = "CAST(v.CAL_YR AS INT)" if a.group_by == "year" else "v.PART_SECTION"
        w, p = ["1=1"], []
        if a.mine_id:
            w.append("v.MINE_ID = ?"); p.append(a.mine_id)
        if a.year_from:
            w.append("CAST(v.CAL_YR AS INT) >= ?"); p.append(a.year_from)
        if a.year_to:
            w.append("CAST(v.CAL_YR AS INT) <= ?"); p.append(a.year_to)
        if a.state:
            w.append("m.STATE = ?"); p.append(a.state.upper())
        if a.coal_metal:
            w.append("v.COAL_METAL_IND = ?"); p.append(a.coal_metal)
        sql, params = (f"""SELECT {col} AS key, count(*) AS n, sum(CASE WHEN v.SIG_SUB='Y' THEN 1 ELSE 0 END) AS sig_sub
                          FROM violations v LEFT JOIN mines m USING (MINE_ID) WHERE {' AND '.join(w)}
                          GROUP BY 1 ORDER BY {'1' if a.group_by == 'year' else 'n DESC'} LIMIT {a.top_n}"""), p
    else:  # mine_profile
        if not a.mine_id:
            return {"error": "mine_profile needs mine_id (7 digits, e.g. 0504841)"}
        mine = con.execute("SELECT * FROM mines WHERE MINE_ID = ?", [a.mine_id]).fetchdf().to_dict("records")
        acc = con.execute("""SELECT CAST(CAL_YR AS INT) yr, count(*) n, sum(CASE WHEN is_fatal THEN 1 ELSE 0 END) fatal
                             FROM accidents WHERE MINE_ID = ? GROUP BY 1 ORDER BY 1""", [a.mine_id]).fetchdf().to_dict("records")
        insp = con.execute("SELECT count(*) FROM inspections WHERE MINE_ID = ?", [a.mine_id]).fetchone()[0]
        return {"metric": "mine_profile", "mine": mine[:1], "accidents_by_year": acc, "n_inspections": insp,
                "source": "MSHA Open Government Data (Mines, Accidents, Inspections), snapshot 2026-10-30"}
    rows = con.execute(sql, params).fetchdf().to_dict("records")
    extra = {}
    if a.metric in ("count_by", "yearly_trend"):
        # the 8B model cannot be trusted to add up a table (it said 23 for 27): return the grand total, over ALL groups
        # (not just the top_n rows shown), computed by the database
        extra["total_matching_records"] = con.execute(f"SELECT count(*) {base} WHERE {where}", params).fetchone()[0]
    if ignored:   # visible to the model, the Critic and the trace: a filter that was NOT applied
        extra["ignored_args_not_applied"] = ignored
    return {"metric": a.metric, "args": a.model_dump(exclude_none=True), **extra, "rows": rows,
            "source": "MSHA Open Government Data, snapshot 2026-10-30",
            "note": ("Accident rows count injured persons, not events" + ("; a year missing from rows means 0" if a.metric == "yearly_trend" else "")) if a.metric != "fatal_events_by" else "Counts MSHA fatality events with a final report"}
