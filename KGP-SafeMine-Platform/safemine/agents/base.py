"""BaseAgent: one role, a small set of actions, uniform error handling.

`invoke(ctx, action, ...)` is the only way agents are called. It (1) records the request and the outcome on the message bus,
(2) converts an unexpected exception into an AgentError result instead of letting it escape, and (3) times the call.
An agent action returns its value, or raises `Terminal(res)` when the request must end now (refusal, abstention, error answer).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional


class Terminal(Exception):
    """Raised by an agent action to end the whole request with this result dict (refuse / abstain / error)."""

    def __init__(self, res: dict):
        super().__init__(res.get("status", "terminal"))
        self.res = res


@dataclass
class AgentError:
    agent: str
    action: str
    error: str

    def __bool__(self) -> bool:      # `if result:` is False for an error
        return False


class BaseAgent:
    name = "agent"
    description = ""

    def invoke(self, ctx, action: str, *args: Any, _sender: str = "supervisor", **kw: Any) -> Any:
        fn = getattr(self, action, None)
        if fn is None or action.startswith("_"):
            raise AttributeError(f"{self.name} has no action {action!r}")
        t = time.time()
        ctx.bus.send(_sender, self.name, "task", action)
        try:
            out = fn(ctx, *args, **kw)
        except Terminal:
            ctx.bus.send(self.name, _sender, "result", action, ms=int((time.time() - t) * 1000), terminal=True)
            raise
        except Exception as e:  # noqa: BLE001  an agent bug or an unexpected tool failure must not become a user-facing traceback
            err = AgentError(self.name, action, f"{type(e).__name__}: {str(e)[:160]}")
            ctx.bus.send(self.name, _sender, "error", action, error=err.error, ms=int((time.time() - t) * 1000))
            ctx.log("agent_error", agent=self.name, action=action, error=err.error)
            return err
        ctx.bus.send(self.name, _sender, "result", action, ms=int((time.time() - t) * 1000))
        return out


def is_error(x: Optional[Any]) -> bool:
    return isinstance(x, AgentError)
