"""cfr_lookup: versioned 30 CFR text.

mode=exact  section (+ optional as_of date) -> text of that section as in force on that date:
            exact eCFR snapshot (Parts 50/56/57/75/77, 2017+) > annual edition (July 1, 2008-2025) > current.
            Returns version_status = "exact" | "annual_edition" | "current" | "version_unverified".
mode=search keyword search over section titles + text of the current edition.
"""
from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from typing import Literal, Optional

from pydantic import BaseModel, Field

from safemine.tools.accident_stats import _con


class CfrArgs(BaseModel):
    mode: Literal["exact", "search"] = "exact"
    section: Optional[str] = Field(None, description="e.g. 56.14211 or '30 CFR 56.14211(c)'")
    as_of: Optional[date] = None
    query: Optional[str] = Field(None, max_length=300)
    part: Optional[str] = Field(None, pattern=r"^\d{1,3}$")
    k: int = Field(5, ge=1, le=10)


def norm_section(s: str) -> tuple[str, Optional[str]]:
    m = re.search(r"(\d{1,3}\.\d+[a-z]?(?:-\d+)?)(\([a-z0-9]+\)(?:\([a-z0-9]+\))*)?", s)
    if not m:
        raise ValueError(f"not a CFR section: {s!r}")
    return m.group(1), m.group(2)


def cfr_lookup(**kwargs) -> dict:
    a = CfrArgs(**kwargs)
    con = _con()
    if a.mode == "search":
        if not a.query:
            return {"error": "search mode needs query"}
        words = [w for w in re.findall(r"[a-z]{3,}", a.query.lower())][:8]
        if not words:
            return {"error": "query has no searchable words"}
        score = " + ".join(["(CASE WHEN lower(subject) LIKE ? THEN 3 ELSE 0 END + CASE WHEN lower(text) LIKE ? THEN 1 ELSE 0 END)"] * len(words))
        params = [p for w in words for p in (f"%{w}%", f"%{w}%")]
        where = "edition = 'current'" + (" AND part = ?" if a.part else "")
        if a.part:
            params.append(a.part)
        sql = """SELECT section, subject, substr(text, 1, 600) AS text, ({score}) AS score
                 FROM cfr_sections WHERE {where} ORDER BY score DESC, section LIMIT {k}"""
        rows = con.execute(sql.format(score=score, where=where, k=a.k), params).fetchdf()
        hits = rows[rows.score > 0]
        if hits.empty and a.part:
            # the 8B Planner passes invalid part numbers ("30"): an empty result with a part filter is retried without it
            rows = con.execute(sql.format(score=score, where="edition = 'current'", k=a.k), params[:len(words) * 2]).fetchdf()
            hits = rows[rows.score > 0]
        return {"mode": "search", "results": hits.drop(columns="score").to_dict("records"),
                "edition": "current eCFR (2026-10-30)"}

    if not a.section:
        return {"error": "exact mode needs section"}
    sec, para = norm_section(a.section)
    as_of = a.as_of or date.today()
    row, status = None, None
    snap = con.execute("""SELECT * FROM cfr_sections WHERE section = ? AND edition = 'snapshot' AND edition_date <= ?
                          ORDER BY edition_date DESC LIMIT 1""", [sec, as_of]).fetchdf()
    if len(snap) and as_of >= date(2017, 1, 23):
        row, status = snap.iloc[0], "exact"
    if row is None:
        ann = con.execute("""SELECT * FROM cfr_sections WHERE section = ? AND edition = 'annual' AND edition_date <= ?
                             ORDER BY edition_date DESC LIMIT 1""", [sec, as_of]).fetchdf()
        if len(ann) and (as_of - ann.iloc[0].edition_date.date()).days < 400:
            row, status = ann.iloc[0], "annual_edition"
    if row is None:
        cur = con.execute("SELECT * FROM cfr_sections WHERE section = ? AND edition = 'current'", [sec]).fetchdf()
        if len(cur):
            row = cur.iloc[0]
            status = "current" if a.as_of is None or as_of >= date(2026, 1, 1) else "version_unverified"
    if row is None:
        return {"error": f"30 CFR {sec} not found in the law store"}
    # rule-status hint: final rules touching this part published after the version date
    later = con.execute("""SELECT document_number, title, publication_date, effective_on FROM fr_rules
                           WHERE kind='final' AND list_contains(string_split(cfr_parts, ','), ?) AND publication_date > ?
                           ORDER BY publication_date LIMIT 5""", [sec.split(".")[0], row.edition_date]).fetchdf()
    return {"mode": "exact", "citation": f"30 CFR {sec}{para or ''}", "section": sec, "paragraph": para,
            "subject": row.subject, "text": row.text[:4000], "edition": row.edition,
            "edition_date": str(row.edition_date.date()), "as_of": str(as_of), "version_status": status,
            "later_final_rules_on_part": later.astype(str).to_dict("records")}
