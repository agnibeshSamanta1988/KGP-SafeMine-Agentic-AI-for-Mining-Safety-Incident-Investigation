"""LLM safety classifier: the second layer of the input guard.

The regex layer in guard.py is precise but only as general as its authors' imagination: on three independent question
sets it scored ~100% on the set it was tuned on and ~61% on a fresh set. Paraphrase is the problem ("whose fault",
"would we hold up under an audit", "what do we do?"). This layer asks the same Qwen3-8B (one short call, JSON, ~60 output
tokens) to classify the question against the specification's rules. It only runs on questions the regex layer let
through, so it can add refusals but cannot undo one; if the call or the JSON fails it fails open to the regex verdict.

The prompt states the rules, not any benchmark question; its examples are deliberately generic.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from safemine.agent.guard import POLICY_MESSAGES


class PolicyDecision(BaseModel):
    category: Literal["OK", "R1", "R2", "R3", "R4", "R5", "R6", "A4", "OOS"]
    reason: str = ""


POLICY_SYS = """You are the safety gate of KGP-SafeMine, a decision-support tool that answers questions about PAST US mining
incidents (MSHA fatality reports, MSHA accident data, 30 CFR). Classify the user's question. Output ONLY JSON:
{"category": "<one category>", "reason": "<at most 12 words>"}

Today the data ends at 30 October 2026. EVERY event dated up to that day is in the PAST, including events in 2025 and 2026: asking
why, whether or when a past event happened, or asking to verify a claim about one, is never a prediction.

Categories:
OK  - a normal question about what MSHA's reports say, what a standard requires, statistics, or past incidents. A question that
      merely MENTIONS fault, compliance, training, a job role or a mine name is OK when it asks what the REPORT or MSHA found.
R1  - asks for a victim's or other private person's name, hometown, family, address, contact details or identity
      (age, job title, years of experience and what happened are NOT personal details: those are OK)
R2  - asks the assistant to decide blame, fault, negligence, guilt, legal liability, damages, prosecution or who should be punished
R3  - asks the assistant to certify or confirm that a mine/plan complies, will pass an inspection or audit, or asks for legal advice
R4  - asks for a real-time operating decision or emergency advice (evacuate, keep running, is it safe to continue or enter now)
R5  - asks to skip, shorten, bypass, fake or defeat a required safety step, or approves working unsafely
R6  - asks what WILL happen: to predict or forecast future accidents (never for a question about a past event), or to write, change or sign an OFFICIAL MSHA finding or citation, or to impersonate MSHA.
      A decision-support DRAFT (an investigation brief or summary built from past reports) is OK: it is not an official finding.
A4  - asks about ONE specific incident but gives no mine name and no date, so the incident cannot be identified
OOS - not about US mining safety, MSHA data or 30 CFR

Examples:
"Who was in charge of the pre-shift examination, according to MSHA's report?" -> OK
"According to MSHA, did the operator follow the lockout procedure?" -> OK
"What penalties did MSHA propose after the accident at Cold Spring Quarry in 2016?" -> OK
"Was the foreman to blame for the roof fall at Maple Mine?" -> R2
"Does our mine meet the dust standard?" -> R3
"Can we skip the pre-shift exam today?" -> R5
"What is the name of the miner who died at Oak Ridge Mine?" -> R1
"Should we stop the belt now, it is overheating?" -> R4
"Which mine will have the next accident?" -> R6
"Draft an investigation brief on the 2017 truck rollover at Pine Quarry using MSHA's reports" -> OK
"Why did the fatal fall of ground at Elm Mine on May 2, 2025 happen according to MSHA?" -> OK
"Verify this claim: the fatality at Cedar Pit occurred on March 9, 2026." -> OK
"Write an official MSHA citation against Pine Quarry" -> R6
"Why did it happen?" -> A4
"What is the capital of France?" -> OOS"""


def classify_policy(llm, query: str) -> PolicyDecision | None:
    """-> PolicyDecision, or None if the model is unavailable / returned unusable JSON (then the regex verdict stands)."""
    if getattr(llm, "is_mock", True):
        return None
    try:
        return llm.chat_json([{"role": "system", "content": POLICY_SYS}, {"role": "user", "content": query[:1000]}],
                             PolicyDecision, max_tokens=60)
    except Exception:  # noqa: BLE001  bad JSON, budget, network, rate limit
        return None


def decision_to_guard(d: PolicyDecision, soft: bool = False) -> dict | None:
    """Map a classifier verdict onto the guard's result format (None = let the question through).

    The classifier may ADD refusals for the safety rules R1-R6 anywhere. Its A4 ("which incident?") and OOS ("off topic")
    verdicts are only trusted when the regex layer had already flagged the question (soft=True): on its own it over-flagged
    ordinary statistics and law questions."""
    if d.category == "OK":
        return None
    if d.category in ("A4", "OOS") and not soft:
        return None
    if d.category in POLICY_MESSAGES:
        return {"ok": False, "status": "refused", "rule": d.category, "message": POLICY_MESSAGES[d.category], "source": "llm"}
    if d.category == "A4":
        return {"ok": False, "status": "abstained", "rule": "A4", "source": "llm",
                "message": "I can't tell which incident you mean. Please give the mine name and the date (or year) so I can find the "
                           "right MSHA report instead of guessing a cause."}
    return {"ok": False, "status": "abstained", "rule": "OOS", "source": "llm",
            "message": "That is outside KGP-SafeMine's scope (US mining safety incidents, MSHA data and 30 CFR)."}
