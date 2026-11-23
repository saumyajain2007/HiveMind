"""Social graph layers (issue #3, HANDOFF §4 M1 `graph.py`).

One `Layer` per platform. Every layer exposes

    push(sharers, *, topic=0, popularity=None) -> float32 exposure of length N
    stats() -> dict

`push` returns exposure **already scaled by the layer's `reach`**, so diffusion sums the layers
directly. Only agents who use a platform carry edges on it.

Layer kinds
-----------
* directed (twitter, instagram, youtube): edges are follower -> followee (subscriber -> creator).
  Stored as a *receiver CSR*: row = followee, columns = followers, so a push only touches the
  sharers' rows (gather with `np.repeat` over indptr ranges, then `np.bincount`).
* undirected (friendship): symmetric CSR.
* membership (reddit): user <-> subreddit, both CSR directions.
* algorithmic (tiktok): no edges; exposure from interest match, popularity and activity.

Graph generators are parameterised so `layer_stats()` can be matched to published statistics;
see DATA_SOURCES.md. Fitting to data is TODO (HANDOFF §2.6).

Run ``python -m marketsim.graph`` to print `layer_stats()` for a 10k-agent population.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from .config import ALL_PLATFORMS, TOPICS, GraphConfig

PLATFORM_INDEX = {p: i for i, p in enumerate(ALL_PLATFORMS)}
_STATS_SEED = 12345  # stats use their own RNG so they never disturb a simulation's stream


class GraphPopulation(Protocol):
    """The population fields the graph reads; `marketsim.population.Population` provides them.

    A negative `community` (media outlets) means "no offline community".
    """

    @property
    def n(self) -> int: ...

    community: np.ndarray  # int (N,): offline community id
    interests: np.ndarray  # float (N, len(TOPICS)): topic mix, rows sum to 1
    influence: np.ndarray  # float (N,): heavy-tailed influence potential
    platform_use: np.ndarray  # bool (N, len(ALL_PLATFORMS))
    platform_intensity: np.ndarray  # float (N, len(ALL_PLATFORMS)), 0 for non-users


# --------------------------------------------------------------------------- array helpers


def build_csr(rows: np.ndarray, cols: np.ndarray, n_rows: int) -> tuple[np.ndarray, np.ndarray]:
    """CSR (indptr int64, indices int32) with `cols` grouped by `rows`."""
    order = np.argsort(rows, kind="stable")
    indptr = np.zeros(n_rows + 1, np.int64)
    np.cumsum(np.bincount(rows, minlength=n_rows), out=indptr[1:])
    return indptr, cols[order].astype(np.int32)


def gather_rows(indptr: np.ndarray, indices: np.ndarray, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Concatenate the CSR rows `rows`. Returns (columns, position of the source row in `rows`)."""
    rows = np.asarray(rows, np.int64)
    starts = indptr[rows]
    counts = indptr[rows + 1] - starts
    total = int(counts.sum())
    if total == 0:
        return np.zeros(0, np.int32), np.zeros(0, np.int64)
    offsets = np.repeat(starts - (np.cumsum(counts) - counts), counts) + np.arange(total)
    return indices[offsets], np.repeat(np.arange(len(rows)), counts)


def dedupe_pairs(
    a: np.ndarray, b: np.ndarray, n: int, drop_self: bool = True
) -> tuple[np.ndarray, np.ndarray]:
    """Drop duplicate (a, b) pairs via int64 keys (and self-loops unless `drop_self` is False).

    `n` must exceed every value in `b`. Output is sorted by (a, b).
    """
    if drop_self:
        keep = a != b
        a, b = a[keep], b[keep]
    keys = np.unique(a.astype(np.int64) * n + b)
    return (keys // n).astype(np.int32), (keys % n).astype(np.int32)


def undirected_keys(a: np.ndarray, b: np.ndarray, n: int) -> np.ndarray:
    """Sorted unique int64 keys of the unordered pairs {a, b} (self-loops dropped)."""
    lo, hi = np.minimum(a, b).astype(np.int64), np.maximum(a, b).astype(np.int64)
    keep = lo != hi
    return np.unique(lo[keep] * n + hi[keep])


def sample_targets(
    rng: np.random.Generator,
    src_group: np.ndarray,
    pool: np.ndarray,
    weights: np.ndarray,
    pool_group: np.ndarray,
    homophily: float,
) -> np.ndarray:
    """For each edge stub, draw a target from `pool` with probability proportional to `weights`.

    With probability `homophily` the target is drawn inside the stub's group (falling back to
    the whole pool if the group has no weight). Stubs whose group is negative ("no group")
    always draw from the whole pool. One sort by group, one cumulative sum, and one
    `searchsorted` for all stubs.
    """
    m = len(src_group)
    if m == 0 or len(pool) == 0:
        return np.zeros(0, np.int32)
    order = np.argsort(pool_group, kind="stable")
    pool_s, g_s = pool[order], pool_group[order]
    cum = np.cumsum(weights[order].astype(np.float64))
    total = cum[-1]
    n_groups = max(int(g_s.max()), int(src_group.max()), -1) + 1
    cum0 = np.concatenate([[0.0], cum])
    lo = cum0[np.searchsorted(g_s, np.arange(n_groups), "left")]
    hi = cum0[np.searchsorted(g_s, np.arange(n_groups), "right")]

    a = np.zeros(m)
    b = np.full(m, total)
    # A negative group means "no group" (e.g. media outlets have community -1): draw globally.
    inside = np.flatnonzero((rng.random(m) < homophily) & (src_group >= 0))
    g = src_group[inside]
    ok = hi[g] > lo[g]
    a[inside[ok]] = lo[g[ok]]
    b[inside[ok]] = hi[g[ok]]
    x = a + rng.random(m) * (b - a)
    k = np.minimum(np.searchsorted(cum, x, side="right"), len(cum) - 1)
    return pool_s[k].astype(np.int32)


def lognormal_counts(
    rng: np.random.Generator, mean: np.ndarray | float, sigma: float, size: int
) -> np.ndarray:
    """Poisson counts whose rate is `mean` times a mean-one lognormal factor."""
    factor = rng.lognormal(-0.5 * sigma**2, sigma, size)
    return rng.poisson(np.asarray(mean) * factor).astype(np.int64)


def _percentiles(x: np.ndarray) -> dict[str, float]:
    if len(x) == 0:
        return {"mean": 0.0, "p50": 0.0, "p90": 0.0, "p99": 0.0, "max": 0.0}
    p50, p90, p99 = np.percentile(x, [50, 90, 99])
    return {
        "mean": float(x.mean()),
        "p50": float(p50),
        "p90": float(p90),
        "p99": float(p99),
        "max": float(x.max()),
    }


def sampled_clustering(
    indptr: np.ndarray, indices: np.ndarray, rng: np.random.Generator, n_sample: int = 400, cap: int = 100
) -> float:
    """Mean local clustering coefficient over sampled nodes of a symmetric CSR.

    Nodes with degree < 2 are skipped. Neighbourhoods larger than `cap` are subsampled
    (an unbiased estimate of the link density among neighbours).
    """
    deg = np.diff(indptr)
    cand = np.flatnonzero(deg >= 2)
    if len(cand) == 0:
        return 0.0
    nodes = rng.choice(cand, size=min(n_sample, len(cand)), replace=False)
    coeffs = np.empty(len(nodes))
    for i, v in enumerate(nodes):
        nb = indices[indptr[v] : indptr[v + 1]]
        if len(nb) > cap:
            nb = rng.choice(nb, cap, replace=False)
        cols, _ = gather_rows(indptr, indices, nb)
        links = np.isin(cols, nb).sum() / 2  # each neighbour-neighbour edge is seen from both ends
        k = len(nb)
        coeffs[i] = links / (k * (k - 1) / 2)
    return float(coeffs.mean())


# --------------------------------------------------------------------------- layers


class Layer:
    """Base class. Subclasses set `kind` and implement `push`, `stats`, `add_nodes`."""

    kind = "base"

    def __init__(self, name: str, n: int, users: np.ndarray, reach: float, trust: float) -> None:
        self.name = name
        self.n = n
        self.users = users.astype(np.int32)
        self.reach = float(reach)
        self.trust = float(trust)

    def push(self, sharers: np.ndarray, *, topic: int = 0, popularity: float | None = None) -> np.ndarray:
        raise NotImplementedError

    def stats(self) -> dict[str, Any]:
        raise NotImplementedError

    def edge_keys(self) -> np.ndarray | None:
        """Unordered edge keys for cross-layer overlap; None for layers without edges."""
        return None

    def add_nodes(
        self, pop: GraphPopulation, new_ids: np.ndarray, cfg: GraphConfig, rng: np.random.Generator
    ) -> None:
        raise NotImplementedError

    def _new_users(self, pop: GraphPopulation, new_ids: np.ndarray) -> np.ndarray:
        col = PLATFORM_INDEX[self.name]
        new_ids = np.asarray(new_ids)
        new_users = new_ids[pop.platform_use[new_ids, col]].astype(np.int32)
        self.n = pop.n
        self.users = np.concatenate([self.users, new_users])
        return new_users


class DirectedLayer(Layer):
    """Follower -> followee graph with a receiver CSR (row = followee, columns = followers)."""

    kind = "directed"

    def __init__(
        self,
        name: str,
        n: int,
        users: np.ndarray,
        follower: np.ndarray,
        followee: np.ndarray,
        reach: float,
        trust: float,
        group_of: str,
        mean_out: float,
        homophily: float,
    ) -> None:
        super().__init__(name, n, users, reach, trust)
        self.follower, self.followee = follower, followee
        self.group_of = group_of  # "interest" or "community": how homophily groups are defined
        self.mean_out = mean_out
        self.homophily = homophily
        self._rebuild()

    def _rebuild(self) -> None:
        self.follower, self.followee = dedupe_pairs(self.follower, self.followee, self.n)
        self.indptr, self.indices = build_csr(self.followee, self.follower, self.n)

    @property
    def n_edges(self) -> int:
        return len(self.follower)

    def push(self, sharers: np.ndarray, *, topic: int = 0, popularity: float | None = None) -> np.ndarray:
        followers, _ = gather_rows(self.indptr, self.indices, sharers)
        out = np.bincount(followers, minlength=self.n).astype(np.float32)
        out *= self.reach
        return out

    def in_degree(self) -> np.ndarray:
        return np.bincount(self.followee, minlength=self.n)

    def out_degree(self) -> np.ndarray:
        return np.bincount(self.follower, minlength=self.n)

    def reciprocity(self) -> float:
        if self.n_edges == 0:
            return 0.0
        fwd = self.follower.astype(np.int64) * self.n + self.followee
        rev = self.followee.astype(np.int64) * self.n + self.follower
        return float(np.isin(rev, fwd, assume_unique=True).mean())

    def edge_keys(self) -> np.ndarray:
        return undirected_keys(self.follower, self.followee, self.n)

    def _symmetric_csr(self) -> tuple[np.ndarray, np.ndarray]:
        keys = self.edge_keys()
        a, b = keys // self.n, keys % self.n
        return build_csr(np.concatenate([a, b]), np.concatenate([b, a]), self.n)

    def stats(self) -> dict[str, Any]:
        rng = np.random.default_rng(_STATS_SEED)
        ind, outd = self.in_degree()[self.users], self.out_degree()[self.users]
        med = np.median(ind) if len(ind) else 0.0
        return {
            "kind": self.kind,
            "users": len(self.users),
            "edges": self.n_edges,
            "in_degree": _percentiles(ind),
            "out_degree": _percentiles(outd),
            "in_max_over_median": float(ind.max() / med) if med > 0 else None,
            "reciprocity": self.reciprocity(),
            "clustering": sampled_clustering(*self._symmetric_csr(), rng),
        }

    def _groups(self, pop: GraphPopulation) -> np.ndarray:
        if self.group_of == "interest":
            return np.argmax(pop.interests, axis=1).astype(np.int32)
        return np.asarray(pop.community, np.int32)

    def _target_pool(self) -> np.ndarray:
        return self.users

    def add_nodes(
        self, pop: GraphPopulation, new_ids: np.ndarray, cfg: GraphConfig, rng: np.random.Generator
    ) -> None:
        """New users follow existing ones by preferential attachment (weight = followers + 1)."""
        new_users = self._new_users(pop, new_ids)
        if len(new_users) == 0:
            self._rebuild()
            return
        col = PLATFORM_INDEX[self.name]
        act = np.asarray(pop.platform_intensity[:, col], np.float64)
        mean_act = act[self.users].mean() or 1.0
        deg = lognormal_counts(
            rng, self.mean_out * act[new_users] / mean_act, cfg.degree_sigma, len(new_users)
        )
        pool = self._target_pool()
        deg = np.minimum(deg, max(len(pool) - 1, 0))
        src = np.repeat(new_users, deg)
        groups = self._groups(pop)
        weights = np.bincount(self.followee, minlength=self.n)[pool] + 1.0
        tgt = sample_targets(rng, groups[src], pool, weights, groups[pool], self.homophily)
        self.follower = np.concatenate([self.follower, src.astype(np.int32)])
        self.followee = np.concatenate([self.followee, tgt])
        self._rebuild()


class YouTubeLayer(DirectedLayer):
    """Subscriber -> creator graph. Only creators' shares produce exposure.

    The production lag (`lag_ticks`) is applied by diffusion (issue #6): it calls `push` when a
    creator's video lands, not when the creator decides to cover the item.
    """

    def __init__(self, *args: Any, creators: np.ndarray, lag_ticks: tuple[int, int], **kw: Any) -> None:
        self.creators = creators.astype(np.int32)
        self.lag_ticks = lag_ticks
        super().__init__(*args, **kw)

    def _target_pool(self) -> np.ndarray:
        return self.creators

    def stats(self) -> dict[str, Any]:
        s = super().stats()
        subs = self.in_degree()[self.creators]
        s["creators"] = len(self.creators)
        s["subscribers_per_creator"] = _percentiles(subs)
        return s


class FriendshipLayer(Layer):
    """Undirected friendship graph stored as canonical pairs (a < b) plus a symmetric CSR."""

    kind = "undirected"

    def __init__(
        self,
        name: str,
        n: int,
        users: np.ndarray,
        a: np.ndarray,
        b: np.ndarray,
        reach: float,
        trust: float,
        mean_degree: float,
        homophily: float,
    ) -> None:
        super().__init__(name, n, users, reach, trust)
        self.a, self.b = a, b
        self.mean_degree = mean_degree
        self.homophily = homophily
        self._rebuild()

    def _rebuild(self) -> None:
        keys = undirected_keys(self.a, self.b, self.n)
        self.a, self.b = (keys // self.n).astype(np.int32), (keys % self.n).astype(np.int32)
        self.indptr, self.indices = build_csr(
            np.concatenate([self.a, self.b]), np.concatenate([self.b, self.a]), self.n
        )

    @property
    def n_edges(self) -> int:
        return len(self.a)

    def degree(self) -> np.ndarray:
        return np.diff(self.indptr)

    def push(self, sharers: np.ndarray, *, topic: int = 0, popularity: float | None = None) -> np.ndarray:
        friends, _ = gather_rows(self.indptr, self.indices, sharers)
        out = np.bincount(friends, minlength=self.n).astype(np.float32)
        out *= self.reach
        return out

    def edge_keys(self) -> np.ndarray:
        return self.a.astype(np.int64) * self.n + self.b

    def stats(self) -> dict[str, Any]:
        rng = np.random.default_rng(_STATS_SEED)
        return {
            "kind": self.kind,
            "users": len(self.users),
            "edges": self.n_edges,
            "degree": _percentiles(self.degree()[self.users]),
            "clustering": sampled_clustering(self.indptr, self.indices, rng),
        }

    def close_triangles(self, share: float, rng: np.random.Generator) -> None:
        """Add about `share * edges` edges, each joining two random neighbours of a random node."""
        k = round(share * self.n_edges)
        deg = self.degree()
        cand = np.flatnonzero(deg >= 2)
        if k == 0 or len(cand) == 0:
            return
        v = rng.choice(cand, k)
        d = deg[v]
        r1 = (rng.random(k) * d).astype(np.int64)
        r2 = (rng.random(k) * (d - 1)).astype(np.int64)
        r2 += r2 >= r1  # second neighbour distinct from the first
        u1 = self.indices[self.indptr[v] + r1]
        u2 = self.indices[self.indptr[v] + r2]
        self.a = np.concatenate([self.a, u1])
        self.b = np.concatenate([self.b, u2])
        self._rebuild()

    def add_nodes(
        self, pop: GraphPopulation, new_ids: np.ndarray, cfg: GraphConfig, rng: np.random.Generator
    ) -> None:
        """New users befriend existing ones by preferential attachment (weight = degree + 1)."""
        new_users = self._new_users(pop, new_ids)
        if len(new_users):
            deg = lognormal_counts(rng, self.mean_degree / 2, cfg.degree_sigma, len(new_users))
            src = np.repeat(new_users, deg)
            community = np.asarray(pop.community, np.int32)
            weights = np.bincount(np.concatenate([self.a, self.b]), minlength=self.n)[self.users] + 1.0
            tgt = sample_targets(
                rng, community[src], self.users, weights, community[self.users], self.homophily
            )
            self.a = np.concatenate([self.a, src.astype(np.int32)])
            self.b = np.concatenate([self.b, tgt])
        self._rebuild()


class RedditLayer(Layer):
    """User <-> subreddit memberships. A sub's intensity grows with the number of sharers in it."""

    kind = "membership"

    def __init__(
        self,
        name: str,
        n: int,
        users: np.ndarray,
        member: np.ndarray,
        sub: np.ndarray,
        sub_topic: np.ndarray,
        sub_popularity: np.ndarray,
        reach: float,
        trust: float,
        mean_memberships: float,
    ) -> None:
        super().__init__(name, n, users, reach, trust)
        self.member, self.sub = member, sub
        self.sub_topic = sub_topic.astype(np.int32)
        self.sub_popularity = sub_popularity
        self.mean_memberships = mean_memberships
        self._rebuild()

    @property
    def n_subs(self) -> int:
        return len(self.sub_topic)

    def _rebuild(self) -> None:
        self.member, self.sub = dedupe_pairs(self.member, self.sub, self.n_subs, drop_self=False)
        self.sub_size = np.bincount(self.sub, minlength=self.n_subs)
        self.sub_ptr, self.sub_members = build_csr(self.sub, self.member, self.n_subs)
        self.user_ptr, self.user_subs = build_csr(self.member, self.sub, self.n)

    def push(self, sharers: np.ndarray, *, topic: int = 0, popularity: float | None = None) -> np.ndarray:
        subs, _ = gather_rows(self.user_ptr, self.user_subs, sharers)
        score = np.bincount(subs, minlength=self.n_subs)
        active = np.flatnonzero(score)
        if len(active) == 0:
            return np.zeros(self.n, np.float32)
        intensity = self.reach * score[active] / np.sqrt(self.sub_size[active])
        members, pos = gather_rows(self.sub_ptr, self.sub_members, active)
        return np.bincount(members, weights=intensity[pos], minlength=self.n).astype(np.float32)

    def stats(self) -> dict[str, Any]:
        per_user = np.diff(self.user_ptr)[self.users]
        return {
            "kind": self.kind,
            "users": len(self.users),
            "subs": self.n_subs,
            "memberships": len(self.member),
            "memberships_per_user": _percentiles(per_user),
            "sub_size": _percentiles(self.sub_size),
            "subs_per_topic": {t: int((self.sub_topic == i).sum()) for i, t in enumerate(TOPICS)},
        }

    @staticmethod
    def sample_memberships(
        rng: np.random.Generator,
        users: np.ndarray,
        interests: np.ndarray,
        sub_topic: np.ndarray,
        sub_weight: np.ndarray,
        mean_memberships: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Each user joins 1 + Poisson(mean - 1) subs: topic by interest, then sub by weight."""
        k = 1 + rng.poisson(max(mean_memberships - 1.0, 0.0), len(users))
        k = np.minimum(k, len(sub_topic))
        member = np.repeat(users, k)
        cum = np.cumsum(interests[member], axis=1)
        u = rng.random(len(member)) * cum[:, -1]
        topic = (cum < u[:, None]).sum(axis=1).astype(np.int32)
        topic = np.minimum(topic, interests.shape[1] - 1)
        # homophily = 1: always inside the chosen topic (topics with no subs fall back to all subs)
        sub = sample_targets(rng, topic, np.arange(len(sub_topic)), sub_weight, sub_topic, 1.0)
        return member.astype(np.int32), sub

    def add_nodes(
        self, pop: GraphPopulation, new_ids: np.ndarray, cfg: GraphConfig, rng: np.random.Generator
    ) -> None:
        """New users join subs by interest, then preferentially by current sub size."""
        new_users = self._new_users(pop, new_ids)
        if len(new_users):
            m, s = self.sample_memberships(
                rng,
                new_users,
                np.asarray(pop.interests, np.float64),
                self.sub_topic,
                self.sub_size + 1.0,
                self.mean_memberships,
            )
            self.member = np.concatenate([self.member, m])
            self.sub = np.concatenate([self.sub, s])
        self._rebuild()


class TikTokLayer(Layer):
    """No edges. exposure = reach * sqrt(popularity) * cosine(interests, item topic) * activity."""

    kind = "algorithmic"

    def __init__(
        self, name: str, n: int, users: np.ndarray, pop: GraphPopulation, reach: float, trust: float
    ) -> None:
        super().__init__(name, n, users, reach, trust)
        self._refresh(pop)

    def _refresh(self, pop: GraphPopulation) -> None:
        col = PLATFORM_INDEX[self.name]
        interests = np.asarray(pop.interests, np.float64)
        norm = np.linalg.norm(interests, axis=1, keepdims=True)
        self.interest_unit = (interests / np.where(norm > 0, norm, 1.0)).astype(np.float32)
        self.activity = np.asarray(pop.platform_intensity[:, col], np.float32)

    def push(self, sharers: np.ndarray, *, topic: int = 0, popularity: float | None = None) -> np.ndarray:
        pop_ = float(len(sharers)) if popularity is None else float(popularity)
        out = np.zeros(self.n, np.float32)
        if pop_ <= 0:
            return out
        u = self.users
        out[u] = self.reach * np.sqrt(pop_) * self.interest_unit[u, topic] * self.activity[u]
        return out

    def stats(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "users": len(self.users),
            "activity": _percentiles(self.activity[self.users]),
        }

    def add_nodes(
        self, pop: GraphPopulation, new_ids: np.ndarray, cfg: GraphConfig, rng: np.random.Generator
    ) -> None:
        self._new_users(pop, new_ids)
        self._refresh(pop)


# --------------------------------------------------------------------------- builders


def _users(pop: GraphPopulation, name: str) -> np.ndarray:
    return np.flatnonzero(pop.platform_use[:, PLATFORM_INDEX[name]]).astype(np.int32)


def _follow_edges(
    rng: np.random.Generator,
    pop: GraphPopulation,
    name: str,
    users: np.ndarray,
    pool: np.ndarray,
    groups: np.ndarray,
    mean_out: float,
    homophily: float,
    sigma: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Chung–Lu: out-degree lognormal x activity; targets proportional to influence."""
    act = np.asarray(pop.platform_intensity[users, PLATFORM_INDEX[name]], np.float64)
    mean_act = act.mean() if len(act) and act.mean() > 0 else 1.0
    deg = lognormal_counts(rng, mean_out * act / mean_act, sigma, len(users))
    deg = np.minimum(deg, max(len(pool) - 1, 0))
    src = np.repeat(users, deg)
    weights = np.asarray(pop.influence, np.float64)[pool]
    tgt = sample_targets(rng, groups[src], pool, weights, groups[pool], homophily)
    return src.astype(np.int32), tgt


def build_directed(
    pop: GraphPopulation, name: str, cfg: GraphConfig, rng: np.random.Generator
) -> DirectedLayer:
    if name == "twitter":
        mean_out, homophily, group_of = cfg.twitter_mean_out, cfg.twitter_homophily, "interest"
    elif name == "instagram":
        mean_out, homophily, group_of = cfg.instagram_mean_out, cfg.instagram_homophily, "community"
    else:
        raise ValueError(f"not a directed follow layer: {name}")
    users = _users(pop, name)
    groups = (
        np.argmax(pop.interests, axis=1).astype(np.int32)
        if group_of == "interest"
        else np.asarray(pop.community, np.int32)
    )
    src, tgt = _follow_edges(rng, pop, name, users, users, groups, mean_out, homophily, cfg.degree_sigma)
    return DirectedLayer(
        name, pop.n, users, src, tgt, cfg.reach[name], cfg.trust[name], group_of, mean_out, homophily
    )


def build_youtube(pop: GraphPopulation, cfg: GraphConfig, rng: np.random.Generator) -> YouTubeLayer:
    """Creators = top `youtube_creator_share` of YouTube users by influence."""
    users = _users(pop, "youtube")
    n_creators = max(1, round(cfg.youtube_creator_share * len(users))) if len(users) else 0
    infl = np.asarray(pop.influence)[users]
    creators = np.sort(users[np.argsort(-infl, kind="stable")[:n_creators]])
    groups = np.argmax(pop.interests, axis=1).astype(np.int32)
    src, tgt = _follow_edges(
        rng,
        pop,
        "youtube",
        users,
        creators,
        groups,
        cfg.youtube_mean_subs,
        cfg.youtube_homophily,
        cfg.degree_sigma,
    )
    return YouTubeLayer(
        "youtube",
        pop.n,
        users,
        src,
        tgt,
        cfg.reach["youtube"],
        cfg.trust["youtube"],
        "interest",
        cfg.youtube_mean_subs,
        cfg.youtube_homophily,
        creators=creators,
        lag_ticks=tuple(cfg.youtube_lag_ticks),
    )


def build_friendship(pop: GraphPopulation, cfg: GraphConfig, rng: np.random.Generator) -> FriendshipLayer:
    """Lognormal degrees; each user initiates ~degree/2 ties, partners weighted by degree,
    a `friendship_homophily` share inside the offline community; then triadic closure."""
    users = _users(pop, "friendship")
    target_deg = lognormal_counts(rng, cfg.friendship_mean_degree, cfg.degree_sigma, len(users))
    initiated = rng.binomial(target_deg, 0.5)
    src = np.repeat(users, initiated)
    community = np.asarray(pop.community, np.int32)
    tgt = sample_targets(
        rng, community[src], users, target_deg + 0.5, community[users], cfg.friendship_homophily
    )
    layer = FriendshipLayer(
        "friendship",
        pop.n,
        users,
        src.astype(np.int32),
        tgt,
        cfg.reach["friendship"],
        cfg.trust["friendship"],
        cfg.friendship_mean_degree,
        cfg.friendship_homophily,
    )
    layer.close_triangles(cfg.triadic_closure, rng)
    return layer


def build_reddit(pop: GraphPopulation, cfg: GraphConfig, rng: np.random.Generator) -> RedditLayer:
    """`round(N / reddit_agents_per_sub)` subs (at least one per topic); topics in proportion
    to users' total interest; Zipf popularity within each topic."""
    users = _users(pop, "reddit")
    interests = np.asarray(pop.interests, np.float64)
    n_topics = interests.shape[1]
    n_subs = max(n_topics, round(pop.n / cfg.reddit_agents_per_sub))
    share = interests[users].sum(axis=0) if len(users) else np.ones(n_topics)
    share = share / share.sum()
    extra = rng.multinomial(n_subs - n_topics, share)
    sub_topic = np.repeat(np.arange(n_topics), 1 + extra).astype(np.int32)
    rank = np.zeros(n_subs)
    for t in range(n_topics):
        idx = np.flatnonzero(sub_topic == t)
        rank[idx] = rng.permutation(len(idx)) + 1
    popularity = rank ** (-cfg.reddit_zipf)
    member, sub = RedditLayer.sample_memberships(
        rng, users, interests, sub_topic, popularity, cfg.reddit_mean_memberships
    )
    return RedditLayer(
        "reddit",
        pop.n,
        users,
        member,
        sub,
        sub_topic,
        popularity,
        cfg.reach["reddit"],
        cfg.trust["reddit"],
        cfg.reddit_mean_memberships,
    )


def build_tiktok(pop: GraphPopulation, cfg: GraphConfig, rng: np.random.Generator) -> TikTokLayer:
    return TikTokLayer("tiktok", pop.n, _users(pop, "tiktok"), pop, cfg.reach["tiktok"], cfg.trust["tiktok"])


_BUILDERS = {
    "twitter": lambda pop, cfg, rng: build_directed(pop, "twitter", cfg, rng),
    "instagram": lambda pop, cfg, rng: build_directed(pop, "instagram", cfg, rng),
    "friendship": build_friendship,
    "reddit": build_reddit,
    "tiktok": build_tiktok,
    "youtube": build_youtube,
}


# --------------------------------------------------------------------------- graph


@dataclass
class SocialGraph:
    """All platform layers over one population."""

    n: int
    cfg: GraphConfig
    layers: dict[str, Layer] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        pop: GraphPopulation,
        cfg: GraphConfig,
        rng: np.random.Generator,
        platforms: Sequence[str] | None = None,
    ) -> SocialGraph:
        """Build the layers in `platforms` (default `cfg.platforms`), in ALL_PLATFORMS order so
        the random stream does not depend on how the list is written."""
        wanted = set(cfg.platforms if platforms is None else platforms)
        unknown = wanted - set(ALL_PLATFORMS)
        if unknown:
            raise ValueError(f"unknown platforms: {sorted(unknown)}")
        layers = {p: _BUILDERS[p](pop, cfg, rng) for p in ALL_PLATFORMS if p in wanted}
        return cls(pop.n, cfg, layers)

    def push(self, platform: str, sharers: np.ndarray, **kw: Any) -> np.ndarray:
        return self.layers[platform].push(sharers, **kw)

    def add_nodes(self, pop: GraphPopulation, new_ids: np.ndarray, rng: np.random.Generator) -> None:
        """Attach agents already appended to `pop`; nodes are never removed."""
        for layer in self.layers.values():
            layer.add_nodes(pop, new_ids, self.cfg, rng)
        self.n = pop.n

    def layer_stats(self) -> dict[str, Any]:
        """Per-layer statistics plus pairwise Jaccard overlap of the edge sets."""
        out: dict[str, Any] = {name: layer.stats() for name, layer in self.layers.items()}
        keyed = {name: k for name, layer in self.layers.items() if (k := layer.edge_keys()) is not None}
        names = list(keyed)
        overlap: dict[str, float] = {}
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                inter = len(np.intersect1d(keyed[a], keyed[b], assume_unique=True))
                union = len(keyed[a]) + len(keyed[b]) - inter
                overlap[f"{a}~{b}"] = inter / union if union else 0.0
        out["overlap_jaccard"] = overlap
        return out


def format_stats(stats: dict[str, Any]) -> str:
    """Plain-text table of `layer_stats()` output."""

    def dist(d: dict[str, float]) -> str:
        return (
            f"mean {d['mean']:7.1f}  p50 {d['p50']:6.0f}  p90 {d['p90']:6.0f}"
            f"  p99 {d['p99']:6.0f}  max {d['max']:6.0f}"
        )

    lines = []
    for name, s in stats.items():
        if name == "overlap_jaccard":
            continue
        lines.append(f"[{name}] {s['kind']}, {s['users']} users")
        if s["kind"] == "directed":
            lines.append(
                f"  edges {s['edges']}  reciprocity {s['reciprocity']:.3f}  clustering {s['clustering']:.3f}"
            )
            ratio = s["in_max_over_median"]
            ratio_txt = f"{ratio:.1f}" if ratio is not None else "n/a"
            lines.append(f"  in-degree   {dist(s['in_degree'])}  (max/median {ratio_txt})")
            lines.append(f"  out-degree  {dist(s['out_degree'])}")
            if "creators" in s:
                lines.append(f"  creators {s['creators']}  subs/creator {dist(s['subscribers_per_creator'])}")
        elif s["kind"] == "undirected":
            lines.append(f"  edges {s['edges']}  clustering {s['clustering']:.3f}")
            lines.append(f"  degree      {dist(s['degree'])}")
        elif s["kind"] == "membership":
            lines.append(f"  subs {s['subs']}  memberships {s['memberships']}")
            lines.append(f"  subs/user   {dist(s['memberships_per_user'])}")
            lines.append(f"  sub size    {dist(s['sub_size'])}")
        elif s["kind"] == "algorithmic":
            lines.append(f"  activity    mean {s['activity']['mean']:.3f}  p50 {s['activity']['p50']:.3f}")
    if stats.get("overlap_jaccard"):
        lines.append("[overlap] " + "  ".join(f"{k} {v:.4f}" for k, v in stats["overlap_jaccard"].items()))
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    import argparse
    import time

    from .config import Config
    from .population import Population

    ap = argparse.ArgumentParser(description="Print layer_stats() for a population of N agents.")
    ap.add_argument("--agents", type=int, default=10_000)
    ap.add_argument("--all-platforms", action="store_true", help="also build instagram, tiktok, youtube")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    population = Population.build(Config(n_agents=args.agents, seed=args.seed))
    t0 = time.perf_counter()
    graph = SocialGraph.build(
        population,
        GraphConfig(),
        np.random.default_rng(args.seed),
        platforms=ALL_PLATFORMS if args.all_platforms else None,
    )
    print(f"built {len(graph.layers)} layers for {args.agents} agents in {time.perf_counter() - t0:.2f}s")
    print(format_stats(graph.layer_stats()))
