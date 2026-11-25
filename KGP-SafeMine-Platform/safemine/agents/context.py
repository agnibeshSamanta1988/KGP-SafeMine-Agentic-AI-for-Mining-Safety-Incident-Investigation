"""TaskContext: all state of ONE request, passed explicitly between agents (no globals, no closures).

Agents are stateless singletons; everything that changes during a question lives here. That is what makes the system safe to run
concurrently (one context per request), easy to test (build a context, call one agent) and easy to inspect (the context is the
complete picture of a run).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from safemine.agents.messages import MessageBus


@dataclass
class TaskContext:
    query: str
    session_id: str
    llm: Any
    usage: Any
    store: Any = None
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    t0: float = field(default_factory=time.time)
    deadline_s: float = 0.0                       # 0 = no wall-clock limit
    trace: list[dict] = field(default_factory=list)
    bus: Optional[MessageBus] = None
    registry: dict[str, Any] = field(default_factory=dict)   # agent name -> agent, filled by the supervisor
    # ---- evolving state
    orig_query: str = ""
    guard: dict = field(default_factory=dict)     # result of the input guard (ok, query, injected, removed)
    plan: Any = None
    pack: list[dict] = field(default_factory=list)   # the evidence pack: E1, E2, ... in the order it was gathered
    steps_used: int = 0
    seen_calls: set = field(default_factory=set)
    named_incident: bool = False
    history_text: str = ""                        # the user's earlier questions in this session (a follow-up inherits their stated filters)
    premise: list[str] = field(default_factory=list)
    wrong_dates: list[str] = field(default_factory=list)   # dates the question gave that the record contradicts: never to be echoed as fact
    problems: list[str] = field(default_factory=list)
    draft: Any = None
    ver: Optional[dict] = None
    decision: str = "abstain"
    best: Optional[tuple] = None                  # (support_ratio, draft, verification) of the best round so far
    prev: Optional[tuple] = None                  # (draft, verification) of the previous round
    caveat: bool = False
    rounds: int = 0
    removed: int = 0                              # unverifiable statements removed from the final answer
    result: Optional[dict] = None                 # set when the run is finished

    def __post_init__(self):
        self.orig_query = self.orig_query or self.query
        self.bus = self.bus or MessageBus(self.turn_id, self.t0)

    def log(self, kind: str, **kw: Any) -> None:
        self.trace.append({"t": round(time.time() - self.t0, 2), "kind": kind, **kw})

    def evidence_map(self) -> dict[str, str]:
        return {e["id"]: e["label"] + "\n" + e["text"] for e in self.pack}   # the label (date, CFR, source) is evidence too

    def overdue(self) -> bool:
        return bool(self.deadline_s) and time.time() - self.t0 > self.deadline_s

    def call(self, sender: str, recipient: str, action: str, *args: Any, **kw: Any) -> Any:
        """Delegate to another agent by name, recording the request and its outcome on the bus."""
        return self.registry[recipient].invoke(self, action, *args, _sender=sender, **kw)
