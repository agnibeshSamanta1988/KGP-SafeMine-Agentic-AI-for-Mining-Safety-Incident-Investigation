"""Step 4: chunk store -> BM25 index (+ dense matrix when an embedder is available).

Run:  .venv/bin/python -m safemine.ingest.build_indexes [--chunks data_processed/chunks.jsonl] [--tag section450]
"""
from __future__ import annotations

import argparse
import json
import pickle
import re
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from safemine import config

STOP = set("""a an the of and or to in on at for by with from as is was were be been being that this these those it its
he she him his her they them their we our you your i not no but if then than so such into over under after before while
during about which who whom what when where why how all any each other some there here also had has have do does did""".split())
TOKEN_RE = re.compile(r"\d+\.\d+(?:\([a-z0-9]+\))*|\d+\([a-z]\)|[a-z0-9]+(?:'[a-z]+)?")


def bm25_tokens(text: str) -> list[str]:
    toks = TOKEN_RE.findall(text.lower())
    out = []
    for t in toks:
        if t in STOP or len(t) < 2 and not t.isdigit():
            continue
        out.append(t)
        m = re.match(r"(\d+\.\d+)\(", t)  # "56.14211(c)" also indexed as "56.14211"
        if m:
            out.append(m.group(1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", default=str(config.CHUNKS_JSONL))
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-dense", action="store_true")
    a = ap.parse_args()
    suffix = f"_{a.tag}" if a.tag else ""
    chunks = [json.loads(l) for l in open(a.chunks)]
    ids = [c["chunk_id"] for c in chunks]
    bm = BM25Okapi([bm25_tokens(c["index_text"]) for c in chunks])
    bm_path = Path(str(config.BM25_PKL).replace(".pkl", f"{suffix}.pkl"))
    pickle.dump({"ids": ids, "bm25": bm, "chunks_path": str(a.chunks)}, open(bm_path, "wb"))
    print(f"BM25: {len(ids)} chunks -> {bm_path}")
    if a.no_dense:
        return
    try:
        from safemine.embeddings import Embedder
        emb = Embedder()
    except Exception as e:  # DenseUnavailable or model load error
        print(f"Dense index SKIPPED: {e}")
        return
    vecs = emb.encode([c["index_text"] for c in chunks])
    dn_path = Path(str(config.DENSE_NPY).replace(".npy", f"{suffix}.npy"))
    np.save(dn_path, vecs)
    json.dump({"ids": ids, "embedder": emb.name, "dim": int(vecs.shape[1])}, open(str(dn_path) + ".meta.json", "w"))
    print(f"Dense: {vecs.shape} via {emb.name} -> {dn_path}")


if __name__ == "__main__":
    main()
