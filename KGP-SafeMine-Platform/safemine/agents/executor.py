"""Tool execution with the safety rules the 8B Planner needs, shared by the retrieval and regulatory agents.

This is the legacy `execute()` closure moved out unchanged in behaviour: ungrounded ids and CFR sections are dropped, empty or
duplicate steps are skipped, filters the user never stated are removed, bad arguments get one repair attempt, and a failing tool
becomes a trace event instead of an exception. The per-request counters live on the TaskContext.
"""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from safemine import config
from safemine.agent import heuristics
from safemine.agent import orchestrator as O


def run_step(ctx, st, allowed: set[str], from_critic: bool = False, trusted: bool = False) -> str:
    """Execute one planned tool call. Returns "stop" when the step limit is reached, otherwise "ok" (also for skipped/failed steps)."""
    query, pack, log = ctx.query, ctx.pack, ctx.log
    if st.tool not in allowed:
        log("step_misrouted", tool=st.tool)
        return "ok"
    if ctx.steps_used >= config.MAX_STEPS:
        log("step_limit")
        return "stop"
    # The 8B Planner copies the section number from its own few-shot example (30 CFR 75.1403) or invents one.
    if st.tool == "record_lookup":   # an id may only be looked up if the user wrote it (the 8B model invents ids)
        for key in ("document_no", "event_no", "violation_no", "mine_id", "section"):
            if st.args.get(key) and str(st.args[key]).lower() not in query.lower():
                log("dropped_ungrounded_id", key=key, value=str(st.args[key])[:20])
                st.args.pop(key)
        if not any(st.args.get(k) for k in ("document_no", "event_no", "violation_no", "mine_id", "section")):
            return "ok"
    # A section may only be looked up if the user wrote it or it appears in evidence already retrieved.
    if st.tool == "cfr_lookup" and not trusted and (st.args.get("mode") or "exact") == "exact":
        m = re.search(r"\d{1,3}\.\d+[a-z]?", str(st.args.get("section") or ""))
        # grounded = the user wrote it, or the INDEXED citation list of a retrieved report (cfr_ids, extracted when the index was built), or
        # a regulation already fetched. Free text of a document does not count: an attacker can write any section number into a document.
        if not m or not (m.group(0) in query or any(m.group(0) in (e.get("cfr_ids") or []) or (e["kind"] == "regulation" and m.group(0) in e["text"])
                                                     for e in pack)):
            log("dropped_ungrounded_section", section=st.args.get("section"))
            return "ok"
    # A Critic extra step with no arguments would be "repaired" into an unfiltered search of the raw question (noise).
    if from_critic and not st.args:
        log("skipped_empty_critic_step", tool=st.tool)
        return "ok"
    call_key = st.tool + json.dumps(st.args, sort_keys=True, default=str)
    if call_key in ctx.seen_calls:  # identical call already ran: would only repeat the same evidence
        log("skipped_duplicate_step", tool=st.tool)
        return "ok"
    ctx.seen_calls.add(call_key)
    ctx.steps_used += 1
    plan = ctx.plan
    if st.tool == "hybrid_search" and (plan.intent in O.PATTERN_INTENTS or (plan.output == "investigation_brief" and not O.FULL_DATE.search(query))):
        st.args.setdefault("diverse", True)   # breadth over depth: one chunk per incident, up to 12
    if st.tool == "hybrid_search":
        try:
            st.args["k"] = max(int(st.args.get("k") or 8), 4)   # the 8B Planner sometimes asks for k=1
        except (TypeError, ValueError):
            st.args["k"] = 8
        if O.FULL_DATE.search(query) and not st.args.get("event_id"):
            # The Planner shortens the question and loses the mine name and date that identify the event.
            st.args["query"] = query[:300]
            if st.args.get("sections"):   # events with no final report only have these sections
                st.args["sections"] = list(dict.fromkeys([*st.args["sections"], "PRELIMINARY", "ALERT_SUMMARY", "SUPPLEMENT"]))
    st.args, dropped = O.ground_filters(st.tool, st.args, (query + " " + ctx.history_text).strip())   # the user's own words, this turn or earlier
    if dropped:
        log("dropped_ungrounded_filters", tool=st.tool, keys=dropped)
    tools = O.TOOLS
    if (st.tool == "hybrid_search" and "ENFORCEMENT" in (st.args.get("sections") or []) and O.CITED_ASK.search(query)
            and O.FULL_DATE.search(query) and not st.args.get("event_id")):
        # "which standard was cited after the <date> fatality at <mine>": the answer is in that event's ENFORCEMENT chunks. Searching them together with
        # the preliminary / alert sections lets a notification-order chunk (30 CFR 50.12) outrank the real citation, so look in ENFORCEMENT first and
        # widen only when that finds nothing for the named date.
        narrow = {**st.args, "sections": ["ENFORCEMENT"]}
        try:
            probe = tools["hybrid_search"](**narrow)
            if any(c.get("date") in O.query_dates(query) for c in probe):
                st.args = narrow
        except Exception:  # noqa: BLE001  the normal call below reports any real tool problem
            pass
    try:
        result = tools[st.tool](**st.args)
    except (ValidationError, ValueError, TypeError) as e:
        # small models send bad args: drop unknown/invalid keys once and retry
        fixed = heuristics.repair_args(st.tool, st.args, query)
        log("tool_arg_error", tool=st.tool, error=str(e)[:200], repaired=fixed)
        try:
            result = tools[st.tool](**fixed)
        except Exception as e2:  # noqa: BLE001
            log("tool_error", tool=st.tool, error=str(e2)[:200])
            return "ok"
    except Exception as e:  # noqa: BLE001
        log("tool_error", tool=st.tool, error=str(e)[:200])
        return "ok"
    new = O._evidence_from_tool(st.tool, result, len(pack) + 1)
    pack.extend(new)
    log("tool", tool=st.tool, args=st.args, n_evidence=len(new), evidence=[e.get("chunk_id") or e["label"] for e in new],
        **({"data": O._plain(result)} if st.tool == "accident_stats" and isinstance(result, dict) else {}))   # raw rows for the UI charts
    return "ok"
