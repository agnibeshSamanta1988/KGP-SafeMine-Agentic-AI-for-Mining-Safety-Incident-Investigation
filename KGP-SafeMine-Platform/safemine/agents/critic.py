"""CriticAgent: judges a verified draft and decides accept / revise / abstain. Deterministic rules override the model."""
from __future__ import annotations

import json

from safemine.agent import heuristics
from safemine.agent import orchestrator as O
from safemine.agents.base import BaseAgent

MIN_SUPPORT = 0.6   # a draft supported below this is never accepted, whatever the model says


class CriticAgent(BaseAgent):
    name = "critic"
    description = "LLM review of the draft with a deterministic support floor; can request up to two extra retrieval steps"

    def review(self, ctx, draft, ver) -> "O.Critique":
        llm, query, pack, log = ctx.llm, ctx.query, ctx.pack, ctx.log
        try:
            if llm.is_mock:
                crit = heuristics.critique(ver)
            else:
                crit = llm.chat_json([{"role": "system", "content": O.CRITIC_SYS},
                                      {"role": "user", "content": f"QUESTION: {query}\n\n"
                                       + (f"PREMISE CORRECTION (authoritative): {' '.join(ctx.premise)}\n\n" if ctx.premise else "")
                                       + f"DRAFT:\n{draft.answer}\n\nVERIFICATION: "
                                       f"{json.dumps({k: ver[k] for k in ('support_ratio', 'n_factual', 'unsupported')})[:2500]}"
                                       f"\n\nEVIDENCE IDS: {[e['id'] + ' ' + e['label'] for e in pack]}"}], O.Critique)
        except Exception as e:  # noqa: BLE001  bad JSON, budget, API/network/rate-limit errors -> fallback
            log("critic_fallback", error=str(e)[:200])
            crit = heuristics.critique(ver)
        if crit.decision == "accept" and ver["support_ratio"] < MIN_SUPPORT:   # deterministic override: low support can never be accepted
            crit = O.Critique(decision="revise", problems=["deterministic check: support_ratio < 0.6"] + crit.problems)
        if (ctx.wrong_dates and crit.decision == "revise" and crit.problems and ver["support_ratio"] >= MIN_SUPPORT and not ver["unsupported"]
                and not any(d in draft.answer for d in ctx.wrong_dates) and all(any(d in p for d in ctx.wrong_dates) for p in crit.problems)):
            # every complaint is about the QUESTION's wrong date, and the draft already uses the record's date: there is nothing left to revise
            log("critic_override_premise", problems=crit.problems[:2])
            crit = O.Critique(decision="accept")
        log("critic", round=ctx.rounds, decision=crit.decision, problems=crit.problems[:4])
        return crit
