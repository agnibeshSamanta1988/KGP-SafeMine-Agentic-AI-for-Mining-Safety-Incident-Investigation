"""ReportAgent: assembles the final response and enforces the last gates (output policy, privacy filter, human-review flag).

It never writes new facts. It only orders, annotates and filters what the validator has already verified: premise notes first, caveats
and removal notices, the coverage note for pattern answers, the output filter (names, policy), and the claim map that makes the
answer traceable to its sources.
"""
from __future__ import annotations

import re

from safemine.agent import orchestrator as O
from safemine.agent.guard import POLICY_MESSAGES, answer_policy_violation, output_filter
from safemine.agents.base import BaseAgent


class ReportAgent(BaseAgent):
    name = "report"
    description = "Final assembly: notes, policy gate, privacy filter, claim map, human-review flag"

    def no_evidence(self, ctx) -> dict:
        return {"status": "abstained", "reason": "no_evidence", "evidence": [],
                "answer": "I could not find evidence in the MSHA corpus, accident data or 30 CFR "
                          "that answers this question. Try naming the accident type, equipment, mine type or year range."}

    def not_accepted(self, ctx) -> dict:
        """The draft was not accepted: abstain, without echoing the rejected draft or the Critic's remarks (they can contain the very
        recommendation or unsupported claim that was just refused). Only the writer's own short "what is missing" items are shown."""
        draft, problems = ctx.draft, ctx.problems
        reason = (draft.missing if draft and draft.missing else problems[:3]) or ["evidence insufficient or conflicting"]
        shown = [m for m in (draft.missing if draft and draft.insufficient_evidence else []) if isinstance(m, str) and len(m) <= 120]
        return {"status": "abstained", "reason": reason,
                "answer": "I don't have enough verified evidence to answer this reliably."
                          + (" What is missing: " + "; ".join(shown) + "." if shown else "")
                          + " The closest evidence found is listed below.",
                "evidence": ctx.pack, "verification": ctx.ver}

    def compose(self, ctx) -> dict:
        draft, pack, plan, log = ctx.draft, ctx.pack, ctx.plan, ctx.log
        if ctx.removed:
            if len(re.sub(r"[\s\W_]+", "", re.sub(r"\[E\d+\]", "", draft.answer))) < 40:   # nothing verifiable was left
                return {"status": "abstained", "reason": "unverifiable", "evidence": pack,
                        "answer": "I could not verify the regulation numbers, quotations or figures in my draft against the evidence, "
                                  "so I am not giving an answer. The closest evidence found is listed below."}
            draft.answer += (f"\n\n*{ctx.removed} statement(s) were removed because a regulation number, quotation, figure or date in them "
                             "could not be verified in the cited evidence.*")
        try:   # an answer accepted at >= 60% support can still hold a sentence the verifier could not tie to its citations: say so in the answer
            n_open = ctx.registry["validator"].claim_map(ctx, draft.answer)["summary"]["unsupported"]
        except Exception:  # noqa: BLE001
            n_open = 0
        if n_open:
            log("unsupported_released", n=n_open)
            draft.answer += (f"\n\n*{n_open} statement(s) in this answer could not be tied to the cited evidence. They are marked in "
                             "the verification detail: treat them as unverified.*")
        if ctx.caveat:
            draft.answer += ("\n\n*Note: the automated review considered this answer possibly incomplete. Every claim above was "
                             "checked against the cited evidence.*")
        violated = answer_policy_violation(draft.answer)   # a fault / compliance verdict the input rules did not catch
        if violated:
            log("answer_policy_violation", rule=violated)
            return {"status": "refused", "rule": violated, "answer": POLICY_MESSAGES[violated], "evidence": []}
        if ctx.guard.get("injected"):
            draft.answer = "(Instructions embedded in the question were ignored; this answers the legitimate question only.)\n\n" + draft.answer
        if ctx.premise:   # state MSHA's record before the writer's cause, so a false premise is never left standing
            draft.answer = "\n".join(ctx.premise) + "\n\n" + draft.answer
        if plan.intent in O.PATTERN_INTENTS:
            # A pattern answer is built from the top-ranked incidents only; say so instead of implying completeness.
            cited_ids = set(re.findall(r"\[(E\d+)\]", draft.answer))
            n_inc = len({e["event_id"] for e in pack if e["id"] in cited_ids and e.get("event_id")})
            if n_inc:
                draft.answer += (f"\n\n*Coverage: drawn from {n_inc} MSHA investigation report(s), the best matches found for "
                                 "this question. Other matching reports may exist that are not shown here.*")
        answer, notes = output_filter(draft.answer, {e["id"] for e in pack})
        cited = sorted(set(re.findall(r"\[(E\d+)\]", answer)), key=lambda x: int(x[1:]))
        res = {"status": "answered", "intent": plan.intent, "answer": answer,
               "evidence": [e for e in pack if e["id"] in cited] or pack, "verification": ctx.ver, "filter_notes": notes,
               "human_review": "pending" if plan.output == "investigation_brief" or plan.intent in
               ("incident_investigation", "prevention_recommendations") else "optional"}
        try:   # traceability: claim -> citations -> sources. Best effort: a failure here must not block a verified answer.
            cm = ctx.registry["validator"].claim_map(ctx, answer)
            res["claim_map"], res["verification_report"] = cm["claims"], cm["summary"]
        except Exception as e:  # noqa: BLE001
            log("claim_map_error", error=str(e)[:120])
        return res
