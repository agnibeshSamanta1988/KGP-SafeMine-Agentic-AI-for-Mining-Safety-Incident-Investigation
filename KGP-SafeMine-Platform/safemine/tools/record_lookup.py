"""record_lookup: fetch ONE record (or a short list) by its identifier from the MSHA tables in DuckDB.

  kind="accident"         DOCUMENT_NO -> the accident row (date, classification, degree of injury, occupation, narrative)
  kind="inspection"       EVENT_NO    -> the inspection (dates, activity, hours) + how many violations it produced
  kind="violation"        VIOLATION_NO -> the citation (standard, date, significant-and-substantial flag, proposed penalty)
  kind="mine"             MINE_ID     -> mine profile + counts of accidents / fatal accidents / inspections / violations
  kind="last_inspection"  MINE_ID (+ before date) -> the most recent inspection before that date
  kind="reports_citing"   section     -> MSHA fatality reports whose enforcement actions cite that 30 CFR section

Like accident_stats the LLM never writes SQL: it chooses a `kind` and passes identifiers that are validated by pydantic
and bound as parameters. The orchestrator additionally drops any identifier that is not written in the user's question
(an 8B model invents plausible ids). A missing id returns {"found": false}, never a guess.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

from safemine.redact import redact_initial_names
from safemine.tools.accident_stats import _con

SOURCE = "MSHA Open Government Data, snapshot 2026-10-30"


class RecordArgs(BaseModel):
    kind: Literal["accident", "inspection", "violation", "mine", "last_inspection", "reports_citing"]
    document_no: Optional[str] = Field(None, pattern=r"^\d{9,14}$")
    event_no: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9]{6,8}$")
    violation_no: Optional[str] = Field(None, pattern=r"^\d{6,9}$")
    mine_id: Optional[str] = Field(None, pattern=r"^\d{7}$")
    section: Optional[str] = Field(None, pattern=r"^\d{1,3}\.\d+[a-z]?(\([a-z0-9]+\))*$")
    before: Optional[date] = None
    limit: int = Field(5, ge=1, le=15)


def _rows(sql: str, params: list) -> list[dict]:
    return _con().execute(sql, params).fetchdf().to_dict("records")


def _clean(rec: dict) -> dict:
    return {k: (None if v != v else v) for k, v in rec.items()}   # NaN -> None


def record_lookup(**kwargs) -> dict:
    a = RecordArgs(**kwargs)
    base = {"kind": a.kind, "source": SOURCE}

    if a.kind == "accident":
        if not a.document_no:
            return {**base, "error": "kind=accident needs document_no (the 12-digit DOCUMENT_NO)"}
        rows = _rows("""SELECT DOCUMENT_NO, MINE_ID, OPERATOR_NAME, ACCIDENT_DT, CAL_YR, ACCIDENT_TIME, DEGREE_INJURY, CLASSIFICATION,
                               ACCIDENT_TYPE, MINING_EQUIP, OCCUPATION, ACTIVITY, INJURY_SOURCE, NATURE_INJURY, INJ_BODY_PART, DAYS_LOST,
                               NO_INJURIES, NARRATIVE FROM accidents WHERE DOCUMENT_NO = ? LIMIT 3""", [a.document_no])
        for r in rows:
            r["NARRATIVE"] = redact_initial_names(str(r.get("NARRATIVE") or ""))[:600]
        return {**base, "found": bool(rows), "records": [_clean(r) for r in rows],
                "note": "One row per injured person; a fatal accident has DEGREE_INJURY = FATALITY."}

    if a.kind == "inspection":
        if not a.event_no:
            return {**base, "error": "kind=inspection needs event_no (EVENT_NO)"}
        rows = _rows("""SELECT EVENT_NO, MINE_ID, INSPECTION_BEGIN_DT, INSPECTION_END_DT, ACTIVITY, NBR_INSPECTOR, TOTAL_INSP_HOURS
                        FROM inspections WHERE EVENT_NO = ? LIMIT ?""", [a.event_no, a.limit])
        viol = _rows("""SELECT count(*) AS n_violations, sum(CASE WHEN SIG_SUB = 'Y' THEN 1 ELSE 0 END) AS n_significant_substantial
                        FROM violations WHERE EVENT_NO = ?""", [a.event_no])
        return {**base, "found": bool(rows), "records": [_clean(r) for r in rows], "violations_from_this_inspection": _clean(viol[0])}

    if a.kind == "violation":
        if not a.violation_no:
            return {**base, "error": "kind=violation needs violation_no (VIOLATION_NO)"}
        rows = _rows("""SELECT VIOLATION_NO, MINE_ID, EVENT_NO, VIOLATION_ISSUE_DT, PART_SECTION, SIG_SUB, LIKELIHOOD, INJ_ILLNESS,
                               NEGLIGENCE, PROPOSED_PENALTY, CONTESTED_IND FROM violations WHERE VIOLATION_NO = ? LIMIT ?""",
                     [a.violation_no, a.limit])
        return {**base, "found": bool(rows), "records": [_clean(r) for r in rows]}

    if a.kind == "mine":
        if not a.mine_id:
            return {**base, "error": "kind=mine needs mine_id (7 digits, e.g. 0504841)"}
        mine = _rows("""SELECT MINE_ID, CURRENT_MINE_NAME, CURRENT_MINE_TYPE, CURRENT_MINE_STATUS, COAL_METAL_IND, STATE, FIPS_CNTY_NM,
                               CURRENT_OPERATOR_NAME, CURRENT_CONTROLLER_NAME, NO_EMPLOYEES FROM mines WHERE MINE_ID = ?""", [a.mine_id])
        if not mine:
            return {**base, "found": False}
        c = _con()
        acc = c.execute("SELECT count(*), sum(CASE WHEN is_fatal THEN 1 ELSE 0 END) FROM accidents WHERE MINE_ID = ?", [a.mine_id]).fetchone()
        insp = c.execute("""SELECT count(*), max(try_strptime(INSPECTION_BEGIN_DT, '%m/%d/%Y')) FROM inspections WHERE MINE_ID = ?""",
                         [a.mine_id]).fetchone()
        viol = c.execute("SELECT count(*) FROM violations WHERE MINE_ID = ?", [a.mine_id]).fetchone()[0]
        return {**base, "found": True, "mine": _clean(mine[0]),
                "counts": {"accident_rows": acc[0], "fatal_accident_rows": int(acc[1] or 0), "inspections": insp[0],
                           "last_inspection_begin": str(insp[1].date()) if insp[1] is not None else None, "violations": viol}}

    if a.kind == "last_inspection":
        if not a.mine_id:
            return {**base, "error": "kind=last_inspection needs mine_id"}
        cutoff = a.before or date.today()
        rows = _rows("""SELECT EVENT_NO, MINE_ID, INSPECTION_BEGIN_DT, INSPECTION_END_DT, ACTIVITY, TOTAL_INSP_HOURS
                        FROM inspections WHERE MINE_ID = ? AND try_strptime(INSPECTION_BEGIN_DT, '%m/%d/%Y') < ?
                        ORDER BY try_strptime(INSPECTION_BEGIN_DT, '%m/%d/%Y') DESC LIMIT 1""", [a.mine_id, cutoff])
        return {**base, "found": bool(rows), "before": str(cutoff), "records": [_clean(r) for r in rows]}

    # reports_citing
    if not a.section:
        return {**base, "error": "kind=reports_citing needs section (e.g. 75.202)"}
    sec = a.section.split("(")[0]
    where = "list_contains(string_split(cfr_cited, ','), ?)"
    total = _con().execute(f"SELECT count(*) FROM fatal_events WHERE {where}", [sec]).fetchone()[0]
    rows = _rows(f"""SELECT event_id, event_date, mine_name, classification, state FROM fatal_events WHERE {where}
                     ORDER BY event_date DESC LIMIT ?""", [sec, a.limit])
    return {**base, "found": total > 0, "section": sec, "total_reports_citing": total, "most_recent": [_clean(r) for r in rows],
            "note": "Counts MSHA fatality reports (final reports) whose enforcement actions cite this section."}
