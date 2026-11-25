"""Step 2: cleaned documents -> canonical chunk store (chunks.jsonl).

Strategies (for the Week-2 chunking experiment; pick by recall@10 on the dev set):
  section  (RECOMMENDED) structure-aware: one unit per report section / DISCUSSION sub-heading,
           packed by paragraph up to --size tokens; ROOT CAUSE -> one chunk per root-cause/corrective-action
           pair; ENFORCEMENT -> one chunk per citation/order; OVERVIEW+CONCLUSION -> one summary chunk.
  fixed    baseline: whole report flattened, sliding window of --size tokens with 15% overlap.

Every chunk gets a contextual header (date | classification | mine type/material | state | section)
that is prepended for indexing only (index_text). The plain `text` is what gets cited and quote-checked.

Run:  .venv/bin/python -m safemine.ingest.chunk --strategy section --size 450
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime

from safemine import config
from safemine.ingest.clean_reports import CFR_RE  # shared regex; docs now come from clean_pdfs.py

_tok = None


def n_tokens(text: str) -> int:
    """Token count with the embedding model's tokenizer (falls back to words*1.3)."""
    global _tok
    if _tok is None:
        try:
            from transformers import AutoTokenizer
            local = config.MODELS / "bge-small-en-v1.5"
            _tok = AutoTokenizer.from_pretrained(str(local) if local.exists() else "BAAI/bge-small-en-v1.5")
        except Exception:
            _tok = False
    if _tok:
        return len(_tok.encode(text, add_special_tokens=False))
    return int(len(text.split()) * 1.3)


SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[(\"])")


def pack(paras: list[str], size: int, overlap_sents: int = 1) -> list[str]:
    """Greedy paragraph packing; paragraphs longer than `size` are split on sentences."""
    units: list[str] = []
    for p in paras:
        if n_tokens(p) <= size:
            units.append(p)
        else:
            for sent in SENT_SPLIT.split(p):
                if n_tokens(sent) <= size:
                    units.append(sent)
                else:  # pathological run-on sentence / table row: hard split on words
                    w = sent.split()
                    step = max(20, int(size / 1.4))
                    units.extend(" ".join(w[k:k + step]) for k in range(0, len(w), step))
    chunks, cur, cur_n = [], [], 0
    for u in units:
        un = n_tokens(u)
        if cur and cur_n + un > size:
            chunks.append(" ".join(cur))
            tail = SENT_SPLIT.split(cur[-1])[-overlap_sents:] if overlap_sents else []
            cur, cur_n = list(tail), sum(n_tokens(t) for t in tail)
        cur.append(u)
        cur_n += un
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def iso_date(meta: dict) -> str | None:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta.get("date_iso") or ""):
        return meta["date_iso"]
    for key in ("accident_date_text", "incident_datetime"):
        v = meta.get(key)
        if not v:
            continue
        m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", v)
        if m:
            try:
                return datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
            except ValueError:
                pass
    return None


def long_date(iso: str | None) -> str | None:
    """2019-09-17 -> 'September 17, 2019' (questions write dates in words; BM25 cannot match those to ISO)."""
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
        return f"{d:%B} {d.day}, {d.year}"
    except (TypeError, ValueError):
        return None


def context_header(doc: dict, section: str, sub: str | None) -> str:
    # mine name + date in words: benchmark v2 queries name the incident ("fatality at American Eagle Mine on
    # September 17, 2019"); without them, short Root Cause / citation chunks never match and narrative chunks win
    m = doc["meta"]
    iso = iso_date(m)
    parts = [iso or str(doc["year"]), long_date(iso), m.get("mine_name"),
             m.get("classification") or m.get("classification_report"),
             " ".join(filter(None, [m.get("mine_type") or m.get("mine_category"), m.get("material") or m.get("commodity")])),
             m.get("state") or m.get("location"), doc["doc_type"].replace("_", " "),
             section.replace("_", " ").title() + (f" / {sub}" if sub else "")]
    return " | ".join(p for p in parts if p)


def make_chunk(doc, section, sub, text, i):
    m = doc["meta"]
    return {
        "chunk_id": f"{doc['doc_id']}::{section}::{i}",
        "doc_id": doc["doc_id"], "event_id": doc["event_id"], "doc_type": doc["doc_type"], "year": doc["year"],
        "date": iso_date(m), "section": section, "subheading": sub,
        "classification": m.get("classification") or m.get("classification_report"),
        "mine_type": m.get("mine_type") or m.get("mine_category"), "material": m.get("material") or m.get("commodity"),
        "state": m.get("state"), "mine_id": m.get("mine_id"), "mine_name": m.get("mine_name"),
        "cfr_ids": sorted({x.group(1).split("(")[0] for x in CFR_RE.finditer(text)}),
        "text": text,
        "index_text": context_header(doc, section, sub) + "\n" + text,
        "source_path": doc["source_path"],
        "n_tokens": n_tokens(text),
    }


def section_chunks(doc: dict, size: int) -> list[dict]:
    out, S = [], doc["sections"]
    flat = lambda name: [p for b in S.get(name, []) for p in b["paras"]]  # noqa: E731

    # 1) summary: OVERVIEW (+ CONCLUSION if it adds new text)
    ov, cc = " ".join(flat("OVERVIEW")), " ".join(flat("CONCLUSION"))
    if ov or cc:
        sw = lambda t: set(re.findall(r"[a-z]{4,}", t.lower()))  # noqa: E731
        same = ov and cc and len(sw(ov) & sw(cc)) / max(1, len(sw(cc))) > 0.7
        summary = ov if same else " ".join(filter(None, [ov, cc]))
        for i, t in enumerate(pack([summary], size)):
            out.append(make_chunk(doc, "SUMMARY", None, t, i))

    # 2) root causes: one atomic chunk per pair
    if doc.get("root_causes"):
        for i, rc in enumerate(doc["root_causes"]):
            t = f"Root Cause: {rc['root_cause']} Corrective Action: {rc['corrective_action']}"
            pieces = pack([t], size) if n_tokens(t) > size else [t]   # a few pairs run on into later text
            for j, piece in enumerate(pieces):
                out.append(make_chunk(doc, "ROOT_CAUSE", None, piece, f"{i}" if j == 0 else f"{i}.{j}"))
    elif S.get("ROOT_CAUSE"):
        for i, t in enumerate(pack(flat("ROOT_CAUSE"), size)):
            out.append(make_chunk(doc, "ROOT_CAUSE", None, t, i))

    # 3) enforcement: one chunk per numbered citation / order
    if S.get("ENFORCEMENT"):
        items, cur = [], []
        for p in flat("ENFORCEMENT"):
            if re.match(r"^(\d+\.|[A-Z]\.|Order No|Citation No|•)|^(A|An) (104|103|107|110)", p) and cur:
                items.append(" ".join(cur))
                cur = []
            cur.append(p)
        if cur:
            items.append(" ".join(cur))
        i = 0
        for it in items:
            for t in pack([it], size):
                out.append(make_chunk(doc, "ENFORCEMENT", None, t, i))
                i += 1

    # 4) narrative sections: pack by paragraph inside (sub)section; merge tiny sub-sections forward
    for name in ("GENERAL_INFORMATION", "DESCRIPTION", "INVESTIGATION", "RESCUE_RECOVERY", "DISCUSSION",
                 "TRAINING_EXPERIENCE", "SUPPLEMENT", "ALERT_SUMMARY", "BEST_PRACTICES", "PRELIMINARY"):
        blocks = S.get(name, [])
        i, carry = 0, None
        for b in blocks:
            paras = [p for p in b["paras"] if p]
            if not paras:
                continue
            sub = b["subheading"]
            if carry:  # tiny previous sub-section (e.g. "Weather") is glued onto this one
                paras = [f"{carry[0]}: " + " ".join(carry[1])] + ([f"{sub}: " + paras[0]] + paras[1:] if sub else paras)
                sub = f"{carry[0]} + {sub}" if sub else carry[0]
                carry = None
            if n_tokens(" ".join(paras)) < 60 and b is not blocks[-1]:
                carry = (sub or "Note", paras)
                continue
            if name == "BEST_PRACTICES":
                paras = ["Best practices: " + " ".join(paras)]
            for t in pack(paras, size):
                out.append(make_chunk(doc, name, sub, t, i))
                i += 1
        if carry:
            out.append(make_chunk(doc, name, carry[0], " ".join(carry[1]), i))
    return out


def fixed_chunks(doc: dict, size: int) -> list[dict]:
    text = " ".join(p for s in doc["sections"].values() for b in s for p in b["paras"])
    words = text.split()
    step_words = max(50, int(size / 1.3 * 0.85))
    win_words = int(size / 1.3)
    out = []
    for i, start in enumerate(range(0, max(1, len(words)), step_words)):
        t = " ".join(words[start:start + win_words])
        if t:
            out.append(make_chunk(doc, "FIXED", None, t, i))
        if start + win_words >= len(words):
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", choices=["section", "fixed"], default="section")
    ap.add_argument("--size", type=int, default=450)
    ap.add_argument("--out", default=str(config.CHUNKS_JSONL))
    a = ap.parse_args()
    n, by_sec, toks = 0, {}, []
    with open(a.out, "w") as f:
        for line in open(config.DOCS_JSONL):
            doc = json.loads(line)
            chunks = section_chunks(doc, a.size) if a.strategy == "section" else fixed_chunks(doc, a.size)
            for c in chunks:
                f.write(json.dumps(c) + "\n")
                n += 1
                by_sec[c["section"]] = by_sec.get(c["section"], 0) + 1
                toks.append(c["n_tokens"])
    toks.sort()
    print(f"{a.strategy}/{a.size}: {n} chunks, tokens median={toks[len(toks)//2]} p95={toks[int(len(toks)*.95)]} max={toks[-1]}")
    print(dict(sorted(by_sec.items(), key=lambda x: -x[1])))


if __name__ == "__main__":
    main()
