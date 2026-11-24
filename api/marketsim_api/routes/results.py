"""Stored results of finished runs (issue #18).

Single runs read `runs/<id>/result/`; Monte Carlo runs read `runs/<id>/mc/` (whose representative
run stands in for the per-run endpoints). Large float arrays can be sent packed:
`?encoding=b64` returns `{"dtype": "float32", "shape": [...], "b64": "..."}` instead of lists.
"""

from __future__ import annotations

import base64
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Query, status

from marketsim import montecarlo
from marketsim.config import ALL_PLATFORMS, CATEGORIES, TICKS_PER_DAY
from marketsim.graph import DirectedLayer, FriendshipLayer, RedditLayer
from marketsim.metrics import acf, excess_kurtosis, open_tick_returns
from marketsim.sim import FAMILY_COLUMNS, World, json_safe
from marketsim.sim import load as load_run

from ..config_schema import parameters_to_engine
from ..deps import StoreDep
from ..schemas import RunDetail, RunMode, RunStatus
from ..storage import NotFound, Store
from ..worker import NODE_SAMPLE, node_sample

router = APIRouter(prefix="/runs", tags=["results"])
Encoding = Annotated[Literal["json", "b64"], Query(description="b64 = packed float32 arrays")]


# --------------------------------------------------------------------------- loading + caches


class _LRU:
    def __init__(self, size: int) -> None:
        self.size, self.data, self.lock = size, OrderedDict[Any, Any](), threading.Lock()

    def get(self, key: Any, make: Callable[[], Any]) -> Any:
        with self.lock:
            if key in self.data:
                self.data.move_to_end(key)
                return self.data[key]
        value = make()
        with self.lock:
            self.data[key] = value
            while len(self.data) > self.size:
                self.data.popitem(last=False)
        return value


_results = _LRU(8)
_worlds = _LRU(2)


def _finished(store: Store, run_id: str) -> RunDetail:
    try:
        run = store.get_run(run_id)
    except NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found") from None
    if run.status not in (RunStatus.done, RunStatus.cancelled):
        raise HTTPException(status.HTTP_409_CONFLICT, f"run {run_id} is {run.status.value}; no results yet")
    return run


def _single_result(store: Store, run: RunDetail) -> dict[str, Any]:
    if run.mode == RunMode.single:
        path = store.run_dir(run.id) / "result"
    elif run.mode == RunMode.montecarlo:
        path = store.run_dir(run.id) / "mc" / "rep"
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{run.mode.value} runs have no price series")
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run.id} has no stored results")
    return _results.get(("run", str(path)), lambda: load_run(path))


def _mc(store: Store, run: RunDetail) -> montecarlo.MonteCarloResult:
    if run.mode != RunMode.montecarlo:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "only Monte Carlo runs have quantiles and paths")
    path = store.run_dir(run.id) / "mc"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run.id} has no stored results")
    return _results.get(("mc", str(path)), lambda: montecarlo.load(path))


def pack(a: np.ndarray, encoding: str) -> Any:
    if encoding == "b64":
        arr = np.ascontiguousarray(a, dtype="<f4")
        return {"dtype": "float32", "shape": list(arr.shape), "b64": base64.b64encode(arr.tobytes()).decode()}
    return np.round(np.asarray(a, np.float64), 6).tolist()


# --------------------------------------------------------------------------- price series


@router.get("/{run_id}/series")
def series(
    run_id: str,
    store: StoreDep,
    every: Annotated[int, Query(ge=1, le=TICKS_PER_DAY, description="Keep every n-th tick")] = 1,
    encoding: Encoding = "json",
) -> dict[str, Any]:
    """Per-tick price, V_true, volume, mean investor confidence, IV, ATM call, market-maker
    inventory and order imbalance, plus daily OHLC."""
    res = _single_result(store, _finished(store, run_id))
    s = res["series"]
    n = len(s["price"])
    idx = np.arange(0, n, every)
    if every > 1 and len(idx) and idx[-1] != n - 1:
        idx = np.r_[idx, n - 1]
    out = {k: pack(np.asarray(v)[idx], encoding) for k, v in s.items()}
    return {
        "n_ticks": n,
        "every": every,
        "tick": idx.tolist(),
        "series": out,
        "ohlc": np.asarray(res["ohlc"]).tolist(),
        "events": res["events"],
    }


@router.get("/{run_id}/quantiles")
def quantiles(run_id: str, store: StoreDep, encoding: Encoding = "json") -> dict[str, Any]:
    """Monte Carlo quantile bands (5/25/50/75/95%) of the price, and the mean V_true path."""
    mc = _mc(store, _finished(store, run_id))
    q = mc.quantiles()
    return {
        "n_runs": mc.n_runs,
        "n_ticks": int(mc.paths.shape[1]),
        "quantiles": {k: pack(v, encoding) for k, v in q.items()},
        "v_true": pack(mc.v_true.mean(axis=0), encoding),
        "summary": mc.summary(),
    }


@router.get("/{run_id}/paths")
def paths(
    run_id: str,
    store: StoreDep,
    sample: Annotated[int, Query(ge=1, le=1_000)] = 50,
    every: Annotated[int, Query(ge=1, le=TICKS_PER_DAY)] = 1,
    encoding: Encoding = "json",
) -> dict[str, Any]:
    """Up to `sample` simulated price paths (the first ones, in seed order)."""
    mc = _mc(store, _finished(store, run_id))
    n = mc.paths.shape[1]
    idx = np.arange(0, n, every)
    if idx[-1] != n - 1:  # always end on the final tick (terminal prices)
        idx = np.r_[idx, n - 1]
    p = mc.paths[:sample][:, idx]
    return {"seeds": mc.seeds[:sample], "every": every, "tick": idx.tolist(), "paths": pack(p, encoding)}


# --------------------------------------------------------------------------- narratives


@router.get("/{run_id}/awareness")
def awareness(
    run_id: str,
    store: StoreDep,
    every: Annotated[int, Query(ge=1, le=TICKS_PER_DAY)] = 1,
) -> dict[str, Any]:
    """Awareness of each event family over time, split by platform users and by category.

    `rows` columns follow `columns`: tick, root, total, one count per platform's users, one per
    category. Divide by `platform_sizes` / `category_sizes` for shares. `items` maps each item id
    to its own [tick, aware] rows while it was active."""
    res = _single_result(store, _finished(store, run_id))
    fam = np.asarray(res["family"])
    if every > 1 and len(fam):
        fam = fam[(fam[:, 0] % every == 0) | (fam[:, 0] == fam[:, 0].max())]
    families = []
    for f in res["summary"]["families"]:
        rows = fam[fam[:, 1] == f["root"]] if len(fam) else fam
        families.append({**f, "rows": rows.tolist()})
    meta = res["meta"]
    aw = np.asarray(res["awareness"])
    items: dict[str, list[list[int]]] = {}
    if len(aw):
        if every > 1:
            aw = aw[(aw[:, 0] % every == 0) | (aw[:, 0] == aw[:, 0].max())]
        for item in np.unique(aw[:, 1]):
            rows = aw[aw[:, 1] == item]
            items[str(int(item))] = rows[:, [0, 2]].tolist()
    return {
        "items": items,
        "columns": list(FAMILY_COLUMNS),
        "platforms": list(ALL_PLATFORMS),
        "categories": list(CATEGORIES),
        "n_nodes": meta["n_nodes"],
        "platform_sizes": meta.get("platform_sizes"),
        "category_sizes": meta.get("category_sizes"),
        "families": families,
    }


@router.get("/{run_id}/lineage")
def lineage(run_id: str, store: StoreDep) -> dict[str, Any]:
    """Every item ever created (id, parent, root, origin, sentiment, credibility, born, final
    awareness, shares, ...), for the narrative tree."""
    res = _single_result(store, _finished(store, run_id))
    return {"items": res["lineage"], "families": res["summary"]["families"]}


@router.get("/{run_id}/stylized-facts")
def stylized_facts(run_id: str, store: StoreDep, lags: Annotated[int, Query(ge=1, le=50)] = 10) -> Any:
    """Open-tick return histogram (in sd units) vs normal, kurtosis, and ACF of r and |r|.
    Monte Carlo runs pool every path."""
    run = _finished(store, run_id)
    if run.mode == RunMode.montecarlo:
        rows = list(_mc(store, run).paths)
    else:
        rows = [np.asarray(_single_result(store, run)["series"]["price"])]
    rets = [open_tick_returns(p) for p in rows]
    pooled = np.concatenate(rets)
    sd = float(pooled.std()) or 1e-12
    edges = np.linspace(-6, 6, 49)
    counts, _ = np.histogram(np.clip(pooled / sd, -6, 6), bins=edges)
    centres = 0.5 * (edges[1:] + edges[:-1])
    width = edges[1] - edges[0]
    return json_safe(
        {
            "n_returns": len(pooled),
            "return_sd": sd,
            "excess_kurtosis": excess_kurtosis(pooled),
            "histogram": {
                "centres": centres.tolist(),
                "density": (counts / max(len(pooled), 1) / width).tolist(),
                "normal": (np.exp(-0.5 * centres**2) / np.sqrt(2 * np.pi)).tolist(),
            },
            "acf_r": np.nanmean([acf(r, lags) for r in rets], axis=0).tolist(),
            "acf_abs_r": np.nanmean([acf(np.abs(r), lags) for r in rets], axis=0).tolist(),
            "band": 1.96 / float(np.sqrt(max(float(np.mean([len(r) for r in rets])), 1.0))),
        }
    )


# --------------------------------------------------------------------------- network


@dataclass
class _Node:
    id: int
    index: int  # position in the run's node sample (matches tick.node_seen and /node-seen)
    category: str
    influence: float
    community: int
    age: float
    knowledge: float
    impulsiveness: float
    wealth: float
    platforms: list[str]


def _world(run: RunDetail) -> World:
    cfg = parameters_to_engine(run.spec.parameters, run.spec.scenario.n_agents, run.spec.scenario.seed)
    key = (run.spec.scenario.n_agents, run.spec.scenario.seed, run.spec.parameters.model_dump_json())
    return _worlds.get(key, lambda: World.build(cfg))


def _layer_edges(layer: Any, sample: np.ndarray, in_sample: np.ndarray) -> np.ndarray:
    if isinstance(layer, DirectedLayer):  # follower -> followee
        a, b = layer.follower, layer.followee
    elif isinstance(layer, FriendshipLayer):
        a, b = layer.a, layer.b
    elif isinstance(layer, RedditLayer):
        # co-membership drawn as a ring through each sub's sampled members (not a clique)
        keep = in_sample[layer.member]
        m, s = layer.member[keep], layer.sub[keep]
        order = np.lexsort((m, s))
        m, s = m[order], s[order]
        same = s[1:] == s[:-1]
        a, b = m[:-1][same], m[1:][same]
    else:  # TikTok has no edges
        return np.zeros((0, 2), np.int64)
    keep = in_sample[a] & in_sample[b]
    return np.column_stack([a[keep], b[keep]]).astype(np.int64)


@router.get("/{run_id}/graph")
def graph(
    run_id: str,
    store: StoreDep,
    layer: Annotated[str, Query(description="A platform name, or 'all'")] = "all",
    sample: Annotated[int, Query(ge=10, le=NODE_SAMPLE)] = NODE_SAMPLE,
) -> dict[str, Any]:
    """The run's sampled nodes (the same sample streamed in `node_seen`), their attributes, the
    edges among them on the chosen layer(s), and every layer's statistics."""
    run = _finished(store, run_id)
    world = _world(run)
    pop, g = world.pop, world.graph
    if layer != "all" and layer not in g.layers:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"layer {layer!r} is not on in this run")
    full = node_sample(pop.n, run.spec.scenario.seed)
    pick = full[np.linspace(0, len(full) - 1, min(sample, len(full))).astype(np.int64)]
    in_sample = np.zeros(pop.n, bool)
    in_sample[pick] = True
    index_of = {int(v): i for i, v in enumerate(full)}
    nodes = [
        asdict(
            _Node(
                id=int(v),
                index=index_of[int(v)],
                category=CATEGORIES[int(pop.category[v])],
                influence=round(float(pop.influence[v]), 4),
                community=int(pop.community[v]),
                age=round(float(pop.age[v]), 1),
                knowledge=round(float(pop.knowledge[v]), 3),
                impulsiveness=round(float(pop.impulsiveness[v]), 3),
                wealth=round(float(pop.wealth[v]), 0),
                platforms=[p for j, p in enumerate(ALL_PLATFORMS) if pop.platform_use[v, j]],
            )
        )
        for v in pick
    ]
    names = list(g.layers) if layer == "all" else [layer]
    edges: list[list[Any]] = []
    for name in names:
        e = _layer_edges(g.layers[name], pick, in_sample)
        edges.extend([int(a), int(b), name] for a, b in e)
    return json_safe(
        {
            "n_nodes": pop.n,
            "layers": list(g.layers),
            "nodes": nodes,
            "edges": edges,
            "stats": g.layer_stats(),
        }
    )


@router.get("/{run_id}/node-seen")
def node_seen(run_id: str, store: StoreDep) -> dict[str, Any]:
    """When each sampled node became aware of each item: rows of [tick, sample index, item]."""
    run = _finished(store, run_id)
    path = store.run_dir(run_id) / "result" / "node_seen.npy"
    if run.mode != RunMode.single or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "only single runs record node awareness")
    return {"columns": ["tick", "index", "item"], "rows": np.load(path).tolist()}
