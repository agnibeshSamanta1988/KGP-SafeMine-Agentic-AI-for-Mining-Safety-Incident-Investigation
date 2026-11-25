"""SafetyAgent: decides whether a question may be answered at all (spec rules R1-R7, LLM policy classifier, snapshot limit)."""
from __future__ import annotations

from safemine.agent import orchestrator as O
from safemine.agent.guard import input_guard
from safemine.agent.policy import classify_policy, decision_to_guard
from safemine.agents.base import BaseAgent, Terminal


class SafetyAgent(BaseAgent):
    name = "safety"
    description = "Input policy: refusals, injection stripping, out-of-snapshot dates"

    def screen(self, ctx) -> None:
        """Clean the question or end the request with a refusal / abstention."""
        query, log, llm = ctx.orig_query, ctx.log, ctx.llm
        g = input_guard(query)
        pol_done = False
        if not g["ok"] and g.get("soft"):   # regex scope miss: let the LLM classifier decide (OK / specific refusal / really OOS)
            pol = classify_policy(llm, g["query"])
            pol_done = pol is not None
            if pol is not None:
                log("policy_classifier", category=pol.category, reason=pol.reason[:80], after="regex_scope_miss")
                if pol.category == "OK":
                    g = {"ok": True, "query": g["query"], "injected": g["injected"], "removed": g["removed"]}
                elif decision_to_guard(pol, soft=True):
                    g = decision_to_guard(pol, soft=True)
        if not g["ok"]:
            log("refuse" if g["status"] == "refused" else "abstain", rule=g["rule"])
            raise Terminal({"status": g["status"], "rule": g["rule"], "reason": g["rule"], "answer": g["message"], "evidence": []})
        ctx.query = g["query"]   # R7: instructions embedded in the question have been removed; the rest is the real question
        ctx.guard = g
        if g["injected"]:
            log("injection_stripped", removed=[s[:80] for s in g["removed"]])
        # second layer: the LLM classifier catches paraphrases the regex rules miss (it can only add a refusal)
        pol = None if pol_done else classify_policy(llm, ctx.query)
        if pol is not None:
            log("policy_classifier", category=pol.category, reason=pol.reason[:80])
            blocked = decision_to_guard(pol)
            if blocked:
                raise Terminal({"status": blocked["status"], "rule": blocked["rule"], "reason": blocked["rule"],
                                "answer": blocked["message"], "evidence": []})
        future = sorted(d for d in O.query_dates(ctx.query) if d > O.SNAPSHOT_END.isoformat())
        if future:   # the corpus ends at the snapshot: no event after it can exist, so do not search and do not guess
            log("abstain", reason="out_of_snapshot", date=future[0])
            raise Terminal({"status": "abstained", "reason": "out_of_snapshot", "evidence": [],
                            "answer": f"I cannot find any record for {future[0]}: the MSHA data behind this tool ends at its "
                                      f"{O.SNAPSHOT_END:%d %B %Y} snapshot, so no event after that date is in the corpus. I will not guess a cause."})
