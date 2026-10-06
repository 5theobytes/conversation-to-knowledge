"""Embedding interface.

* ``HashingEmbedder`` — stdlib-only, deterministic: word unigrams + character
  3-grams hashed into a fixed-size vector, L2-normalised. It gives sensible
  cosine similarity for near-duplicate phrasings *within one language*; it has
  no cross-lingual ability. It exists so the demo and tests run with zero
  dependencies.
* ``SentenceTransformerEmbedder`` — adapter for a real multilingual model
  (the production run used a multilingual MiniLM/e5 family model locally).
"""
from __future__ import annotations

import math
import re
import zlib
from typing import Protocol, Sequence

TOKEN_RE = re.compile(r"\w+", re.UNICODE)
Vector = list[float]


class Embedder(Protocol):
    name: str

    def embed(self, texts: Sequence[str]) -> list[Vector]: ...


def cosine(a: Vector, b: Vector) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


def _normalize(v: Vector) -> Vector:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class HashingEmbedder:
    name = "hashing-ngram"

    def __init__(self, dim: int = 1024, ngram: int = 3) -> None:
        self.dim = dim
        self.ngram = ngram

    def _features(self, text: str) -> list[str]:
        t = (text or "").lower()
        t = re.sub(r"<[a-z_]+>", " ", t)  # placeholders carry no meaning
        feats: list[str] = []
        for w in TOKEN_RE.findall(t):
            feats.append("w:" + w)
            padded = f" {w} "
            if len(padded) >= self.ngram:
                feats.extend("c:" + padded[i:i + self.ngram] for i in range(len(padded) - self.ngram + 1))
        return feats

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        out: list[Vector] = []
        for t in texts:
            v = [0.0] * self.dim
            for f in self._features(t):
                h = zlib.crc32(f.encode("utf-8"))
                v[h % self.dim] += 1.0 if (h >> 31) == 0 else -1.0  # signed hashing
            out.append(_normalize(v))
        return out


class SentenceTransformerEmbedder:
    name = "sentence-transformers"

    def __init__(self, model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2") -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore
        self._m = SentenceTransformer(model_name)

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        arr = self._m.encode(list(texts), normalize_embeddings=True)
        return [list(map(float, row)) for row in arr]
