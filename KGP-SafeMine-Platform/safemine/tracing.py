"""Langfuse tracing (Langfuse Cloud, or a self-hosted Langfuse v3+ server). One trace per question, one span per agent step, one
generation per LLM call, each with its real start and end time.

Why OpenTelemetry directly. Langfuse Cloud shut down its old ingestion API (/api/public/ingestion) on 16 Nov 2026; the old `langfuse<3`
SDK sent there and every trace was rejected with HTTP 410 (silently, because tracing errors are swallowed). The current SDK (v5) exports
OpenTelemetry spans to /api/public/otel/v1/traces. It cannot back-date an observation, and this module sends a question AFTER it has
finished (the agent records every step in res["trace"]), so the spans are created on our own OpenTelemetry tracer with explicit start and
end times and the Langfuse attribute names (LangfuseOtelSpanAttributes); the Langfuse client provides authentication and export.

Configuration (.env): LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST = https://cloud.langfuse.com (EU) or
https://us.cloud.langfuse.com (US). LANGFUSE_ENABLED=false (or the Settings toggle) stops sending, to save the free-tier quota; the local
traces.jsonl and the session history are always written. Any failure is swallowed so tracing never breaks an answer, but it is RECORDED:
status() reports "unreachable" / "keys rejected" and the last error, and the first failure is printed once to stderr.
"""
from __future__ import annotations

import atexit
import json
import os
import sys
import threading

_client = None          # Langfuse client (or None when off / not configured)
_tracer = None          # OpenTelemetry tracer whose spans the client exports
_tried = False
_LAST_ERROR = {"msg": None, "printed": False}
_RUNTIME = {"enabled": None}   # Settings toggle; None = follow LANGFUSE_ENABLED
_LOCK = threading.Lock()
TRACER_NAME = "safemine"
_NEXT_TRACE = threading.local()   # trace id the next root span must use (deterministic per turn)


def _id_generator():
    """OpenTelemetry id generator that gives a root span the trace id we chose for the turn (so the root has no fake parent)."""
    from opentelemetry.sdk.trace.id_generator import RandomIdGenerator

    class _TurnIds(RandomIdGenerator):
        def generate_trace_id(self) -> int:
            tid = getattr(_NEXT_TRACE, "value", None)
            if tid:
                _NEXT_TRACE.value = None
                return tid
            return super().generate_trace_id()
    return _TurnIds()


def _note_error(where: str, e: Exception) -> None:
    _LAST_ERROR["msg"] = f"{where}: {type(e).__name__}: {str(e)[:200]}"
    if not _LAST_ERROR["printed"]:      # once per process, never the keys
        _LAST_ERROR["printed"] = True
        print(f"[tracing] Langfuse {_LAST_ERROR['msg']}", file=sys.stderr)


def configured() -> bool:
    """Both keys are set (whether or not sending is switched on)."""
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def switched_on() -> bool:
    """The on/off switch: the Settings toggle if it was used in this process, else LANGFUSE_ENABLED (default on)."""
    if _RUNTIME["enabled"] is not None:
        return _RUNTIME["enabled"]
    return os.getenv("LANGFUSE_ENABLED", "true").lower() != "false"


def set_enabled(on: bool) -> None:
    """Settings toggle: start or stop sending traces now (no restart). Off saves the Langfuse free-tier quota."""
    _RUNTIME["enabled"] = bool(on)
    if not on:
        flush()   # what was already queued still goes out


def _host() -> str:
    return os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")


def _lf():
    """The Langfuse client, created on first use. None when keys are missing or creation failed."""
    global _client, _tracer, _tried
    if _tried:
        return _client
    with _LOCK:
        if _tried:
            return _client
        _tried = True
        if not configured():
            return None
        try:
            from langfuse import Langfuse
            from opentelemetry.sdk.trace import TracerProvider
            provider = TracerProvider(id_generator=_id_generator())   # our own provider: nothing else in the process is exported
            _client = Langfuse(public_key=os.getenv("LANGFUSE_PUBLIC_KEY"), secret_key=os.getenv("LANGFUSE_SECRET_KEY"), host=_host(),
                               tracer_provider=provider,
                               should_export_span=lambda s: s.instrumentation_scope is not None and s.instrumentation_scope.name == TRACER_NAME)
            _tracer = provider.get_tracer(TRACER_NAME)
            atexit.register(flush)   # short-lived runs (CLI, eval scripts) exit before the background exporter has sent the spans
        except Exception as e:  # noqa: BLE001
            _note_error("client", e)
            _client = _tracer = None
    return _client


def enabled() -> bool:
    """Traces are being sent: keys configured, switched on and the client started."""
    return switched_on() and _lf() is not None


def _short(v, n=1500):
    s = v if isinstance(v, str) else json.dumps(v, default=str, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + " …"


def _ns(epoch: float) -> int:
    return int(epoch * 1e9)


def trace_id_for(turn_id: str) -> str:
    """Deterministic 32-hex Langfuse trace id for a turn: a replayed question updates its trace instead of duplicating it."""
    from langfuse import Langfuse
    return Langfuse.create_trace_id(seed=str(turn_id))


def trace_url(turn_id: str) -> str | None:
    """Link to this question's trace in the Langfuse dashboard (None when tracing is off)."""
    lf = _lf()
    if lf is None or not turn_id:
        return None
    try:
        return lf.get_trace_url(trace_id=trace_id_for(turn_id))
    except Exception:  # noqa: BLE001
        return None


STEP_KINDS = {"plan", "tool", "verify", "critic", "policy_classifier", "premise_check"}


def emit(query: str, res: dict, model: str = "", provider: str = "", calls: list[dict] | None = None, t_end: float | None = None,
         t_start: float | None = None) -> None:
    """Send one finished question to Langfuse. `res` is the dict returned by Agent.run (trace, usage, latency_s, turn_id ...).
    `calls` (Usage.log) gives one generation per LLM call (planner, writer, critic, safety gate) with its own timing and tokens;
    without it (replay of old traces) a single generation sums the question's calls."""
    if not switched_on():
        return
    lf = _lf()
    if lf is None or _tracer is None:
        return
    try:
        import time

        from langfuse import LangfuseOtelSpanAttributes as A
        from opentelemetry import trace as ot
        from opentelemetry.context import Context

        latency = float(res.get("latency_s") or 0)
        if t_start:          # the agent's own clock: exact, so child spans never start before their parent
            start, end = t_start, t_start + latency
        else:                # replay: only the end time is known
            end = t_end or time.time()
            start = end - latency
        if calls:            # never let an LLM call fall outside the root span
            start = min(start, min(c["start"] for c in calls))
            end = max(end, max(c["end"] for c in calls))
        status = res.get("status", "?")
        tid = trace_id_for(res.get("turn_id") or f"{query}{start}")
        _NEXT_TRACE.value = int(tid, 16)   # the root span below takes this trace id (a true root: empty context, no parent)
        parent = Context()
        u = res.get("usage") or {}
        meta = {"status": status, "intent": res.get("intent"), "tool_calls": res.get("tool_calls"), "latency_s": latency,
                "support_ratio": (res.get("verification") or {}).get("support_ratio"), "human_review": res.get("human_review"),
                "provider": provider or u.get("provider"), "model": model, "llm_calls": u.get("llm_calls"),
                "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
                "rate_limit_sleep_s": u.get("rate_limit_sleep_s"), "rule": res.get("rule")}
        root = _tracer.start_span("safemine.ask", context=parent, start_time=_ns(start), attributes={
            A.TRACE_NAME: "safemine.ask", A.TRACE_SESSION_ID: str(res.get("session_id") or ""),
            A.TRACE_TAGS: [t for t in (status, res.get("intent") or "no_intent", provider or u.get("provider") or "") if t],
            A.TRACE_METADATA: _short(meta, 3000), A.OBSERVATION_TYPE: "agent",
            A.OBSERVATION_INPUT: _short(query, 2000), A.OBSERVATION_OUTPUT: _short(res.get("answer", ""), 4000),
            A.OBSERVATION_LEVEL: "WARNING" if status in ("refused", "abstained") else ("ERROR" if status == "error" else "DEFAULT"),
            A.AS_ROOT: True})
        ctx = ot.set_span_in_context(root)
        for ev in res.get("trace", []):
            kind = ev.get("kind", "event")
            at = start + float(ev.get("t", 0))
            body = {k: v for k, v in ev.items() if k not in ("t", "kind")}
            level = "ERROR" if "error" in kind else ("WARNING" if kind in ("refuse", "abstain", "injection_stripped", "injection_in_evidence",
                                                                            "step_limit") else "DEFAULT")
            is_step = kind in STEP_KINDS
            name = f"tool:{ev.get('tool')}" if kind == "tool" else kind
            sp = _tracer.start_span(name, context=ctx, start_time=_ns(at), attributes={
                A.OBSERVATION_TYPE: ("tool" if kind == "tool" else "span") if is_step else "event",
                A.OBSERVATION_INPUT: _short(body.get("args") or body.get("steps") or "", 1200) if is_step else "",
                A.OBSERVATION_OUTPUT: _short(body, 1500) if is_step else "",
                A.OBSERVATION_METADATA: "" if is_step else _short(body, 1500), A.OBSERVATION_LEVEL: level})
            sp.end(end_time=_ns(at) + 1_000_000)
        if calls:
            for c in calls:
                g = _tracer.start_span(c.get("name") or "llm", context=ctx, start_time=_ns(c["start"]), attributes={
                    A.OBSERVATION_TYPE: "generation", A.OBSERVATION_MODEL: c.get("model") or model,
                    A.OBSERVATION_INPUT: _short(c.get("input", ""), 1500), A.OBSERVATION_OUTPUT: _short(c.get("output", ""), 1500),
                    A.OBSERVATION_USAGE_DETAILS: json.dumps({"input": int(c.get("prompt_tokens") or 0), "output": int(c.get("completion_tokens") or 0)}),
                    A.OBSERVATION_METADATA: _short({"json_mode": c.get("json_mode"), "provider": provider}, 300)})
                g.end(end_time=_ns(c["end"]))
        elif u.get("llm_calls"):
            g = _tracer.start_span("llm (all calls for this question)", context=ctx, start_time=_ns(start), attributes={
                A.OBSERVATION_TYPE: "generation", A.OBSERVATION_MODEL: model or u.get("provider") or "",
                A.OBSERVATION_USAGE_DETAILS: json.dumps({"input": int(u.get("prompt_tokens") or 0), "output": int(u.get("completion_tokens") or 0)}),
                A.OBSERVATION_METADATA: _short({"llm_calls": u.get("llm_calls"), "llm_latency_s": u.get("llm_latency_s")}, 300)})
            g.end(end_time=_ns(end))
        root.end(end_time=_ns(end))
    except Exception as e:  # noqa: BLE001
        _note_error("emit", e)


def flush() -> None:
    lf = _client
    if lf is not None:
        try:
            lf.flush()
        except Exception as e:  # noqa: BLE001
            _note_error("flush", e)


_STATUS = {"t": 0.0, "v": None, "busy": False}


def _probe(host: str) -> bool:
    import urllib.request
    # "localhost" is tried over IPv6 first on Windows and can stall for seconds: probe the loopback address directly
    url = host.rstrip("/").replace("//localhost", "//127.0.0.1") + "/api/public/health"
    try:
        return urllib.request.urlopen(url, timeout=3).status == 200
    except Exception:  # noqa: BLE001
        return False


def _auth_ok() -> bool | None:
    """True / False when the server answered the key check, None when it could not be asked."""
    lf = _lf()
    if lf is None:
        return None
    try:
        return bool(lf.auth_check())
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        if "401" in msg or "unauthor" in msg or "invalid" in msg or "403" in msg:
            _note_error("auth", e)
            return False
        return None


def _refresh(host: str) -> None:
    import time
    reachable = _probe(host)
    prev_auth = (_STATUS["v"] or {}).get("auth")
    # publish reachability at once; the key check is a second network call and only adds its result when it arrives
    _STATUS.update(t=time.time(), v={"enabled": True, "switched_on": switched_on(), "reachable": reachable, "auth": prev_auth if reachable else None,
                                      "host": host, "last_error": _LAST_ERROR["msg"]}, busy=bool(reachable))   # still busy while keys are checked
    if reachable:
        auth = _auth_ok()
        _STATUS["v"] = {**_STATUS["v"], "auth": auth, "last_error": _LAST_ERROR["msg"]}
    _STATUS["busy"] = False


def status(max_age: float = 30.0, block: bool = False) -> dict:
    """{"enabled": keys configured, "switched_on": sending on/off, "reachable": True/False/None, "auth": True/False/None, "host": ...}.

    NEVER blocks a page render: the check runs in a background thread and the last result is returned at once (a stale result is refreshed
    in the background). Pass block=True where a real answer is needed (the API /health, the command line)."""
    import time
    host = _host()
    if not configured():
        _STATUS.update(t=time.time(), v={"enabled": False, "switched_on": switched_on(), "reachable": None, "auth": None, "host": host})
        return _STATUS["v"]
    if block:
        _refresh(host)
        return _STATUS["v"]
    stale = _STATUS["v"] is None or time.time() - _STATUS["t"] > max_age or not _STATUS["v"].get("enabled")
    if stale and not _STATUS["busy"]:
        _STATUS["busy"] = True
        threading.Thread(target=_refresh, args=(host,), name="langfuse-status", daemon=True).start()
    v = dict(_STATUS["v"] or {"enabled": True, "reachable": None, "auth": None, "host": host})
    v["switched_on"] = switched_on()
    return v


def replay(path: str, since_ts: float = 0.0) -> int:
    """Send the traces of data_processed/traces.jsonl to Langfuse again (questions asked while tracing was off or failing). Trace ids are
    derived from the turn ids, so a trace that is already in Langfuse is updated, not duplicated. Returns the number sent."""
    n = 0
    for line in open(path, encoding="utf-8"):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not rec.get("turn_id") or rec.get("t_end", since_ts) < since_ts:
            continue
        emit(rec.get("query", ""), rec, model=(rec.get("usage") or {}).get("model", ""), provider=(rec.get("usage") or {}).get("provider", ""),
             t_end=rec.get("t_end"))
        n += 1
    flush()
    return n


if __name__ == "__main__":
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from safemine import config  # noqa: F401  (loads .env)
    if len(sys.argv) > 1 and sys.argv[1] == "replay":
        print("sent", replay(str(config.OUT / "traces.jsonl")), "traces to", _host())
    else:
        print(status(block=True))
