"""Shared fixtures: fake tools, a scripted fake LLM, an isolated session store. No network, no API key, no real index needed."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safemine import config, tracing  # noqa: E402
from safemine.agent import orchestrator as O  # noqa: E402
from safemine.agent.llm import Usage  # noqa: E402

CHUNK = {"chunk_id": "2019/test-mine#final::SUMMARY::0", "event_id": "2019/test-mine", "doc_type": "final_report", "date": "2019-03-04",
         "section": "SUMMARY", "subheading": None, "classification": "Powered Haulage", "mine_type": "Surface", "state": "Kentucky",
         "mine_name": "Test Mine", "cfr_ids": ["56.14211"], "source_path": "fatality_investigations/2019/test-mine.pdf",
         "text": "The miner was struck by a haul truck while working near the dump point. The accident occurred because management failed "
                 "to ensure that equipment was blocked against motion. MSHA cited 30 CFR 56.14211 in the investigation."}
CFR = {"mode": "exact", "citation": "30 CFR 56.14211", "section": "56.14211", "subject": "Blocking equipment in a raised position.",
       "text": "(a) Persons shall not work on top of, under, or work from mobile equipment in a raised position until blocked.",
       "edition": "snapshot", "edition_date": "2026-10-30", "version_status": "exact"}


class ScriptedLLM:
    """A fake model: answers chat_json(messages, Schema) from a script keyed by schema name (value, list queue, or callable)."""
    is_mock = False

    def __init__(self, usage=None, script=None):
        self.usage = usage or Usage()
        self.script = dict(script or {})
        self.calls: list[str] = []

    def chat_json(self, messages, schema, max_tokens=600):
        name = schema.__name__
        self.calls.append(name)
        v = self.script.get(name)
        if isinstance(v, list):
            v = v.pop(0) if len(v) > 1 else v[0]
        if callable(v):
            v = v()
        if isinstance(v, Exception):
            raise v
        if v is None:
            raise RuntimeError(f"no script for {name}")
        return v if isinstance(v, schema) else schema.model_validate(v)

    def chat(self, *a, **k):
        raise RuntimeError("not scripted")


def good_script(answer="Management failed to ensure the equipment was blocked against motion [E1]."):
    return {"PolicyDecision": {"category": "OK"},
            "Plan": {"intent": "root_cause_patterns", "output": "answer",
                     "steps": [{"tool": "hybrid_search", "args": {"query": "haul truck blocked against motion"}}]},
            "Draft": {"answer": answer},
            "Critique": {"decision": "accept"}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """An isolated environment. Returns a namespace with .store, .calls (tool call log) and .install(llm) to choose the fake model."""
    monkeypatch.setattr(config, "OUT", tmp_path)
    monkeypatch.setattr(tracing, "_client", None)
    monkeypatch.setattr(tracing, "_tried", True)
    store = O.SessionStore(tmp_path / "s.sqlite")

    class E:
        pass

    e = E()
    e.store, e.calls, e.tmp = store, [], tmp_path

    def hybrid(**kw):
        e.calls.append(("hybrid_search", kw))
        return [dict(CHUNK)]

    def cfr(**kw):
        e.calls.append(("cfr_lookup", kw))
        return dict(CFR)

    def stats(**kw):
        e.calls.append(("accident_stats", kw))
        return {"metric": "count_by", "args": kw, "total_matching_records": 5, "rows": [{"key": "Powered Haulage", "n": 5}],
                "source": "test", "note": ""}

    monkeypatch.setattr(O, "TOOLS", {"hybrid_search": hybrid, "cfr_lookup": cfr, "accident_stats": stats, "record_lookup": lambda **k: {"error": "x"}})

    def install(llm):
        from safemine.agents import supervisor as S
        monkeypatch.setattr(S, "get_llm", lambda usage=None: (setattr(llm, "usage", usage or llm.usage), llm)[1])
        monkeypatch.setattr(O, "get_llm", lambda usage=None: (setattr(llm, "usage", usage or llm.usage), llm)[1])
        return llm

    e.install = install
    monkeypatch.setattr(O, "_events_with_final_report", lambda: frozenset({"2019/test-mine"}))
    return e


@pytest.fixture
def supervisor(env):
    from safemine.agents.supervisor import Supervisor
    return Supervisor(env.store)
