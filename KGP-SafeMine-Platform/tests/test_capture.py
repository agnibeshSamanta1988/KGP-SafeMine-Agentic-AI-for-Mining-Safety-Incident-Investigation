"""Every question must leave a history entry (sessions.sqlite) and a Langfuse trace, whatever its outcome and however it was served."""
from __future__ import annotations

import sys

import pytest

from conftest import ScriptedLLM, good_script
from safemine import tracing

Q = "What root causes did MSHA find for haul truck fatalities at surface mines?"


@pytest.fixture
def api(env, monkeypatch):
    import safemine.tools.hybrid_search as hs
    monkeypatch.setattr(hs, "warmup", lambda: None)          # do not load the real index in a test
    for m in [m for m in sys.modules if m == "app.api"]:
        del sys.modules[m]
    from fastapi.testclient import TestClient
    import app.api as api_mod
    from safemine.agent.orchestrator import Agent
    api_mod.agent = Agent(env.store)
    api_mod._cache.clear()
    api_mod._hits.clear()
    env.sent = []
    monkeypatch.setattr(tracing, "emit", lambda query, res, **k: env.sent.append((query, res.get("status"), res.get("turn_id"), res.get("session_id"))))
    return TestClient(api_mod.app), env


def turns(env, session):
    return env.store.db.execute("select status, query from turns where session_id=? order by ts", (session,)).fetchall()


def test_every_outcome_is_saved_and_traced(api):
    client, env = api
    env.install(ScriptedLLM(script=good_script()))
    qs = [(Q, "answered"), ("Who was at fault for the haul truck accident and should the foreman be prosecuted?", "refused"),
          ("What was the cause of the fatality at Test Mine on March 3, 2027?", "abstained")]
    for q, expected in qs:
        r = client.post("/ask", json={"question": q, "session_id": "cap-1"}).json()
        assert r["status"] == expected
    assert [t[0] for t in turns(env, "cap-1")] == ["answered", "refused", "abstained"]          # history keeps all three
    assert [s[1] for s in env.sent] == ["answered", "refused", "abstained"]                        # and each was traced


def test_a_repeated_question_served_from_cache_is_still_recorded(api):
    client, env = api
    env.install(ScriptedLLM(script=good_script()))
    first = client.post("/ask", json={"question": Q, "session_id": "cap-2"}).json()
    second = client.post("/ask", json={"question": Q, "session_id": "cap-2"}).json()
    assert second["cached"] is True and second["answer"] == first["answer"]
    assert second["turn_id"] != first["turn_id"]                                                   # its own turn: it can be reviewed separately
    assert len(turns(env, "cap-2")) == 2 and len(env.sent) == 2                                    # in the history and in Langfuse
    assert second["tool_calls"] == 0 and second["trace"][0]["kind"] == "cache_hit"
    assert client.post("/review", json={"turn_id": second["turn_id"], "decision": "approve"}).status_code == 200


def test_sessions_stay_separate(api):
    client, env = api
    env.install(ScriptedLLM(script=good_script()))
    client.post("/ask", json={"question": Q, "session_id": "cap-A"})
    client.post("/ask", json={"question": "How many fatal accidents by classification?", "session_id": "cap-B"})
    assert len(turns(env, "cap-A")) == 1 and len(turns(env, "cap-B")) == 1
    assert {s[3] for s in env.sent} == {"cap-A", "cap-B"}


def test_health_reports_tracing_state(api, monkeypatch):
    client, env = api
    monkeypatch.setattr(tracing, "status", lambda *a, **k: {"enabled": True, "reachable": False, "host": "x"})
    from safemine import config
    monkeypatch.setattr(config, "startup_checks", lambda: [])
    assert client.get("/health").json()["tracing"]["reachable"] is False


def test_tracing_status_without_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    tracing._STATUS["v"] = None
    s = tracing.status(max_age=0)
    assert s["enabled"] is False and s["reachable"] is None


def test_replay_sends_each_recorded_turn(tmp_path, monkeypatch):
    import json
    sent = []
    monkeypatch.setattr(tracing, "emit", lambda q, r, **k: sent.append((q, r["turn_id"])))
    monkeypatch.setattr(tracing, "flush", lambda: None)
    f = tmp_path / "traces.jsonl"
    f.write_text("\n".join([json.dumps({"query": "q1", "turn_id": "t1", "trace": []}), "not json", json.dumps({"query": "no id"}),
                            json.dumps({"query": "q2", "turn_id": "t2", "trace": []})]))
    assert tracing.replay(str(f)) == 2 and sent == [("q1", "t1"), ("q2", "t2")]


def test_the_langfuse_status_check_never_blocks_a_page(monkeypatch):
    """Regression: the sidebar's 'Langfuse connected' check blocked about 3 s (and a full timeout whenever Langfuse was down) on every page render."""
    import time
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setattr(tracing, "_probe", lambda host: (time.sleep(1.0), True)[1])          # a slow Langfuse
    tracing._STATUS.update(t=0.0, v=None, busy=False)
    t = time.time()
    first = tracing.status()
    assert time.time() - t < 0.2 and first["reachable"] is None                                   # answers at once: "still checking"
    time.sleep(1.4)
    t = time.time()
    assert tracing.status()["reachable"] is True and time.time() - t < 0.2                        # the background result is used afterwards
    tracing._STATUS.update(t=0.0, v=None, busy=False)
    assert tracing.status(block=True)["reachable"] is True                                        # /health still gets a real answer


def test_preload_runs_once_and_never_raises(monkeypatch):
    from app import lib
    calls = []
    monkeypatch.setattr(lib, "_PRELOAD", {"started": False})
    import threading
    real = threading.Thread
    monkeypatch.setattr(threading, "Thread", lambda target=None, **k: type("T", (), {"start": lambda self: calls.append(1)})())
    lib.preload()
    lib.preload()
    assert len(calls) == 1
