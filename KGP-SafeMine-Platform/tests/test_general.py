"""General chat mode (safemine/agent/general.py): grounded first, labelled general knowledge only where it cannot misstate a real event."""
from __future__ import annotations

import pytest

from safemine.agent import general
from safemine.agent import llm as llm_mod


class FakeAgent:
    """Stands in for the grounded agent: returns a fixed result and records whether it was asked."""

    def __init__(self, store, result: dict):
        self.store, self.result, self.asked = store, result, []

    def run(self, query, session_id="x"):
        self.asked.append(query)
        return {"turn_id": "g1", "session_id": session_id, "trace": [], "evidence": [], "latency_s": 0.1,
                "usage": {"llm_calls": 1, "prompt_tokens": 1, "completion_tokens": 1}, **self.result}


class FakeLLM:
    is_mock = False

    def __init__(self, text, usage=None):
        self.text, self.calls, self.usage = text, [], usage or llm_mod.Usage()

    def chat(self, messages, max_tokens=500, **kw):
        self.calls.append(messages)
        return self.text


def use_llm(monkeypatch, text) -> FakeLLM:
    fake = FakeLLM(text)
    monkeypatch.setattr(llm_mod, "get_llm", lambda usage=None: fake)
    return fake


NO_EVIDENCE = {"status": "abstained", "reason": "no_evidence", "answer": "I could not find evidence in the MSHA corpus ..."}


@pytest.mark.parametrize("q", ["hi", "Hello!", "thanks"])
def test_greetings_are_answered_directly_without_the_agent(env, q):
    a = FakeAgent(env.store, NO_EVIDENCE)
    r = general.answer(a, q, "s")
    assert r["status"] == "answered" and r["intent"] == "greeting" and not a.asked


@pytest.mark.parametrize("q", ["What can you help me with?", "what can you do", "Who are you?"])
def test_capability_questions_list_what_the_tool_does(env, q):
    a = FakeAgent(env.store, NO_EVIDENCE)
    r = general.answer(a, q, "s")
    assert r["intent"] == "capabilities" and "30 CFR" in r["answer"] and not a.asked


def test_a_grounded_answer_is_returned_unchanged(env, monkeypatch):
    fake = use_llm(monkeypatch, "should not be used")
    a = FakeAgent(env.store, {"status": "answered", "answer": "MSHA found ... [E1]."})
    r = general.answer(a, "What root causes did MSHA find for conveyor fatalities since 2018?", "s")
    assert r["answer"] == "MSHA found ... [E1]." and not r.get("general_knowledge") and not fake.calls


def test_general_safety_question_without_evidence_gets_a_labelled_general_answer(env, monkeypatch):
    fake = use_llm(monkeypatch, "Store cylinders upright and chained, away from heat.")
    a = FakeAgent(env.store, NO_EVIDENCE)
    r = general.answer(a, "How should I store compressed gas cylinders in a workshop?", "s")
    assert r["status"] == "answered" and r["general_knowledge"] is True and "cylinders upright" in r["answer"]
    assert r["grounded_attempt"]["reason"] == "no_evidence" and len(fake.calls) == 1


@pytest.mark.parametrize("q", ["Why did the fatal accident at Riverbend Sand and Gravel Mine happen?",
                               "What caused the fatality on April 15, 2024?"])
def test_a_named_incident_is_never_answered_from_general_knowledge(env, monkeypatch, q):
    fake = use_llm(monkeypatch, "It was caused by ...")
    a = FakeAgent(env.store, NO_EVIDENCE)
    r = general.answer(a, q, "s")
    assert r["status"] == "abstained" and not r.get("general_knowledge") and not fake.calls


@pytest.mark.parametrize("res", [{"status": "abstained", "rule": "A1", "answer": "no record for 2027"},
                                 {"status": "abstained", "reason": "report_not_published", "answer": "not published"},
                                 {"status": "abstained", "rule": "A4", "answer": "which incident?"},
                                 {"status": "refused", "rule": "R2", "answer": "no blame"}])
def test_no_fallback_after_a_refusal_or_an_event_specific_abstention(env, monkeypatch, res):
    fake = use_llm(monkeypatch, "anything")
    r = general.answer(FakeAgent(env.store, res), "What are common causes of haulage accidents?", "s")
    assert r["status"] == res["status"] and not fake.calls


def test_off_topic_questions_are_still_declined(env, monkeypatch):
    use_llm(monkeypatch, "OUT_OF_SCOPE")
    oos = {"status": "abstained", "rule": "OOS", "answer": "outside scope"}
    r = general.answer(FakeAgent(env.store, oos), "What is the best recipe for chocolate cake?", "s")
    assert r["status"] == "abstained" and r["reason"] == "out_of_scope" and not r.get("general_knowledge")


def test_a_general_answer_that_assigns_blame_is_refused(env, monkeypatch):
    use_llm(monkeypatch, "In such cases the operator is legally liable for the death.")
    r = general.answer(FakeAgent(env.store, NO_EVIDENCE), "Who is usually responsible when a conveyor guard is missing?", "s")
    assert r["status"] == "refused"


def test_the_grounded_abstention_is_not_fed_back_to_the_model(env, monkeypatch):
    """Regression: the question's own abstention ('I could not find evidence ...') was passed as history and copied into the answer."""
    q = "What is MSHA and what does it regulate?"
    env.store.save("s", "old", q, {"status": "abstained", "answer": "I could not find evidence in the MSHA corpus ..."})
    fake = use_llm(monkeypatch, "MSHA is the Mine Safety and Health Administration.")
    general.answer(FakeAgent(env.store, NO_EVIDENCE), q, "s")
    assert "I could not find evidence" not in fake.calls[0][-1]["content"]
