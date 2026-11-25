"""InvestigationAgent: incident-level reasoning. Grounds a question in the ONE incident it names, and writes the cited draft
(a plain answer, or a three-part investigation brief)."""
from __future__ import annotations

from safemine import config
from safemine.agent import heuristics
from safemine.agent import orchestrator as O
from safemine.agents.base import BaseAgent, Terminal, is_error


class InvestigationAgent(BaseAgent):
    name = "investigation"
    description = "Named-incident grounding, premise checks, cited drafting (answers and investigation briefs)"

    def ground_incident(self, ctx) -> None:
        """A question about one named incident (exact date, not a date range) may only be answered from that incident.
        Delegates the retrieval of that incident's own report to the retrieval agent when the search missed it."""
        plan, query, pack, log = ctx.plan, ctx.query, ctx.pack, ctx.log
        q_dates, ql = O.query_dates(query), query.lower()
        reports = [e for e in pack if e["kind"] == "report_chunk"]
        if not any(e.get("date") in q_dates for e in reports):
            extra = ctx.call(self.name, "retrieval", "fetch_named_event", q_dates, ql)
            if extra and not is_error(extra):
                log("named_event_fetched", event=extra[0]["event_id"], chunks=len(extra))
                pack.extend(O._evidence_from_tool("hybrid_search", extra, len(pack) + 1))
                reports = [e for e in pack if e["kind"] == "report_chunk"]
        if not reports:
            return
        keep = [e for e in reports if O.event_matches(e, ql, q_dates)]
        exact = [e for e in keep if e.get("date") in q_dates]
        if exact:   # an event on the exact date at the named mine beats same-mine events from other dates
            keep = exact
        log("event_grounding", retrieved=len(reports), matching=len(keep))
        if not keep:
            raise Terminal({"status": "abstained", "reason": "no_matching_event", "evidence": [],
                            "answer": "I could not find an incident in the corpus that matches the mine and date named in the "
                                      "question, so I will not answer from similar events. Please check the mine name and date."})
        pack[:] = [e for e in pack if e["kind"] != "report_chunk" or e in keep]
        ctx.named_incident = True
        # A2: only a preliminary notice / alert exists for this event and the question asks for its cause: no official
        # root cause is published, so say so (and what is public) instead of inventing one.
        if O.CAUSE_ASK.search(query) and keep[0]["event_id"] not in O._events_with_final_report():
            first = keep[0]
            raise Terminal({"status": "abstained", "reason": "report_not_published", "evidence": keep[:2],
                            "answer": "MSHA has not published a final investigation report for this event, so there is no official root "
                                      "cause to report. I will not guess one. What is public so far: "
                                      + O.re.sub(r"\s+", " ", first["text"])[:420] + f" [{first['id']}]"})
        ctx.premise = O.premise_notes(keep, query, q_dates)
        if ctx.premise:
            log("premise_check", notes=ctx.premise)
            if any(n.startswith("Date check") for n in ctx.premise):
                # the dates the QUESTION gave that are not the record's: the answer must never state them as the event's date
                have = {e.get("date") for e in keep}
                for m in O.FULL_DATE.findall(query):
                    try:
                        iso = O.datetime.strptime(O.re.sub(r"\s+", " ", m).replace(",", ""), "%B %d %Y").date().isoformat()
                    except ValueError:
                        continue
                    if iso not in have:
                        ctx.wrong_dates.append(m)

    def draft(self, ctx, problems: list[str]):
        """One writing round. Returns a Draft, or None when the model failed (the supervisor then falls back to the best earlier draft)."""
        query, plan, pack, llm, log = ctx.query, ctx.plan, ctx.pack, ctx.llm, ctx.log
        try:
            if llm.is_mock:
                return heuristics.draft(query, pack, plan)
            msgs = [{"role": "system", "content": O.DRAFT_SYS},
                    {"role": "user", "content": f"QUESTION: {query}\nOUTPUT FORMAT: {plan.output}\n\nEVIDENCE:\n{O._fmt_evidence(pack)}"
                     + (f"\n\nPREMISE CORRECTION (from MSHA's record, authoritative): {' '.join(ctx.premise)} Refer to the event by the date in the "
                        "EVIDENCE. Do not use the date from the question as the date of the event." if ctx.premise else "")
                     + (f"\n\nFIX THESE PROBLEMS FROM REVIEW: {problems}" if problems else "")}]
            return (O.write_brief(llm, query, pack, ctx.named_incident, problems, log) if plan.output == "investigation_brief"
                    else llm.chat_json(msgs, O.Draft, max_tokens=900))
        except Exception as e:  # noqa: BLE001  bad JSON, budget, API/network/rate-limit errors -> fallback
            log("draft_error", error=str(e)[:200])
            if getattr(e, "status_code", None) in (401, 403):
                raise Terminal({"status": "error", "answer": f"The LLM endpoint rejected the API key ({config.llm_label()}). "
                                "Check the key in .env.", "evidence": pack})
            return None
