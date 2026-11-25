"""RetrievalAgent: owns hybrid search over reports, accident statistics and record lookups."""
from __future__ import annotations

from safemine.agent import orchestrator as O
from safemine.agents import executor
from safemine.agents.base import BaseAgent

OWNS = {"hybrid_search", "accident_stats", "record_lookup"}


class RetrievalAgent(BaseAgent):
    name = "retrieval"
    description = "Hybrid BM25 + dense search, accident statistics, record lookups"

    def execute_step(self, ctx, st, from_critic: bool = False, trusted: bool = False) -> str:
        return executor.run_step(ctx, st, OWNS, from_critic, trusted)

    def fetch_named_event(self, ctx, q_dates: set, ql: str) -> list[dict]:
        """The report chunks of the one event named by mine + exact date, when the search missed it."""
        return O.named_event_chunks(ql, q_dates)
