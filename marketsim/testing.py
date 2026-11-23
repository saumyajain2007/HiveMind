"""Test helpers.

`StubPopulation` is a small stand-in that exposes only the fields the graph layer reads
(see `marketsim.graph.GraphPopulation`). Graph tests and `python -m marketsim.graph` use it
until the real copula-based `Population` (issue #2) exists. The distributions roughly
follow HANDOFF §4 M1 but are not the model's: no copula, no conditional categories.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import ALL_PLATFORMS, TOPICS

# Rough share of agents using each platform (order = ALL_PLATFORMS).
_STUB_PLATFORM_USE = {
    "twitter": 0.25,
    "reddit": 0.20,
    "friendship": 0.95,
    "instagram": 0.45,
    "tiktok": 0.35,
    "youtube": 0.60,
}


@dataclass
class StubPopulation:
    community: np.ndarray  # int32 (N,)
    interests: np.ndarray  # float32 (N, T), rows sum to 1
    influence: np.ndarray  # float64 (N,), Pareto(1.5) + 1
    platform_use: np.ndarray  # bool (N, P), columns in ALL_PLATFORMS order
    platform_intensity: np.ndarray  # float32 (N, P), 0 for non-users

    @property
    def n(self) -> int:
        return len(self.community)

    @classmethod
    def generate(cls, n: int, seed: int = 0, community_mean_size: float = 60.0) -> StubPopulation:
        pop = cls(
            community=np.zeros(0, np.int32),
            interests=np.zeros((0, len(TOPICS)), np.float32),
            influence=np.zeros(0),
            platform_use=np.zeros((0, len(ALL_PLATFORMS)), bool),
            platform_intensity=np.zeros((0, len(ALL_PLATFORMS)), np.float32),
        )
        pop.add_agents(n, np.random.default_rng(seed), community_mean_size)
        return pop

    def add_agents(self, n: int, rng: np.random.Generator, community_mean_size: float = 60.0) -> np.ndarray:
        """Append `n` agents; returns their ids. Communities are new chunks after the existing ones."""
        first = self.n
        sizes: list[int] = []
        while sum(sizes) < n:
            sizes.append(max(2, round(rng.lognormal(np.log(community_mean_size) - 0.18, 0.6))))
        base = int(self.community.max()) + 1 if first else 0
        community = np.repeat(np.arange(len(sizes)) + base, sizes)[:n].astype(np.int32)

        # Interests: Dirichlet, mixed with a per-community preferred topic.
        n_comm = len(sizes)
        pref = rng.integers(0, len(TOPICS), n_comm)
        own = rng.dirichlet(np.full(len(TOPICS), 0.4), n)
        comm = np.eye(len(TOPICS))[pref[community - base]]
        interests = (0.7 * own + 0.3 * comm).astype(np.float32)

        influence = rng.pareto(1.5, n) + 1.0
        p_use = np.array([_STUB_PLATFORM_USE[p] for p in ALL_PLATFORMS])
        use = rng.random((n, len(ALL_PLATFORMS))) < p_use
        intensity = (rng.beta(2, 3, (n, len(ALL_PLATFORMS))) * use).astype(np.float32)

        self.community = np.concatenate([self.community, community])
        self.interests = np.concatenate([self.interests, interests])
        self.influence = np.concatenate([self.influence, influence])
        self.platform_use = np.concatenate([self.platform_use, use])
        self.platform_intensity = np.concatenate([self.platform_intensity, intensity])
        return np.arange(first, first + n)
