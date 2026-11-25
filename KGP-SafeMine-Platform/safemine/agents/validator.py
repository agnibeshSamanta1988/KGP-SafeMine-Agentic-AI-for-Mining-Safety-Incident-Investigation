"""ValidatorAgent: evidence validation. Nothing reaches the user that this agent has not checked against the cited evidence.

Checks (deterministic, no model): every [E#] exists; quotes are verbatim; numbers, dates and CFR sections appear in the cited evidence;
factual sentences are cited (all from tools.verify_claims). On top of that this agent adds:
  * a claim map: each factual sentence -> its citations -> verdict -> source provenance (event, chunk, report file)
  * a grounding score per sentence (share of its content words found in the cited evidence): a SOFT signal that catches a cited but
    unrelated sentence which has no number or quote to check. It informs the claim map; it gates acceptance only when
    AGENT_STRICT_GROUNDING is set (default off, so existing behaviour and benchmark results are unchanged).
"""
from __future__ import annotations

import re

from safemine import config
from safemine.agent import orchestrator as O
from safemine.agents.base import BaseAgent
from safemine.tools.verify_claims import CITE, CLAIM_Q, split_sentences, verify_claims

STOP = set("""the and for with from that this these those was were are been being has have had not but its their his her they them
into than then also which who whom while during after before when where what will would could should may might can per via over under
about between among such other some any all each more most only very mine miner miners accident incident report reports evidence""".split())


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def content_words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z][a-z0-9]+", text.lower()) if len(w) > 3 and w not in STOP}


def grounding_score(sentence: str, evidence_text: str) -> float:
    """Share (0..1) of the sentence's content words that occur in the evidence it cites. 1.0 for a sentence with no content words."""
    sw = content_words(CITE.sub("", sentence))
    if not sw:
        return 1.0
    return round(len(sw & content_words(evidence_text)) / len(sw), 3)


WEAK = 0.5   # below this, a cited sentence is flagged "weak support" in the claim map


class ValidatorAgent(BaseAgent):
    name = "validator"
    description = "Citation repair, claim-by-claim verification, grounding score, hallucination stripping, claim map"

    def validate(self, ctx, draft) -> dict:
        """Repair citations, then verify every claim of the draft against the evidence pack."""
        draft.answer = draft.answer.replace("\\n", "\n")  # some models double-escape newlines inside JSON
        draft.answer, n_fixed = O.repair_citations(draft.answer, ctx.pack)
        if n_fixed:
            ctx.log("citations_repaired", n=n_fixed)
        ver = verify_claims(draft.answer, ctx.evidence_map(), question=ctx.query)
        if config.STRICT_GROUNDING:   # optional: weakly grounded cited sentences count as unsupported
            ev = ctx.evidence_map()
            for r in ver["sentences"]:
                if r["status"] == "supported" and r.get("citations"):
                    g = grounding_score(r["sentence"], " ".join(ev.get(c, "") for c in r["citations"]))
                    if g < config.GROUNDING_MIN:
                        r["status"], r["issues"] = "unsupported", [f"weak grounding {g:.2f} in the cited evidence"]
                        ver["unsupported"].append(r)
                        ver["n_supported"] -= 1
            ver["support_ratio"] = round(ver["n_supported"] / ver["n_factual"], 3) if ver["n_factual"] else 0.0
        if ctx.wrong_dates and not CLAIM_Q.search(ctx.query):
            # (not for a claim-check question: "Verify this claim: ... on July 17, 2025" is answered by restating the claim, then contradicting it)
            # MSHA's record contradicts a date the question gave: no sentence may state that date as the event's date, whatever the model or the
            # Critic says (a wrong Critic once talked the writer into "on May 19, 2001" for an event dated May 19, 2026). Sentences that point out
            # the mismatch are fine.
            cue = re.compile(r"\b(?:no event|differs?|does not match|doesn't match|not match|the question|question assumes|not on)\b", re.I)
            for r in ver["sentences"]:
                bad = next((d for d in ctx.wrong_dates if d in r["sentence"]), None)
                if bad and r["status"] == "supported" and not cue.search(r["sentence"]):
                    r["status"], r["issues"] = "unsupported", [f"date {bad} is the question's date, not the date of MSHA's record"]
                    ver["unsupported"].append(r)
                    ver["n_supported"] -= 1
            ver["support_ratio"] = round(ver["n_supported"] / ver["n_factual"], 3) if ver["n_factual"] else 0.0
        ctx.log("verify", round=ctx.rounds, support_ratio=ver["support_ratio"], unsupported=len(ver["unsupported"]))
        return ver

    def salvage(self, ctx) -> None:
        """After the Critic loop did not accept: keep the best verified draft, or the verified remainder for open-ended questions."""
        log, plan, best = ctx.log, ctx.plan, ctx.best
        if ctx.decision != "accept" and best is not None and best[0] >= 0.8:
            log("best_draft_returned", support_ratio=best[0], last_decision=ctx.decision)
            _, ctx.draft, ctx.ver = best
            ctx.decision, ctx.caveat = "accept", True
        elif ctx.decision != "accept" and best is not None and plan.intent in O.OPEN_ENDED_INTENTS:
            # An open-ended question rarely needs every sentence: if what is left after removing the unverifiable sentences is itself
            # well supported and substantial, return that remainder. Questions about ONE incident stay conservative (they abstain).
            kept_text, n_cut = O.strip_unverifiable(best[1].answer, best[2])
            if n_cut:
                rem = verify_claims(kept_text, ctx.evidence_map(), question=ctx.query)
                if rem["n_factual"] >= 2 and rem["support_ratio"] >= 0.9:
                    log("verified_remainder_returned", removed=n_cut, remaining=rem["n_factual"], support_ratio=rem["support_ratio"])
                    best[1].answer, ctx.ver = kept_text, rem
                    ctx.draft, ctx.decision, ctx.caveat = best[1], "accept", True

    def sanitize(self, ctx) -> int:
        """Remove sentences whose regulation number, quotation, figure or date is not in the cited evidence."""
        ctx.draft.answer, n = O.strip_unverifiable(ctx.draft.answer, ctx.ver)
        ctx.removed = n
        if n:
            ctx.log("unverifiable_removed", n=n)
        return n

    def claim_map(self, ctx, answer: str) -> dict:
        """Claim-by-claim record of the FINAL answer: which evidence each claim rests on, its verdict, and where that evidence came from."""
        ev_text = ctx.evidence_map()
        by_id = {e["id"]: e for e in ctx.pack}
        # only the writer's claims are mapped: notes the system itself appended (italic notices, premise lines from the MSHA record, the
        # injection notice) are not model claims
        own = {ln.strip() for ln in ctx.premise}
        body = "\n".join(ln for ln in answer.split("\n")
                         if not re.fullmatch(r"\s*\*[^*].*\*\s*", ln) and ln.strip() not in own and not ln.startswith("(Instructions embedded"))
        final = verify_claims(body, ev_text, question=ctx.query)
        claims, weak, uncited = [], 0, 0
        for r in final["sentences"]:
            if r["status"] == "no_claim":
                continue
            cites = r.get("citations", [])
            g = grounding_score(r["sentence"], " ".join(ev_text.get(c, "") for c in cites)) if cites else 0.0
            if not cites:
                uncited += 1
            is_weak = bool(cites) and g < WEAK and r["status"] == "supported"
            weak += is_weak
            claims.append({"sentence": r["sentence"][:300], "status": r["status"], "citations": cites, "issues": r.get("issues", []),
                           "grounding": g, "weak_support": is_weak,
                           "sources": [{"id": c, "kind": by_id[c].get("kind"), "label": by_id[c].get("label"), "event_id": by_id[c].get("event_id"),
                                        "chunk_id": by_id[c].get("chunk_id"), "source_path": by_id[c].get("source_path")} for c in cites if c in by_id]})
        n = len(claims)
        return {"claims": claims,
                "summary": {"claims": n, "supported": sum(c["status"] == "supported" for c in claims), "unsupported": sum(c["status"] == "unsupported" for c in claims),
                            "uncited": uncited, "weak_support": weak, "removed": ctx.removed, "rounds": ctx.rounds + 1,
                            "support_ratio": final["support_ratio"],
                            "traceability": round((n - uncited) / n, 3) if n else 0.0,
                            "mean_grounding": round(sum(c["grounding"] for c in claims) / n, 3) if n else 0.0}}
