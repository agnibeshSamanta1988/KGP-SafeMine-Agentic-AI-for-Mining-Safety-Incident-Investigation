"""Deterministic fallbacks for each LLM role.

Used (a) by MockLLM so the pipeline runs before the Track B key arrives, (b) as the fallback when the real
model returns unusable JSON twice, and (c) as a no-LLM extractive baseline for the evaluation report.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

CLASSES = {
    "powered haulage": "Powered Haulage", "haul truck": "Powered Haulage", "conveyor": "Powered Haulage",
    "machinery": "Machinery", "roof fall": "Fall of Roof or Back", "fall of roof": "Fall of Roof or Back",
    "rib": "Fall of Face", "highwall": "Fall of Face", "electrical": "Electrical", "electrocut": "Electrical",
    "slip or fall": "Slip or Fall", "fell from": "Slip or Fall", "falling material": "Falling",
    "explosion": "Explosion", "drowning": "Drowning", "fire": "Fire", "hoisting": "Hoisting",
}
STATES = {"WV": "West Virginia", "KY": "Kentucky", "PA": "Pennsylvania", "TX": "Texas", "NV": "Nevada", "IL": "Illinois",
          "AL": "Alabama", "VA": "Virginia", "OH": "Ohio", "WY": "Wyoming", "CA": "California", "AZ": "Arizona"}


def _years(q: str) -> dict:
    out = {}
    m = re.search(r"(?:since|after|from)\s+((?:19|20)\d\d)", q, re.I)
    if m:
        out["year_from"] = int(m.group(1))
    m = re.search(r"(?:before|until|through|to)\s+((?:19|20)\d\d)", q, re.I)
    if m:
        out["year_to"] = int(m.group(1))
    m = re.search(r"\bin\s+((?:19|20)\d\d)\b", q)
    if m and not out:
        out = {"year_from": int(m.group(1)), "year_to": int(m.group(1))}
    return out


def plan(q: str):
    from safemine.agent.orchestrator import Plan, ToolCall
    ql = q.lower()
    yrs = _years(q)
    cls = next((v for k, v in CLASSES.items() if k in ql), None)
    mt = "Underground" if "underground" in ql else "Surface" if "surface" in ql else None
    steps = []
    cfr = re.findall(r"\b(\d{2,3}\.\d{2,6})(?:\([a-z0-9]+\))*", q)
    if re.search(r"how many|count|number of|trend|most common|statistic|per year|each year|rate", ql):
        intent = "statistics"
        metric = "yearly_trend" if re.search(r"trend|per year|each year|over time", ql) else "count_by"
        gb = next((g for g in ("equipment", "occupation", "activity", "accident_type", "state", "classification")
                   if g.replace("_", " ") in ql), "classification")
        st = next((k for k, v in STATES.items() if v.lower() in ql), None)
        args = {"metric": metric, "group_by": gb, "fatal_only": "fatal" in ql or "death" in ql or "fatalit" in ql, **yrs}
        args = {k: v for k, v in args.items() if v is not None}
        if cls:
            args["classification"] = cls
        if st:
            args["state"] = st
        steps.append(ToolCall(tool="accident_stats", args=args, purpose="statistics"))
    for sec in cfr[:2]:
        steps.append(ToolCall(tool="cfr_lookup", args={"mode": "exact", "section": sec}, purpose="standard text"))
    if not steps or re.search(r"root cause|why|similar|lesson|prevent|recommend|corrective|investigat|what happened|describe", ql):
        sections = ["ROOT_CAUSE", "SUMMARY"] if re.search(r"root cause|why|corrective", ql) else \
                   ["BEST_PRACTICES", "ROOT_CAUSE"] if re.search(r"prevent|recommend|best practice", ql) else None
        args = {"query": q[:300], "k": 8, **yrs}
        if cls:
            args["classification"] = cls
        if mt:
            args["mine_type"] = mt
        if sections:
            args["sections"] = sections
        steps.append(ToolCall(tool="hybrid_search", args=args, purpose="report evidence"))
    if re.search(r"(standard|regulation|cfr|require)", ql) and not cfr:
        steps.append(ToolCall(tool="cfr_lookup", args={"mode": "search", "query": q[:200]}, purpose="find standard"))
    intent = ("regulatory_lookup" if cfr and len(steps) == len(cfr) else
              "statistics" if steps[0].tool == "accident_stats" else
              "root_cause_patterns" if "root cause" in ql else
              "prevention_recommendations" if re.search(r"prevent|recommend", ql) else
              "similar_incidents" if "similar" in ql else "incident_investigation")
    return Plan(intent=intent, steps=steps[:4], output="investigation_brief" if "brief" in ql or "report" in ql else "answer")


def repair_args(tool: str, args: dict, q: str) -> dict:
    from safemine.tools.accident_stats import StatsArgs
    from safemine.tools.cfr_lookup import CfrArgs
    from safemine.tools.hybrid_search import SearchArgs
    from safemine.tools.record_lookup import RecordArgs
    model = {"hybrid_search": SearchArgs, "accident_stats": StatsArgs, "cfr_lookup": CfrArgs, "record_lookup": RecordArgs}[tool]
    fields = set(model.model_fields)
    fixed = {k: v for k, v in args.items() if k in fields and v not in (None, "", [])}
    for k in list(fixed):
        try:
            model(**{**({"query": q[:300]} if tool == "hybrid_search" else {}), k: fixed[k]})
        except Exception:  # noqa: BLE001
            fixed.pop(k)
    if tool == "hybrid_search":
        fixed.setdefault("query", q[:300])
    return fixed


def _sentences(t: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\[])", t) if len(s.strip()) > 25]


def draft(q: str, pack: list[dict], plan_obj):
    """Extractive draft: best sentences of the top evidence, each cited. (No generation, so no hallucination.)"""
    from safemine.agent.orchestrator import Draft
    qw = set(re.findall(r"[a-z]{4,}", q.lower()))
    lines = []
    for e in pack[:6]:
        if e["kind"] == "statistics":
            lines.append(f"- Statistics ({e['label']}): {e['text'][:400]} [{e['id']}]")
            continue
        sents = _sentences(e["text"]) or [e["text"][:300]]
        best = max(sents, key=lambda s: len(qw & set(re.findall(r"[a-z]{4,}", s.lower()))))
        lines.append(f"- {e['label'].split(' | ')[0]} ({e['label'].split(' | ')[1] if ' | ' in e['label'] else ''}): {best} [{e['id']}]")
    head = "Evidence-grounded summary (extractive baseline, no LLM):"
    return Draft(answer=head + "\n" + "\n".join(lines), insufficient_evidence=not lines)


class _Crit(BaseModel):
    decision: str


def critique(ver: dict):
    from safemine.agent.orchestrator import Critique
    if ver["n_factual"] == 0:
        return Critique(decision="abstain", problems=["no factual, cited content"])
    if ver["support_ratio"] >= 0.6:
        return Critique(decision="accept")
    return Critique(decision="revise", problems=[f"{len(ver['unsupported'])} unsupported sentence(s)"])
