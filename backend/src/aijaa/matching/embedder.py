"""Embedding layer. Default: deterministic local hashing embedder (TF-weighted
bag of words hashed to 256 dims) — free, offline, good enough as a coarse
retriever since the Claude re-ranker does the fine judgment. Swap in a real
embedding provider via the Embedder protocol for production semantic recall."""

import hashlib
import math
import re
from typing import Protocol

DIM = 256
# Python's Unicode-aware \w keeps Hebrew and other non-Latin CV/job terms in
# local retrieval instead of silently discarding them.
_TOKEN_RE = re.compile(r"[^\W_][\w+#./&-]*", re.UNICODE)


class Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    async def embed(self, text: str) -> list[float]:
        vec = [0.0] * DIM
        tokens = [t.lower() for t in _TOKEN_RE.findall(text or "")]
        for tok in tokens:
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            idx = h % DIM
            sign = 1.0 if (h >> 16) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def get_embedder() -> Embedder:
    return HashingEmbedder()
