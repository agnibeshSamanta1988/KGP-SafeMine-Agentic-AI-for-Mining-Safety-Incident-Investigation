"""RegulatoryAgent: owns 30 CFR text (as in force on a date) and links findings to the standards they cite."""
from __future__ import annotations

import re

from safemine.agent import orchestrator as O
from safemine.agents import executor
from safemine.agents.base import BaseAgent

OWNS = {"cfr_lookup"}


class RegulatoryAgent(BaseAgent):
    name = "regulatory"
    description = "30 CFR lookup/search with as-of-date versions; maps incidents to cited standards"

    def execute_step(self, ctx, st, from_critic: bool = False, trusted: bool = False) -> str:
        return executor.run_step(ctx, st, OWNS, from_critic, trusted)

    def enrich_standards(self, ctx) -> None:
        """Add the text of the standards an answer needs but the Planner skipped (a standard cited in a retrieved incident; the standards
        behind a brief or an open-ended question). Retrieval is delegated to the retrieval agent; CFR text is fetched here."""
        query, pack, plan, log = ctx.query, ctx.pack, ctx.plan, ctx.log
        # "which standard was cited and what does it require": the text must come from cfr_lookup, as in force on the incident date
        if (pack and O.STANDARD_ASK.search(query) and not O.SECTION_IN_QUERY.search(query)
                and not any(e["kind"] == "regulation" for e in pack)):
            top = next((e for e in pack if e["kind"] == "report_chunk"), None)
            if top:
                ids = lambda: [s for e in pack if e["kind"] == "report_chunk" and e["event_id"] == top["event_id"]  # noqa: E731
                               for s in e.get("cfr_ids", []) if re.fullmatch(r"\d{2,3}\.\d+", s)]
                if not ids():   # the retrieved chunks name no standard: ask retrieval for this incident's enforcement chunks
                    ctx.call(self.name, "retrieval", "execute_step",
                             O.ToolCall(tool="hybrid_search", purpose="find the cited standard",
                                        args={"query": query[:300], "event_id": top["event_id"], "sections": ["ENFORCEMENT"], "k": 4}))
                for sec in list(dict.fromkeys(ids()))[:2]:
                    log("enriched_cfr", section=sec, as_of=top.get("date"))
                    self.execute_step(ctx, O.ToolCall(tool="cfr_lookup", purpose="text of the cited standard",
                                                      args={"mode": "exact", "section": sec, **({"as_of": top["date"]} if top.get("date") else {})}),
                                      trusted=True)
        if (plan.output == "investigation_brief" or plan.intent in O.OPEN_ENDED_INTENTS) and pack and not any(e["kind"] == "regulation" for e in pack):
            enf, secs = O.standards_for_brief(pack)
            if enf:
                have = {e.get("chunk_id") for e in pack}
                pack.extend(O._evidence_from_tool("hybrid_search", [c for c in enf if c["chunk_id"] not in have], len(pack) + 1))
            for sec in secs:
                log("enriched_cfr", section=sec, purpose="brief")
                self.execute_step(ctx, O.ToolCall(tool="cfr_lookup", purpose="applicable standard", args={"mode": "exact", "section": sec}), trusted=True)
