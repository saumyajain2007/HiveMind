"""Tests for marketsim.graph (issue #3), on the real copula population from issue #2."""

from __future__ import annotations

import numpy as np
import pytest
import scipy.sparse as sp

from marketsim.config import ALL_PLATFORMS, MEDIA, Config, GraphConfig
from marketsim.graph import (
    PLATFORM_INDEX,
    DirectedLayer,
    FriendshipLayer,
    RedditLayer,
    SocialGraph,
    TikTokLayer,
    YouTubeLayer,
    build_friendship,
    format_stats,
    gather_rows,
    sample_targets,
)
from marketsim.population import Population

N = 10_000


@pytest.fixture(scope="module")
def pop() -> Population:
    return Population.build(Config(n_agents=N, seed=1))  # N people + media outlets


@pytest.fixture(scope="module")
def graph(pop: Population) -> SocialGraph:
    return SocialGraph.build(pop, GraphConfig(), np.random.default_rng(7), platforms=ALL_PLATFORMS)


def _directed(graph: SocialGraph) -> list[DirectedLayer]:
    return [layer for layer in graph.layers.values() if isinstance(layer, DirectedLayer)]


# ----------------------------------------------------------------- structure


def test_default_platforms_are_the_v1_set(pop: Population) -> None:
    g = SocialGraph.build(pop, GraphConfig(), np.random.default_rng(0))
    assert set(g.layers) == {"twitter", "reddit", "friendship"}


def test_unknown_platform_rejected(pop: Population) -> None:
    with pytest.raises(ValueError, match="unknown platforms"):
        SocialGraph.build(pop, GraphConfig(), np.random.default_rng(0), platforms=["myspace"])


def test_no_self_loops_or_duplicates(graph: SocialGraph) -> None:
    for layer in _directed(graph):
        assert np.all(layer.follower != layer.followee), layer.name
        keys = layer.follower.astype(np.int64) * layer.n + layer.followee
        assert len(np.unique(keys)) == len(keys), layer.name
    fr = graph.layers["friendship"]
    assert isinstance(fr, FriendshipLayer)
    assert np.all(fr.a < fr.b)  # canonical, so no self-loops and no (a,b)/(b,a) duplicates
    keys = fr.a.astype(np.int64) * fr.n + fr.b
    assert len(np.unique(keys)) == len(keys)
    rd = graph.layers["reddit"]
    assert isinstance(rd, RedditLayer)
    keys = rd.member.astype(np.int64) * rd.n_subs + rd.sub
    assert len(np.unique(keys)) == len(keys)


def test_only_platform_users_carry_edges(graph: SocialGraph, pop: Population) -> None:
    for name, layer in graph.layers.items():
        uses = pop.platform_use[:, PLATFORM_INDEX[name]]
        if isinstance(layer, DirectedLayer):
            ends = np.concatenate([layer.follower, layer.followee])
        elif isinstance(layer, FriendshipLayer):
            ends = np.concatenate([layer.a, layer.b])
        elif isinstance(layer, RedditLayer):
            ends = layer.member
        else:
            ends = layer.users
        assert uses[ends].all(), name


def test_twitter_in_degree_heavy_tailed(graph: SocialGraph) -> None:
    tw = graph.layers["twitter"]
    assert isinstance(tw, DirectedLayer)
    ind = tw.in_degree()[tw.users]
    assert ind.max() / np.median(ind) > 20


def test_friendship_symmetric_csr(graph: SocialGraph) -> None:
    fr = graph.layers["friendship"]
    assert isinstance(fr, FriendshipLayer)
    m = sp.csr_matrix((np.ones(len(fr.indices)), fr.indices, fr.indptr), shape=(fr.n, fr.n))
    assert (m != m.T).nnz == 0


def test_homophily_shares(graph: SocialGraph, pop: Population) -> None:
    main = np.argmax(pop.interests, axis=1)
    tw = graph.layers["twitter"]
    assert isinstance(tw, DirectedLayer)
    same_interest = (main[tw.follower] == main[tw.followee]).mean()
    assert same_interest >= GraphConfig().twitter_homophily
    fr = graph.layers["friendship"]
    assert isinstance(fr, FriendshipLayer)
    same_comm = (pop.community[fr.a] == pop.community[fr.b]).mean()
    assert same_comm > 0.6


def test_triadic_closure_raises_clustering(pop: Population) -> None:
    cfg_off, cfg_on = GraphConfig(triadic_closure=0.0), GraphConfig(triadic_closure=0.5)
    off = build_friendship(pop, cfg_off, np.random.default_rng(3)).stats()["clustering"]
    on = build_friendship(pop, cfg_on, np.random.default_rng(3)).stats()["clustering"]
    assert on > off


def test_youtube_creators_are_top_influence(graph: SocialGraph, pop: Population) -> None:
    yt = graph.layers["youtube"]
    assert isinstance(yt, YouTubeLayer)
    assert len(yt.creators) == round(GraphConfig().youtube_creator_share * len(yt.users))
    assert np.isin(yt.followee, yt.creators).all()  # subscribers only follow creators
    others = np.setdiff1d(yt.users, yt.creators)
    assert pop.influence[yt.creators].min() >= pop.influence[others].max()


# ----------------------------------------------------------------- push


def _dense_adjacency(layer: DirectedLayer | FriendshipLayer) -> sp.csr_matrix:
    """Reference: row = sender, column = receiver."""
    return sp.csr_matrix((np.ones(len(layer.indices)), layer.indices, layer.indptr), shape=(layer.n, layer.n))


def test_gather_rows_matches_python_loop() -> None:
    indptr = np.array([0, 2, 2, 5, 6])
    indices = np.array([1, 3, 0, 2, 3, 1], np.int32)
    cols, pos = gather_rows(indptr, indices, np.array([2, 0, 1, 3]))
    assert cols.tolist() == [0, 2, 3, 1, 3, 1]
    assert pos.tolist() == [0, 0, 0, 1, 1, 3]


@pytest.mark.parametrize("name", ["twitter", "instagram", "friendship", "youtube"])
def test_edge_push_matches_matrix_product(graph: SocialGraph, name: str) -> None:
    layer = graph.layers[name]
    assert isinstance(layer, DirectedLayer | FriendshipLayer)
    rng = np.random.default_rng(0)
    pool = layer.creators if isinstance(layer, YouTubeLayer) else layer.users
    sharers = rng.choice(pool, size=min(30, len(pool)), replace=False)
    x = np.zeros(layer.n)
    x[sharers] = 1.0
    expected = layer.reach * (_dense_adjacency(layer).T @ x)
    got = graph.push(name, sharers)
    assert got.dtype == np.float32 and got.shape == (layer.n,)
    np.testing.assert_allclose(got, expected, rtol=1e-6)


def test_push_with_no_sharers_is_zero(graph: SocialGraph) -> None:
    for name in graph.layers:
        out = graph.push(name, np.zeros(0, np.int64))
        assert out.shape == (graph.n,) and not out.any(), name


def test_reddit_push_matches_formula(graph: SocialGraph) -> None:
    rd = graph.layers["reddit"]
    assert isinstance(rd, RedditLayer)
    sharers = rd.users[:15]
    m = sp.csr_matrix((np.ones(len(rd.member)), (rd.member, rd.sub)), shape=(rd.n, rd.n_subs))
    x = np.zeros(rd.n)
    x[sharers] = 1
    score = m.T @ x
    intensity = rd.reach * score / np.sqrt(np.maximum(rd.sub_size, 1))
    np.testing.assert_allclose(rd.push(sharers), m @ intensity, rtol=1e-5)


def test_tiktok_push(graph: SocialGraph, pop: Population) -> None:
    tk = graph.layers["tiktok"]
    assert isinstance(tk, TikTokLayer)
    e1 = tk.push(np.arange(4), topic=2)
    e4 = tk.push(np.arange(16), topic=2)
    non_users = ~pop.platform_use[:, PLATFORM_INDEX["tiktok"]]
    assert not e1[non_users].any()
    users = tk.users
    np.testing.assert_allclose(e4[users], 2 * e1[users], rtol=1e-6)  # sqrt(16) / sqrt(4)
    fav = np.argmax(pop.interests[users], axis=1) == 2
    assert e1[users][fav].mean() > e1[users][~fav].mean()


# ----------------------------------------------------------------- stats, determinism, growth


def test_layer_stats(graph: SocialGraph) -> None:
    stats = graph.layer_stats()
    assert set(stats) == set(graph.layers) | {"overlap_jaccard"}
    tw = stats["twitter"]
    assert 0.0 <= tw["reciprocity"] <= 1.0 and 0.0 <= tw["clustering"] <= 1.0
    assert tw["in_degree"]["p50"] <= tw["in_degree"]["p99"] <= tw["in_degree"]["max"]
    assert all(0.0 <= v <= 1.0 for v in stats["overlap_jaccard"].values())
    assert "twitter~friendship" in stats["overlap_jaccard"]
    text = format_stats(stats)
    assert "[twitter]" in text and "[overlap]" in text


def test_same_seed_same_graph(pop: Population) -> None:
    g1 = SocialGraph.build(pop, GraphConfig(), np.random.default_rng(11), platforms=ALL_PLATFORMS)
    g2 = SocialGraph.build(pop, GraphConfig(), np.random.default_rng(11), platforms=ALL_PLATFORMS)
    for name in g1.layers:
        k1, k2 = g1.layers[name].edge_keys(), g2.layers[name].edge_keys()
        if k1 is not None and k2 is not None:
            np.testing.assert_array_equal(k1, k2)
    np.testing.assert_array_equal(g1.layers["reddit"].sub, g2.layers["reddit"].sub)  # type: ignore[attr-defined]


def test_sample_targets_respects_groups_and_weights() -> None:
    rng = np.random.default_rng(0)
    pool = np.arange(6)
    weights = np.array([1.0, 0.0, 3.0, 1.0, 1.0, 0.0])
    pool_group = np.array([0, 0, 0, 1, 1, 1])
    src_group = np.zeros(20_000, np.int32)
    t = sample_targets(rng, src_group, pool, weights, pool_group, homophily=1.0)
    assert set(np.unique(t)) == {0, 2}  # inside group 0, never the zero-weight node
    assert abs((t == 2).mean() - 0.75) < 0.02


def test_add_nodes_keeps_graph_valid() -> None:
    pop = Population.build(Config(n_agents=4_000, seed=2))
    n0 = pop.n
    rng = np.random.default_rng(5)
    g = SocialGraph.build(pop, GraphConfig(), rng, platforms=ALL_PLATFORMS)
    before = {name: layer.edge_keys() for name, layer in g.layers.items()}
    new_ids = pop.add_agents(500)
    g.add_nodes(pop, new_ids, rng)

    assert g.n == pop.n == n0 + 500
    for name, layer in g.layers.items():
        assert layer.n == pop.n, name
        out = g.push(name, layer.users[:10])
        assert out.shape == (pop.n,), name
        uses = pop.platform_use[:, PLATFORM_INDEX[name]]
        assert np.array_equal(np.sort(layer.users), np.flatnonzero(uses)), name
        old = before[name]
        if old is not None:
            # never removed: every old edge survives (keys re-based to the new N)
            a, b = old // n0, old % n0
            assert np.isin(a * pop.n + b, layer.edge_keys()).all(), name  # type: ignore[arg-type]

    for layer in _directed(g):
        assert np.all(layer.follower != layer.followee)
        keys = layer.follower.astype(np.int64) * layer.n + layer.followee
        assert len(np.unique(keys)) == len(keys)
        new_users = np.intersect1d(new_ids, layer.users)
        assert np.isin(new_users, layer.follower).mean() > 0.8, layer.name  # newcomers follow someone
    fr = g.layers["friendship"]
    assert isinstance(fr, FriendshipLayer)
    new_fr = np.intersect1d(new_ids, fr.users)
    assert (fr.degree()[new_fr] > 0).mean() > 0.8
    rd = g.layers["reddit"]
    assert isinstance(rd, RedditLayer)
    assert np.isin(np.intersect1d(new_ids, rd.users), rd.member).all()


# ----------------------------------------------------------------- the real population (#2)


def test_population_satisfies_graph_protocol(pop: Population) -> None:
    from marketsim.graph import GraphPopulation

    p: GraphPopulation = pop  # checked by mypy as well as at runtime
    assert p.n == len(pop.community) == pop.platform_use.shape[0]
    assert pop.platform_use.shape[1] == len(ALL_PLATFORMS)


def test_media_outlets(graph: SocialGraph, pop: Population) -> None:
    media = np.flatnonzero(pop.category == MEDIA)
    assert len(media) > 0
    fr = graph.layers["friendship"]
    assert isinstance(fr, FriendshipLayer)
    assert not np.isin(media, fr.users).any()  # outlets have no offline friends
    tw = graph.layers["twitter"]
    assert isinstance(tw, DirectedLayer)
    ind = tw.in_degree()
    assert np.median(ind[media]) > 5 * np.median(ind[tw.users])  # influence x50 draws followers


def test_negative_group_draws_from_whole_pool() -> None:
    """Community -1 (media) must not be read as 'the last community'."""
    rng = np.random.default_rng(0)
    pool = np.arange(10)
    pool_group = np.repeat([0, 1], 5)
    t = sample_targets(rng, np.full(20_000, -1), pool, np.ones(10), pool_group, homophily=1.0)
    assert abs((t >= 5).mean() - 0.5) < 0.02  # both groups, evenly; not all from group 1
