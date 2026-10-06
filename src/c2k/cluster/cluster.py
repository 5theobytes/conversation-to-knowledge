"""Within-topic near-duplicate clustering (union-find on cosine >= threshold).

* no cross-topic merging: different solution contexts are not interchangeable;
* optional same-requester precondition (``require_same_requester``): the
  production run learned that merging cases of different people leaks
  personal context into one canonical record, so by default a multi-member
  cluster may only form within one chat. The demo relaxes this because the
  synthetic corpus intentionally repeats situations across members.

Threshold notes from the production run (real multilingual embeddings):
0.82 kept "card not arriving" apart from "card PIN not working"; <0.75
over-merged; >0.88 kept the same problem in two languages apart.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..models import RawCase
from .embed import Embedder, cosine

DEFAULT_THRESHOLD = 0.82


@dataclass
class Cluster:
    cluster_id: str
    topic: str
    raw_ids: list[str]

    @property
    def size(self) -> int:
        return len(self.raw_ids)


class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def cluster_cases(raws: list[RawCase], embedder: Embedder, threshold: float = DEFAULT_THRESHOLD,
                  require_same_requester: bool = False) -> list[Cluster]:
    by_topic: dict[str, list[RawCase]] = defaultdict(list)
    for r in raws:
        by_topic[r.topic].append(r)

    clusters: list[Cluster] = []
    for topic in sorted(by_topic):
        items = by_topic[topic]
        vecs = embedder.embed([f"{r.topic} | {r.case}" for r in items])
        uf = UnionFind(len(items))
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if require_same_requester and items[i].from_id != items[j].from_id:
                    continue
                if cosine(vecs[i], vecs[j]) >= threshold:
                    uf.union(i, j)
        groups: dict[int, list[int]] = defaultdict(list)
        for i in range(len(items)):
            groups[uf.find(i)].append(i)
        ordered = sorted(groups.values(), key=lambda g: (-len(g), items[g[0]].ts_first))
        for n, members in enumerate(ordered, 1):
            clusters.append(Cluster(f"{topic}-{n:03d}", topic, [items[m].raw_id for m in members]))
    return clusters
