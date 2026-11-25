"""PlannerAgent: turns the question into an intent and at most four tool steps, then applies the deterministic corrections."""
from __future__ import annotations

import json

from safemine.agent import heuristics
from safemine.agent import orchestrator as O
from safemine.agents.base import BaseAgent


class PlannerAgent(BaseAgent):
    name = "planner"
    description = "Task decomposition: intent, tool steps, output format"

    def plan(self, ctx) -> None:
        query, log, llm = ctx.query, ctx.log, ctx.llm
        history = ctx.store.history(ctx.session_id) if ctx.store else []
        ctx.history_text = " ".join(h["query"] for h in history)
        try:
            plan = heuristics.plan(query) if llm.is_mock else llm.chat_json(
                [{"role": "system", "content": O.PLANNER_SYS}, *O.PLANNER_FEWSHOT,
                 {"role": "user", "content": (f"Conversation so far: {json.dumps(history)}\n\n" if history else "") + query}], O.Plan)
        except Exception as e:  # noqa: BLE001  bad JSON, budget, API/network/rate-limit errors -> fallback
            log("planner_fallback", error=str(e)[:200])
            plan = heuristics.plan(query)
        if plan.output == "investigation_brief" and not O.BRIEF_ASK.search(query):
            plan.output = "answer"   # the 8B Planner picks the brief format for plain questions; the brief's headings invite uncited filler
        if not O.CORPUS_COUNT_ASK.search(query):   # "corpus_events" counts report EVENTS; accident records/rows use count_by
            for st in plan.steps:
                if st.tool == "accident_stats" and st.args.get("metric") == "corpus_events":
                    st.args["metric"] = "count_by"
                    st.args.pop("has_final_report", None)
                    st.args.setdefault("fatal_only", True)
        if O.record_steps(query):   # identifiers in the question: look the record up
            plan.steps, plan.intent = O.record_steps(query)[:4], "statistics"
        elif O.CORPUS_COUNT_ASK.search(query):   # the right tool and metric are not a judgement call for an 8B Planner
            plan.steps, plan.intent = [O.corpus_count_step(query)], "statistics"
        elif (O.FULL_DATE.search(query) and not O.DATE_BOUND.search(query) and O.INCIDENT_WORDS.search(query)
              and not any(s.tool == "hybrid_search" for s in plan.steps)):
            # a question about one named incident needs that incident's own report (the Planner sometimes issues only an
            # invented cfr_lookup, which left the agent with no evidence at all)
            args = {"query": query[:300], "k": 6}
            if O.CITED_ASK.search(query):
                args["sections"] = ["ENFORCEMENT"]
            elif O.CAUSE_ASK.search(query):   # causes and corrective actions live in the ROOT_CAUSE pair chunks
                args["sections"] = ["ROOT_CAUSE", "SUMMARY"]
            plan.steps = [O.ToolCall(tool="hybrid_search", args=args, purpose="find the named incident"), *plan.steps][:4]
            plan.intent = "incident_investigation"
        if O.CITED_ASK.search(query):
            # "which standard did MSHA cite": the citations live in the ENFORCEMENT chunks. An 8B Planner sometimes restricts the search to the
            # root-cause / summary sections, so the answer cannot be found and the writer reaches for standards it remembers (which the verifier
            # rightly refuses). Guarantee the section instead of relying on the model's choice.
            for st in plan.steps:
                secs = st.args.get("sections") if st.tool == "hybrid_search" else None
                if secs and "ENFORCEMENT" not in secs:
                    st.args["sections"] = [*secs, "ENFORCEMENT"]
        log("plan", intent=plan.intent, output=plan.output, steps=[s.model_dump() for s in plan.steps])
        ctx.plan = plan
        if plan.output == "investigation_brief":
            ctx.usage.budget = O.config.TOKEN_BUDGET * 2   # three writer calls instead of one
