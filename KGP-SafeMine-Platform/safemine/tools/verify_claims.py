"""verify_claims: deterministic check of a draft answer against its evidence pack.

For every sentence of the draft:
  * citation check  - each [E#] must exist in the evidence pack; sentences with facts need >= 1 citation
  * quote check     - text in "double quotes" must appear verbatim (whitespace-normalised) in a cited chunk
  * number check    - numbers (ages, counts, feet, years ...) must appear in the cited evidence / tool results
  * CFR check       - every 30 CFR section mentioned must appear in cited evidence or a cfr_lookup result
  * date check      - Month D, YYYY dates must appear in cited evidence
Returns per-sentence verdicts + support_ratio, used by the Critic and logged for the failure taxonomy.
"""
from __future__ import annotations

import re
from datetime import datetime

CITE = re.compile(r"\[(E\d+)\]")
NUM = re.compile(r"(?<![\w.])(\d+(?:,\d{3})*(?:\.\d+)?)(?![\w.]*\])")
CFR = re.compile(r"\b(\d{1,3}\.\d{1,5})(?:\([a-z0-9]+\))*")
CFR_PART = re.compile(r"(?:CFR|§|\bPart)\s*§?\s*(\d{1,3})(?![\d.])")   # "30 CFR § 56", "Part 75" (no section)
DATE = re.compile(r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}")
_NEG_WORD = re.compile(r"\b(not|no|cannot|insufficient|missing|unavailable|unable)\b|n't\b", re.I)
_EVID_WORD = re.compile(r"\b(evidence|documents?|reports?|records?|sources?|provided|mention\w*|available|context|information)\b", re.I)


# "No details on the truck's hydraulic system." / "Cause not stated." : a gap in the sources (what the brief is still missing), not a fact about
# the world. Deliberately narrow: "No injuries were reported" is a factual claim and is NOT exempt.
_GAP = re.compile(r"^\W*(?:no|not|without)\s+(?:further\s+|additional\s+|specific\s+)?(?:details?|information|data|evidence|mention|records?|description|documentation)\b"
                  r"|\b(?:not|never)\s+(?:stated|provided|available|specified|described|documented|given|known)\b"
                  r"|\b(?:is|was|are|were)\s+(?:unknown|unclear|unspecified)\b", re.I)


class _Negative:
    """A statement about the evidence itself ("... is not provided in the evidence", "the evidence does not say"):
    a negation word plus a reference to the evidence, in either order. Only applied to sentences with no citation."""

    @staticmethod
    def search(text: str) -> bool:
        return bool((_NEG_WORD.search(text) and _EVID_WORD.search(text)) or _GAP.search(text))


NEGATIVE = _Negative()
QUOTE = re.compile(r"[\"“]([^\"”]{8,})[\"”]")
SQUOTE = re.compile(r"(?<![\w])'(.{25,}?)'(?=[\s.,;:)\]]|$)")   # 'a long passage' (not an apostrophe)


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace("’", "'").replace("“", '"').replace("”", '"')).strip().lower()


def _num_in(n: str, text: str) -> bool:
    """True if the number occurs in the text as a WHOLE number: "20" must not match inside "2019" or "56.14211" (the old substring test
    accepted an invented "20 years" because the evidence label contained the year 2019)."""
    return bool(re.search(rf"(?<![\d.]){re.escape(n.replace(',', ''))}(?!\d)", text.replace(",", "")))


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\-•*])|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 3]


# a sentence that explicitly contrasts the record with what the question assumed may quote the question's own date or figure
MISMATCH = re.compile(r"\b(?:no event on|there is no (?:event|record|fatality|incident)|does(?: not|n't) match|differs? from|"
                      r"the question (?:gives|states|says|assumes|asks)|not on that date)\b", re.I)
CLAIM_Q = re.compile(r"\b(?:claims?|verify|verified|fact[- ]?check|is it (?:true|correct|accurate|supported)|true or false|supported|contradicted)\b", re.I)
VERDICT = re.compile(r"\b(claim|contradict\w*|support\w*|partial\w*|not|rather than|instead of|differs?|incorrect|wrong)\b", re.I)


def verify_claims(draft: str, evidence: dict[str, str], tool_facts: str = "", question: str = "") -> dict:
    """evidence: {"E1": chunk_text, ...}; tool_facts: serialized accident_stats / cfr_lookup outputs.
    question: the user's question. In a verdict sentence ("The claim ... on July 17, 2025 is Contradicted") the numbers
    and dates that merely restate the user's own claim are not facts to verify; the verdict itself is checked by its cite."""
    results, n_fact, n_ok = [], 0, 0
    facts_norm = _norm(tool_facts)
    q_norm = _norm(question)
    all_ev = " ".join(_norm(v) for v in evidence.values())   # every evidence item, for uncited sentences that name a regulation
    for s in split_sentences(draft):
        if s.lstrip().startswith(">"):   # the user's own description quoted back (new-incident brief): not a claim
            results.append({"sentence": s, "status": "no_claim"})
            continue
        cites = CITE.findall(s)
        body = CITE.sub("", s)
        issues = []
        bad = [c for c in cites if c not in evidence]
        if bad:
            issues.append(f"unknown evidence id(s) {bad}")
        ev = " ".join(_norm(evidence[c]) for c in cites if c in evidence) + " " + facts_norm
        cfrs = CFR.findall(body) + [f"part {p}" for p in CFR_PART.findall(body) if p != "30"]
        # numbers worth checking: 2+ digits (ages, feet, counts, years); skip list markers and CFR ids
        nums = [n for n in NUM.findall(CFR.sub("", re.sub(r"30\s*C\.?F\.?R\.?", "", re.sub(r"^\s*\d+[.)]\s", "", body)))) if len(n.replace(",", "")) >= 2]
        dates = DATE.findall(body)
        quotes = QUOTE.findall(body) + SQUOTE.findall(body)
        is_fact = bool(cites or nums or cfrs or dates or quotes)
        plain = body.strip().lstrip("-*•#> ").strip()
        is_leadin = body.rstrip().endswith(":")   # (headings are < 8 words, so they never reach the check below)
        # lead-in line ("The root causes ... since 2018 include:") only restates the question and introduces a list
        if is_fact and not cites and not quotes and body.rstrip().endswith(":"):
            is_fact = False
        # plain prose with no citation is still a claim ("Corrective actions included ..."): it must be cited
        elif not is_fact and not is_leadin and not NEGATIVE.search(plain) and len(plain.split()) >= 8:
            is_fact = True
        # an honest "the evidence does not say X" is a statement about the evidence, not a claim to be cited; its
        # numbers/dates (restating the question) are not facts either
        # ...but a regulation number inside such a statement must still exist in the evidence: "the evidence does not describe the
        # procedures required by 30 CFR 48.112" invents 48.112 just as much as a positive claim would
        if is_fact and not cites and not quotes and NEGATIVE.search(plain) and all(c.startswith("part ") or c in all_ev for c in cfrs):
            is_fact = False
        if not is_fact:
            results.append({"sentence": s, "status": "no_claim"})
            continue
        n_fact += 1
        if not cites and not facts_norm:
            issues.append("factual sentence without citation")
        # A verdict sentence of a CLAIM-CHECK question may restate the user's own figures ("The claim ... on July 17, 2025 is Contradicted").
        # Any other question may not: a sentence that merely contains the word "support" must not get its date or numbers for free (it let
        # "on May 19, 2001" through, the question's wrong date, when the record says 2026).
        restating = bool(q_norm) and ((bool(CLAIM_Q.search(q_norm)) and bool(VERDICT.search(body))) or bool(MISMATCH.search(body)))
        for q in quotes:
            # a verdict sentence may quote the user's own claim back ("The claim '...' is Contradicted"): that is not a
            # passage attributed to the evidence
            if _norm(q) not in ev and not (restating and _norm(q) in q_norm):
                issues.append(f"quote not found verbatim: {q[:60]!r}")
        for n in nums:
            if not _num_in(n, ev) and not (restating and _num_in(n, q_norm)):
                issues.append(f"number {n} not in cited evidence")
        for c in cfrs:
            if c.startswith("part "):
                if not re.search(rf"(part|cfr|§)\s*§?\s*{c[5:]}\b|\b{c[5:]}\.\d", ev):
                    issues.append(f"CFR {c} not in cited evidence")
            elif c not in ev:
                issues.append(f"CFR {c} not in cited evidence")
        for d in dates:
            try:
                iso = datetime.strptime(re.sub(r"\s+", " ", d), "%B %d, %Y").date().isoformat()
            except ValueError:
                iso = "-"
            if _norm(d) not in ev and iso not in ev and not (restating and _norm(d) in q_norm):
                issues.append(f"date {d} not in cited evidence")
        ok = not issues
        n_ok += ok
        results.append({"sentence": s, "citations": cites, "status": "supported" if ok else "unsupported", "issues": issues})
    ratio = (n_ok / n_fact) if n_fact else 0.0
    return {"support_ratio": round(ratio, 3), "n_factual": n_fact, "n_supported": n_ok,
            "unsupported": [r for r in results if r["status"] == "unsupported"], "sentences": results}
