"""Embedding backends: local bge-small (CPU) or the Track B hosted embeddings endpoint."""
from __future__ import annotations

import os

import numpy as np

from safemine import config

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class DenseUnavailable(RuntimeError):
    pass


def _lfs_stub(p) -> bool:
    return p.exists() and p.stat().st_size < 1024 and p.read_bytes().startswith(b"version https://git-lfs")


_TOK = None


def truncate_tokens(texts: list[str], max_tokens: int) -> list[str]:
    """Cut each text at its first `max_tokens` bge tokens (character offsets, so the text itself is unchanged)."""
    global _TOK
    if _TOK is None:
        from transformers import AutoTokenizer
        local = config.MODELS / "bge-small-en-v1.5"
        _TOK = AutoTokenizer.from_pretrained(str(local) if local.exists() else "BAAI/bge-small-en-v1.5")
    out = []
    for t in texts:
        enc = _TOK(t, add_special_tokens=False, truncation=True, max_length=max_tokens, return_offsets_mapping=True)
        offs = enc["offset_mapping"]
        out.append(t if not offs or offs[-1][1] >= len(t.rstrip()) else t[:offs[-1][1]])
    return out


class Embedder:
    def __init__(self):
        self.backend = config.EMBED_BACKEND
        if self.backend == "endpoint":
            import httpx
            from openai import OpenAI
            http = httpx.Client(verify=config.EMBED_CA_CERT, timeout=60) if config.EMBED_CA_CERT else None
            # max_retries: SDK backs off on capacity errors (429/503) as the quickstart asks
            self.client = OpenAI(base_url=config.EMBED_BASE_URL, api_key=config.EMBED_API_KEY, max_retries=5,
                                 http_client=http)
            self.model_name = config.EMBED_MODEL
            self.name = f"endpoint:{self.model_name}"
        else:
            from sentence_transformers import SentenceTransformer
            local = config.MODELS / "bge-small-en-v1.5"
            if _lfs_stub(local / "model.safetensors"):
                # The repo copy is a Git-LFS pointer. Either `git lfs pull`, or explicitly allow the HF download.
                if os.getenv("EMBED_ALLOW_HF_DOWNLOAD", "false").lower() != "true":
                    raise DenseUnavailable("bge-small weights are a Git-LFS stub; run `git lfs pull` or set EMBED_ALLOW_HF_DOWNLOAD=true")
                src = "BAAI/bge-small-en-v1.5"
            else:
                src = str(local)
            self.model = SentenceTransformer(src, device="cpu")
            self.name = "local:bge-small-en-v1.5"

    def encode(self, texts: list[str], is_query: bool = False, batch_size: int = 64) -> np.ndarray:
        if self.backend == "endpoint":
            # same bge query instruction as the local model, so endpoint and local vectors are interchangeable
            if is_query:
                texts = [BGE_QUERY_PREFIX + t for t in texts]
            # API rejects >512 model tokens per text (422); the local model silently truncates at 512, so cut at the
            # same place with the model's own tokenizer -> endpoint and local vectors stay identical
            texts = truncate_tokens(texts, 510)
            out = []
            bs = 16  # API limit: up to 16 texts per request
            for i in range(0, len(texts), bs):
                r = self.client.embeddings.create(model=self.model_name, input=texts[i:i + bs])
                out.extend(d.embedding for d in sorted(r.data, key=lambda d: d.index))
                if len(texts) > 200 and (i // bs) % 50 == 0:
                    print(f"  embedded {i + bs}/{len(texts)}", flush=True)
            v = np.asarray(out, dtype=np.float32)
            return v / np.linalg.norm(v, axis=1, keepdims=True).clip(1e-9)
        if is_query:
            texts = [BGE_QUERY_PREFIX + t for t in texts]
        return self.model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                                 show_progress_bar=len(texts) > 500, convert_to_numpy=True).astype(np.float32)
