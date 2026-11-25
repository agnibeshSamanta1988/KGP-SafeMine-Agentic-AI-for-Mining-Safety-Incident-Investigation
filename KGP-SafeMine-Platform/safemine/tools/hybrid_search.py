"""hybrid_search: BM25 top-30 + dense top-30 -> RRF -> MiniLM cross-encoder (top-20) -> evidence selection.

Evidence selection: relevance order, max `per_event` chunks per incident (diversity), near-duplicate removal,
6-8 chunks returned. Retrieved text is DATA, never instructions (it is wrapped as such by the agent).
"""
from __future__ import annotations

import json
import pickle
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
from pydantic import BaseModel, Field

from safemine import config
from safemine.ingest.build_indexes import bm25_tokens


class SearchArgs(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    year_from: Optional[int] = Field(None, ge=1995, le=2030)
    year_to: Optional[int] = Field(None, ge=1995, le=2030)
    classification: Optional[str] = None          # e.g. "Powered Haulage"
    mine_type: Optional[str] = None               # Surface / Underground / Facility
    state: Optional[str] = None
    sections: Optional[list[str]] = None          # e.g. ["ROOT_CAUSE","ENFORCEMENT"]
    doc_types: Optional[list[str]] = None         # final_report / fatality_alert / preliminary_report
    event_id: Optional[str] = None
    k: int = Field(8, ge=1, le=12)
    # pattern questions ("root causes of conveyor fatalities since 2018") want breadth: one chunk per incident and no
    # "single-incident" cap lift, so the 8-12 evidence chunks span as many incidents as possible
    diverse: bool = False


def resolve_chunks_path(recorded: str, out_dir: Path) -> Path:
    r"""Where the chunk file is on THIS machine. The index records the path it was built with, which can be a Windows path
    (F:\...\chunks.jsonl) while the app runs on Linux in a container: there Path().name returns the whole string (backslashes are not
    separators), so the file name is taken with both kinds of separator. The canonical copy next to the index wins when it exists."""
    import re
    name = re.split(r"[\\/]", str(recorded))[-1] or "chunks.jsonl"
    here = Path(out_dir) / name
    if here.exists():
        return here
    cp = Path(recorded)
    return cp if cp.exists() else here


class Retriever:
    def __init__(self, tag: str = "", use_dense: bool = True, use_rerank: bool = True, rerank_mode: str | None = None):
        # rerank_mode: "fuse" (RRF of retrieval rank + cross-encoder rank, default) | "replace" (sort by CE score only)
        # Proxy eval: replace R@1 0.717 vs fuse 0.850 vs none 0.875 -> decide on the golden set.
        import os
        self.rerank_mode = rerank_mode or os.getenv("RERANK_MODE", "fuse")
        suffix = f"_{tag}" if tag else ""
        bm = pickle.load(open(str(config.BM25_PKL).replace(".pkl", f"{suffix}.pkl"), "rb"))
        self.ids, self.bm25 = bm["ids"], bm["bm25"]
        cp = resolve_chunks_path(bm["chunks_path"], config.OUT)
        self.chunks = {c["chunk_id"]: c for c in map(json.loads, open(cp))}
        self.rows = [self.chunks[i] for i in self.ids]
        self.dense = None
        dn = Path(str(config.DENSE_NPY).replace(".npy", f"{suffix}.npy"))
        if use_dense and dn.exists():
            from safemine.embeddings import Embedder
            self.dense = np.load(dn)
            self.embedder = Embedder()
        self.reranker = None
        if use_rerank:
            from sentence_transformers import CrossEncoder
            local = config.MODELS / "ms-marco-MiniLM-L6-v2"   # `make models`; else fetched from Hugging Face once
            self.reranker = CrossEncoder(str(local) if local.exists() else "cross-encoder/ms-marco-MiniLM-L6-v2", device="cpu")

    # ---------------------------------------------------------- filters
    def _mask(self, a: SearchArgs) -> np.ndarray:
        def ok(c):
            if a.year_from and c["year"] < a.year_from:
                return False
            if a.year_to and c["year"] > a.year_to:
                return False
            if a.classification and not re.search(rf"(?<!non-){re.escape(a.classification.lower())}", (c.get("classification") or "").lower()):
                return False
            if a.mine_type and a.mine_type.lower() not in (c.get("mine_type") or "").lower():
                return False
            if a.state and a.state.lower() not in (c.get("state") or "").lower():
                return False
            if a.sections and c["section"] not in a.sections:
                return False
            if a.doc_types and c["doc_type"] not in a.doc_types:
                return False
            if a.event_id and c["event_id"] != a.event_id:
                return False
            return True
        return np.array([ok(c) for c in self.rows])

    def search(self, a: SearchArgs, n_candidates: int = 30, n_rerank: int = 20, per_event: int = 2) -> list[dict]:
        mask = self._mask(a)
        if not mask.any():
            return []
        if a.diverse:  # breadth: more candidates so 12 different incidents can survive the one-per-incident cap
            n_candidates, n_rerank = max(n_candidates, 60), max(n_rerank, 40)
        ranks: dict[int, float] = {}
        bm = np.asarray(self.bm25.get_scores(bm25_tokens(a.query)))
        bm[~mask] = -1e9
        bm_top = [i for i in np.argsort(-bm)[:n_candidates] if bm[i] > 0]
        lists = [bm_top]
        if self.dense is not None:
            q = self.embedder.encode([a.query], is_query=True)[0]
            ds = self.dense @ q
            ds[~mask] = -1e9
            lists.append(list(np.argsort(-ds)[:n_candidates]))
        for lst in lists:  # reciprocal rank fusion, k=60
            for r, i in enumerate(lst):
                ranks[i] = ranks.get(i, 0.0) + 1.0 / (60 + r + 1)
        fused = sorted(ranks, key=lambda i: -ranks[i])[:n_rerank]
        cands = [dict(self.rows[i], rrf=round(ranks[i], 5)) for i in fused]
        if self.reranker and cands:
            scores = self.reranker.predict([(a.query, c["index_text"]) for c in cands])
            for c, s in zip(cands, scores):
                c["rerank"] = float(s)
            if self.rerank_mode == "replace":
                cands.sort(key=lambda c: -c["rerank"])
            else:
                ce_rank = {id(c): r for r, c in enumerate(sorted(cands, key=lambda c: -c["rerank"]))}
                for r, c in enumerate(cands):  # cands are currently in RRF order
                    c["final"] = 1 / (60 + r + 1) + 1 / (60 + ce_rank[id(c)] + 1)
                cands.sort(key=lambda c: -c["final"])
        if a.diverse:
            return select_evidence(cands, a.k, 1, lift=False)
        return select_evidence(cands, a.k, per_event)


def _shingles(t: str) -> set:
    w = re.findall(r"[a-z0-9]+", t.lower())
    return {" ".join(w[i:i + 5]) for i in range(max(1, len(w) - 4))}


def select_evidence(cands: list[dict], k: int, per_event: int, lift: bool = True) -> list[dict]:
    # single-incident question ("root causes of the Aug 20, 2009 fatality at X"): when the top event dominates the
    # candidates, the diversity cap would hide its other root causes / citations -> lift the cap for that event.
    top10 = [c["event_id"] for c in cands[:10]]
    if lift and top10 and top10.count(top10[0]) >= 3:
        per_event = max(per_event, 6)
    out, per, seen = [], {}, []
    for c in cands:
        if per.get(c["event_id"], 0) >= per_event:
            continue
        sh = _shingles(c["text"])
        if any(len(sh & s) / max(1, len(sh | s)) > 0.6 for s in seen):
            continue  # near-duplicate (e.g. root-cause pairs with identical corrective action text)
        out.append(c)
        seen.append(sh)
        per[c["event_id"]] = per.get(c["event_id"], 0) + 1
        if len(out) >= k:
            break
    return out


@lru_cache(maxsize=1)
def get_retriever() -> Retriever:
    return Retriever()


def warmup() -> None:
    """Load the indexes and models in a background thread so the first question does not pay ~35 s for it. Safe to call many times."""
    import threading

    def _load():
        try:
            get_retriever()
        except Exception:  # noqa: BLE001  a missing index is reported by /health and by the first search, not here
            pass
    if not getattr(warmup, "_started", False):
        warmup._started = True
        threading.Thread(target=_load, name="retriever-warmup", daemon=True).start()


def hybrid_search(**kwargs) -> list[dict]:
    kwargs = dict(kwargs)
    v = kwargs.pop("year", None)   # {"year": 2019} from the 8B Planner would otherwise be dropped silently
    if v is not None and not kwargs.get("year_from") and not kwargs.get("year_to"):
        try:
            kwargs["year_from"] = kwargs["year_to"] = int(v)
        except (TypeError, ValueError):
            pass
    a = SearchArgs(**kwargs)
    if a.diverse:
        a.k = max(a.k, 12)
    keep = ("chunk_id", "event_id", "doc_type", "date", "section", "subheading", "classification", "mine_type",
            "material", "state", "mine_name", "cfr_ids", "text", "source_path", "rerank")
    return [{k: c.get(k) for k in keep} for c in get_retriever().search(a)]
