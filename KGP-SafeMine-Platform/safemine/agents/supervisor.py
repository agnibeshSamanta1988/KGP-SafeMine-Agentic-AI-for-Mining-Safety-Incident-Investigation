"""Supervisor: coordinates the specialised agents for one question.

    safety -> planner -> [retrieval | regulatory] (per tool step) -> regulatory enrichment -> investigation (incident grounding)
           -> refinement loop:  investigation.draft -> validator.validate -> critic.review -> (extra steps back to retrieval/regulatory)
           -> validator.salvage / sanitize -> report.compose

The supervisor owns control flow only: task delegation, the global limits (steps, revisions, tokens, wall clock), the error policy and
the final result. Agents own the work. Error policy: a failing agent never raises to the user. Planner and Critic failures fall back to
deterministic heuristics; a Validator failure fails CLOSED (no verified answer -> abstain); anything unexpected ends in an abstention
with reason "internal_error". Every answer therefore passes the validator and the report agent, or it is not an answer.
"""
from __future__ import annotations

import re
from typing import Optional

from safemine import config
from safemine.agent import heuristics
from safemine.agent import orchestrator as O
from safemine.agent.llm import Usage, get_llm
from safemine.agents.base import Terminal, is_error
from safemine.agents.context import TaskContext
from safemine.agents.critic import CriticAgent
from safemine.agents.investigation import InvestigationAgent
from safemine.agents.planner import PlannerAgent
from safemine.agents.regulatory import RegulatoryAgent
from safemine.agents.report import ReportAgent
from safemine.agents.retrieval import RetrievalAgent
from safemine.agents.safety import SafetyAgent
from safemine.agents.validator import ValidatorAgent

SUP = "supervisor"
TOOL_OWNER = {"hybrid_search": "retrieval", "accident_stats": "retrieval", "record_lookup": "retrieval", "cfr_lookup": "regulatory"}


class Supervisor:
    def __init__(self, store: Optional["O.SessionStore"] = None):
        self.store = store or O.SessionStore()
        agents = (SafetyAgent(), PlannerAgent(), RetrievalAgent(), RegulatoryAgent(), InvestigationAgent(), ValidatorAgent(),
                  CriticAgent(), ReportAgent())
        self.agents = {a.name: a for a in agents}

    # ------------------------------------------------------------------ public entry point (same contract as the legacy Agent.run)
    def run(self, query: str, session_id: str = "default") -> dict:
        usage = Usage()
        try:
            llm = get_llm(usage)
        except Exception as e:  # noqa: BLE001  e.g. the CA certificate is not mounted: say so instead of an HTTP 500 traceback
            ctx = TaskContext(query=query, session_id=session_id, llm=None, usage=usage, store=self.store)
            ctx.log("llm_client_error", error=str(e)[:200])
            res = {"status": "error", "evidence": [],
                   "answer": f"The language-model client could not start ({type(e).__name__}: {str(e)[:160]}). "
                             "Check the API key and that the CA certificate files are mounted (docker: ./certs)."}
            return self._close(ctx, res)
        ctx = TaskContext(query=query, session_id=session_id, llm=llm, usage=usage, store=self.store,
                          deadline_s=float(config.AGENT_DEADLINE_S), registry=self.agents)
        try:
            res = self._pipeline(ctx)
        except Terminal as t:
            res = t.res
        except Exception as e:  # noqa: BLE001  last line of defence: never an exception or a half-built answer to the user
            ctx.log("internal_error", error=f"{type(e).__name__}: {str(e)[:160]}")
            res = {"status": "abstained", "reason": "internal_error", "evidence": ctx.pack,
                   "answer": "I could not complete this request reliably because of an internal error, so I am not giving an answer."}
        return self._close(ctx, res)

    def _close(self, ctx: TaskContext, res: dict) -> dict:
        res["trace"] = ctx.trace
        res["agent_trail"] = ctx.bus.trail()
        return O.finalize(self.store, res, ctx.session_id, ctx.turn_id, ctx.orig_query, ctx.usage, ctx.t0)

    # ------------------------------------------------------------------ delegation helpers
    def _call(self, ctx, agent: str, action: str, *a, **kw):
        return ctx.call(SUP, agent, action, *a, **kw)

    def _dispatch(self, ctx, steps, from_critic: bool = False) -> None:
        """Send each planned tool step to the agent that owns the tool, in order (evidence ids E1, E2 ... follow this order)."""
        for st in steps:
            out = self._call(ctx, TOOL_OWNER[st.tool], "execute_step", st, from_critic=from_critic)
            if is_error(out):
                ctx.log("tool_error", tool=st.tool, error=out.error)   # an agent crash is handled like a tool failure: carry on
            elif out == "stop":
                return

    # ------------------------------------------------------------------ the pipeline
    def _pipeline(self, ctx: TaskContext) -> dict:
        self._call(ctx, "safety", "screen")                                  # may end the request (refusal / abstention)
        out = self._call(ctx, "planner", "plan")
        if is_error(out):                                                    # planner bug: deterministic plan, request continues
            ctx.log("planner_fallback", error=out.error)
            ctx.plan = heuristics.plan(ctx.query)
        self._dispatch(ctx, ctx.plan.steps)
        out = self._call(ctx, "regulatory", "enrich_standards")
        if is_error(out):
            ctx.log("enrich_error", error=out.error)
        if ctx.plan.intent == "incident_investigation" and O.FULL_DATE.search(ctx.query) and not O.DATE_BOUND.search(ctx.query):
            out = self._call(ctx, "investigation", "ground_incident")        # may end the request (no matching event / not published)
            if is_error(out):                                                # fail closed: an unverifiable incident match is not answered
                raise Terminal({"status": "abstained", "reason": "incident_grounding_failed", "evidence": [],
                                "answer": "I could not confirm which incident this question refers to, so I will not answer from similar events."})
        for e in ctx.pack:   # evidence the injection screen had to clean: visible in the trace and in the console
            if e.get("injection_removed"):
                ctx.log("injection_in_evidence", evidence=e["id"], removed=e["injection_removed"], rules=sorted(set(e["injection_rules"])), source=e.get("chunk_id") or e["label"])
        if not ctx.pack:
            return self._call(ctx, "report", "no_evidence")
        self._refine(ctx)
        self._call(ctx, "validator", "salvage")
        if ctx.decision != "accept" or ctx.draft is None or ctx.ver is None:
            return self._call(ctx, "report", "not_accepted")
        out = self._call(ctx, "validator", "sanitize")
        if is_error(out):                                                    # cannot prove the draft is clean: do not release it
            raise Terminal({"status": "abstained", "reason": "validation_failed", "evidence": ctx.pack,
                            "answer": "I could not complete the verification of my draft, so I am not giving an answer. "
                                      "The closest evidence found is listed below."})
        res = self._call(ctx, "report", "compose")
        if is_error(res):
            raise Terminal({"status": "abstained", "reason": "report_failed", "evidence": ctx.pack,
                            "answer": "I could not assemble a verified answer, so I am not giving one. The closest evidence found is listed below."})
        return res

    def _refine(self, ctx: TaskContext) -> None:
        """Draft -> validate -> critique, repeated while the critic asks for a revision (bounded by MAX_REVISIONS; a brief gets two rounds)."""
        plan = ctx.plan
        for rnd in range(2 if plan.output == "investigation_brief" else config.MAX_REVISIONS + 1):   # a brief costs 3 calls a round
            ctx.rounds = rnd
            if ctx.overdue():
                ctx.log("deadline", seconds=config.AGENT_DEADLINE_S)
                break
            draft = self._call(ctx, "investigation", "draft", ctx.problems)
            if is_error(draft) or draft is None:
                break
            if draft.part_errors and ctx.prev is not None:   # the revision round lost parts (budget, cut-off JSON): keep the earlier draft
                ctx.log("brief_revision_discarded", part_errors=draft.part_errors)
                ctx.draft, ctx.ver = ctx.prev
                ctx.decision = "accept" if ctx.ver["support_ratio"] >= 0.6 else "abstain"
                break
            ver = self._call(ctx, "validator", "validate", draft)
            if is_error(ver):                                # fail closed: an unvalidated draft is never accepted
                ctx.draft, ctx.decision = draft, "abstain"
                break
            ctx.draft, ctx.ver, ctx.prev = draft, ver, (draft, ver)
            if ver["n_factual"] and not draft.insufficient_evidence and (ctx.best is None or ver["support_ratio"] > ctx.best[0]):
                ctx.best = (ver["support_ratio"], draft, ver)
            # model says the evidence is insufficient and cites nothing: abstain now, do not loop through revisions
            if draft.insufficient_evidence and (ver["n_factual"] == 0 or not O.CITE_RE.search(draft.answer)):
                ctx.decision = "abstain"
                break
            crit = self._call(ctx, "critic", "review", draft, ver)
            if is_error(crit):
                ctx.log("critic_fallback", error=crit.error)
                crit = heuristics.critique(ver)
            ctx.decision = crit.decision
            if ctx.decision in ("accept", "abstain"):
                break
            ctx.problems = crit.problems + [f"Unsupported: {u['sentence'][:120]} -> {u['issues']}" for u in ver["unsupported"][:4]]
            if crit.extra_steps:                             # the critic asks for more evidence: back to the owning agents
                self._dispatch(ctx, crit.extra_steps, from_critic=True)
        else:
            ctx.decision = "accept" if ctx.ver and ctx.ver["support_ratio"] >= 0.6 else "abstain"
