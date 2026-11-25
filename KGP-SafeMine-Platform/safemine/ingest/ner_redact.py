"""Name-recognition (NER) pass over the chunk store: the safety net for names the pattern-based redaction missed.

Why: the pattern redaction (clean_pdfs.py / redact.py) knows "Name - Plant Manager", "Mr. Name", "First I. Surname", ... but not
"accompanied by crew members Christopher Franklin and James Eplin": plain first+last names without a title. A person-name
model finds those regardless of phrasing. An answer produced from an unredacted chunk leaked two crew members' names.

Two stages, so the slow part can be stopped and resumed:

  detect   run a token-classification model (dslim/distilbert-NER) over every chunk and store the PERSON spans
             python -m safemine.ingest.ner_redact detect          -> data_processed/ner_detections.jsonl   (about 30-40 min on CPU)
  apply    filter the spans (confidence, mine names, job words), replace them with [PERSON] in chunk `text` and `index_text`,
           rebuild BM25, re-embed ONLY the changed chunks (hosted embeddings), write the names to _restricted/names_ner.json
             python -m safemine.ingest.ner_redact apply [--dry-run]

The model's mistakes cost recall of ordinary words (an over-redacted word is a hole in an answer), so `apply --dry-run` prints
a random sample of what would be replaced for a human to eyeball before anything is changed.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from safemine import config

DETECTIONS = config.OUT / "ner_detections.jsonl"
NAMES_OUT = config.REDACTION_DIR / "names_ner.json"
MODEL = "dslim/distilbert-NER"
MIN_SCORE = 0.85
# capitalised words the model sometimes tags as a person that are mining vocabulary, roles, places or months
NOT_A_NAME = {w.lower() for w in """Out Area Mine Mines Plant Quarry Pit Safety Health Foreman Supervisor Manager Superintendent Inspector
Investigator Operator Miner Victim Coroner Sheriff Deputy Chief Director Engineer Electrician Mechanic Welder Driver Laborer Crew District
Office Department Administration Federal State County Section Entry Panel Face Rib Roof Belt Shaft Slope Level Unit Shift Report Order
Citation Appendix Figure Table Exhibit January February March April May June July August September October November December Monday
Tuesday Wednesday Thursday Friday Saturday Sunday Coal Metal Sand Gravel Stone Cement Lime Gold Silver Copper Iron
Haul Dispatcher Outby Loader Longwall Scoop Crusher Blaster Driller Pillar Free Short Person Truck Dozer Excavator Shuttle""".split()}


def detect(args) -> None:
    import torch
    from transformers import pipeline
    torch.set_num_threads(os.cpu_count() or 4)
    chunks = [json.loads(line) for line in open(config.CHUNKS_JSONL, encoding="utf-8")]
    done = set()
    if DETECTIONS.exists():
        done = {json.loads(line)["chunk_id"] for line in open(DETECTIONS, encoding="utf-8")}
    todo = sorted((c for c in chunks if c["chunk_id"] not in done), key=lambda c: len(c["text"]))   # similar lengths batch better
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(chunks)} chunks, {len(done)} already detected, {len(todo)} to do | model {MODEL}", flush=True)
    ner = pipeline("token-classification", model=MODEL, aggregation_strategy="simple", device=-1, stride=32)
    t0 = time.time()
    with open(DETECTIONS, "a", encoding="utf-8") as f:
        for i in range(0, len(todo), 32):
            batch = todo[i:i + 32]
            res = ner([c["text"] for c in batch], batch_size=32)
            for c, ents in zip(batch, res):
                spans = [[int(e["start"]), int(e["end"]), round(float(e["score"]), 3)] for e in ents if e["entity_group"] == "PER"]
                f.write(json.dumps({"chunk_id": c["chunk_id"], "spans": spans}) + "\n")
            f.flush()
            if (i // 32) % 10 == 0:
                rate = (i + len(batch)) / (time.time() - t0)
                print(f"  {i + len(batch)}/{len(todo)} chunks  {rate:.1f}/s  eta {(len(todo) - i - len(batch)) / max(rate, 0.1) / 60:.0f} min", flush=True)
    print("detect done", flush=True)


VOCAB_LOWERCASE_COUNT = 400    # "haul" 2,094 times, "loader" 1,683, "outby" 785 ... but "means" 235, "north" 320 stay candidates


def _keep(surface: str, score: float, mine_name: str | None, lowfreq: dict | None = None) -> bool:
    if score < MIN_SCORE or len(surface) < 4 or re.search(r"[\[\]\d]", surface):
        return False
    if lowfreq is not None and " " not in surface and lowfreq.get(surface.lower(), 0) >= VOCAB_LOWERCASE_COUNT:
        return False                                   # a job, machine or place word that happens to be capitalised
    words = surface.split()
    if not all(w[:1].isupper() for w in words):
        return False
    if len(words) == 1 and score < 0.9:
        return False
    low = [w.lower().strip(".,'") for w in words]
    if any(w in NOT_A_NAME for w in low):
        return False
    mine_tokens = set(re.findall(r"[a-z]{3,}", (mine_name or "").lower()))
    if mine_tokens and all(w in mine_tokens for w in low):
        return False                                   # a word of the mine's own name, not a person
    return True


def plan(chunks: list[dict], det: dict) -> tuple[dict, list[tuple[str, str]]]:
    """-> ({chunk_id: [(start, end), ...]}, [(surface, chunk_id), ...]) after filtering."""
    from collections import Counter
    lowfreq = Counter(w for c in chunks for w in re.findall(r"\b[a-z]{3,}\b", c["text"]))
    spans_by, found = {}, []
    for c in chunks:
        text, keep = c["text"], []
        for s, e, sc in det.get(c["chunk_id"], []):
            # the model labels word pieces ("Star|cher", "Electric|ian"): widen the span to whole words BEFORE judging it, so a
            # surname is redacted completely and "Electrician" is recognised as a job word instead of a person
            while s > 0 and text[s - 1].isalpha():
                s -= 1
            while e < len(text) and text[e].isalpha():
                e += 1
            surface = text[s:e]
            if s > 0 and text[s - 1] == "[":               # already a placeholder: "[PERSON-3]", "[name withheld]"
                continue
            if _keep(surface, sc, c.get("mine_name"), lowfreq):
                keep.append((s, e, surface))
        merged = []
        for s, e, surface in sorted(set(keep)):
            if merged and s <= merged[-1][1]:                       # overlapping / touching spans become one
                merged[-1] = (merged[-1][0], max(e, merged[-1][1]), text[merged[-1][0]:max(e, merged[-1][1])])
            else:
                merged.append((s, e, surface))
        if merged:
            spans_by[c["chunk_id"]] = [(s, e) for s, e, _ in merged]
            found.extend((surface, c["chunk_id"]) for _, _, surface in merged)
    return spans_by, found


def apply(args) -> None:
    chunks = [json.loads(line) for line in open(config.CHUNKS_JSONL, encoding="utf-8")]
    det = {}
    for line in open(DETECTIONS, encoding="utf-8"):
        d = json.loads(line)
        det[d["chunk_id"]] = d["spans"]
    missing = sum(1 for c in chunks if c["chunk_id"] not in det)
    if missing:
        sys.exit(f"{missing} chunks have no detection yet: run `detect` to completion first")
    spans_by, found = plan(chunks, det)
    surfaces = sorted({s for s, _ in found})
    print(f"{len(found)} person mentions in {len(spans_by)} chunks; {len(surfaces)} distinct strings")
    rnd = random.Random(1)
    print("random sample of what would be replaced (check for false positives):")
    for s, cid in rnd.sample(found, min(40, len(found))):
        print(f"   {s!r:38} {cid.split('::')[1]}")
    if args.dry_run:
        return

    old_ids = {c["chunk_id"]: c for c in chunks}
    changed = []
    for c in chunks:
        sp = spans_by.get(c["chunk_id"])
        if not sp:
            continue
        text = c["text"]
        for s, e in sorted(sp, reverse=True):
            text = text[:s] + "[PERSON]" + text[e:]
        header = c["index_text"][: len(c["index_text"]) - len(c["text"]) - 1]
        c["text"], c["index_text"] = text, header + "\n" + text
        changed.append(c["chunk_id"])
    # names for the answer-time Output Filter
    config.REDACTION_DIR.mkdir(parents=True, exist_ok=True)
    NAMES_OUT.write_text(json.dumps({"ner": {"victims": [], "people": surfaces}}, indent=1), encoding="utf-8")
    with open(config.CHUNKS_JSONL, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c) + "\n")
    print(f"chunks.jsonl rewritten: {len(changed)} chunks changed; names -> {NAMES_OUT.name}")

    # indexes: BM25 is cheap to rebuild; dense vectors are re-computed only for the changed chunks
    from safemine.ingest.build_indexes import main as build_indexes
    sys.argv = ["build_indexes", "--no-dense"]
    build_indexes()
    meta_p = Path(str(config.DENSE_NPY) + ".meta.json")
    meta = json.load(open(meta_p, encoding="utf-8"))
    ids = meta["ids"]
    dense = np.load(config.DENSE_NPY)
    pos = {cid: i for i, cid in enumerate(ids)}
    from safemine.embeddings import Embedder
    emb = Embedder()
    todo = [cid for cid in changed if cid in pos]
    print(f"re-embedding {len(todo)} changed chunks via {emb.name} ...", flush=True)
    for i in range(0, len(todo), 400):
        part = todo[i:i + 400]
        vecs = emb.encode([old_ids[cid]["index_text"] for cid in part])
        for cid, v in zip(part, vecs):
            dense[pos[cid]] = v
        print(f"  {min(i + 400, len(todo))}/{len(todo)}", flush=True)
    np.save(config.DENSE_NPY, dense)
    print("dense.npy updated; done")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["detect", "apply"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    detect(a) if a.stage == "detect" else apply(a)


if __name__ == "__main__":
    main()
