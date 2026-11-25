"""Inter-agent messages. Every delegation between agents is a typed Message recorded on a per-request bus.

The bus is the single place that answers "who asked whom to do what, and what came back": it feeds the agent trail shown in the UI,
the trace log (traces.jsonl, Langfuse) and the unit tests. Payloads are short summaries, never full evidence text.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["task", "result", "error", "feedback"]


@dataclass
class Message:
    task_id: str
    sender: str
    recipient: str
    kind: Kind
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def brief(self, t0: float) -> dict[str, Any]:
        return {"t": round(self.ts - t0, 2), "from": self.sender, "to": self.recipient, "kind": self.kind, "action": self.action,
                **({"info": self.payload} if self.payload else {})}


class MessageBus:
    """Append-only record of the messages of ONE request. Thread-confined (one request = one bus), so no locking is needed."""

    def __init__(self, task_id: str, t0: float):
        self.task_id, self.t0 = task_id, t0
        self.messages: list[Message] = []

    def send(self, sender: str, recipient: str, kind: Kind, action: str, **payload: Any) -> Message:
        m = Message(self.task_id, sender, recipient, kind, action, {k: v for k, v in payload.items() if v is not None})
        self.messages.append(m)
        return m

    def trail(self) -> list[dict[str, Any]]:
        return [m.brief(self.t0) for m in self.messages]

    def between(self, sender: str, recipient: str) -> list[Message]:
        return [m for m in self.messages if m.sender == sender and m.recipient == recipient]
