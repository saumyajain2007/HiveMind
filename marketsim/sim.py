"""The simulation loop, metrics, determinism and the `on_tick` hook (issue #10, HANDOFF §4 M4).

Order of each tick (from the notes' loop):

1. Inject due events: seeds, an item, V_true for real events, funds read official news.
2. Diffusion (profitable holders talk up their book).
3. Beliefs and narratives (mutations; hourly inventions after big unexplained moves).
4. If the market is open: retail and firm orders, the batch auction, fills. Losing holders may
   panic inside the retail orders.
5. Feedback for the next tick: a move past `price_news_threshold` since the last price headline
   queues a `price_move` event (seeding "outlet", sentiment clip(8·ret), true_impact 0), and
   chartists see the new momentum.

Every run is fully determined by (config, scenario, seed). The population and graph come from
`config.seed` (the *world*); `seed` drives the dynamics, so Monte Carlo can reuse one world
with many dynamics seeds.

The engine never imports the API: `on_tick(frame)` gets a JSON-ready `TickFrame`, and
`should_stop()` is polled before each tick for cancellation.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, TypedDict

import numpy as np

from .beliefs import Beliefs
from .config import ALL_PLATFORMS, CATEGORIES, MEDIA, TICKS_PER_DAY, Config
from .diffusion import Diffusion
from .events import Event, EventQueue, apply_to_market, assign_ids, event_from_dict, seed_agents
from .firms import build_firms
from .graph import DirectedLayer, FriendshipLayer, SocialGraph
from .items import ORIGINS, ItemStore
from .market import MarketState, is_market_open
from .metrics import max_drawdown, stylized_facts
from .population import Population
from .trading import Trading

ENGINE_VERSION = "0.1.0"
SERIES = (
    "price",
    "v_true",
    "volume",
    "confidence",
    "iv",
    "atm_call",
    "mm_inventory",
    "imbalance",
    "online",
    "active_items",
)
AWARENESS_COLUMNS = ("tick", "item", "aware")
FAMILY_COLUMNS = ("tick", "root", "total", *ALL_PLATFORMS, *CATEGORIES)
PRICE_NEWS_CREDIBILITY = 0.9
PRICE_NEWS_COMPLEXITY = 0.1


class TickFrame(TypedDict, total=False):
    """One tick, JSON-ready. `born` holds event / narrative messages for items born this tick;
    `node_seen` holds [sample index, item id] pairs that became aware this tick."""

    tick: int
    price: float
    v_true: float
    volume: float
    confidence: float
    iv: float
    atm_call: float
    mm_inventory: float
    imbalance: float
    awareness: dict[str, int]
    born: list[dict[str, Any]]
    node_seen: list[list[int]]


# --------------------------------------------------------------------------- scenario + world


@dataclass
class Scenario:
    events: list[Event] = field(default_factory=list)
    labels: dict[int, str] = field(default_factory=dict)  # event id -> headline text

    @classmethod
    def from_dicts(cls, events: Iterable[Mapping[str, Any]]) -> Scenario:
        """Strictly validated events (see `event_from_dict`); a `label` key becomes a headline."""
        raw = list(events)
        evs = [event_from_dict(d) for d in raw]
        assign_ids(evs)
        labels = {e.id: str(d["label"]) for e, d in zip(evs, raw, strict=True) if d.get("label")}
        return cls(evs, labels)


@dataclass
class World:
    """The parts of a run that come from `config.seed`: the population and the social graph."""

    pop: Population
    graph: SocialGraph

    @classmethod
    def build(cls, cfg: Config) -> World:
        pop = Population.build(cfg)
        graph = SocialGraph.build(pop, cfg.graph, np.random.default_rng([cfg.seed, 1]))
        return cls(pop, graph)


def connectedness(pop: Population, graph: SocialGraph) -> np.ndarray:
    """Total ties per agent (followers on directed layers + friends), used to seed insiders."""
    deg = np.zeros(pop.n)
    for layer in graph.layers.values():
        if isinstance(layer, DirectedLayer):
            deg += layer.in_degree()
        elif isinstance(layer, FriendshipLayer):
            deg += layer.degree()
    return deg


def price_news_event(ret: float, tick: int) -> tuple[Event, str]:
    pct = 100.0 * math.expm1(ret)
    ev = Event(
        tick=tick,
        kind="price_move",
        ticker=0,
        true_impact=0.0,
        sentiment=float(np.clip(8.0 * ret, -1.0, 1.0)),
        credibility=PRICE_NEWS_CREDIBILITY,
        salience=float(np.clip(0.4 + 5.0 * abs(ret), 0.0, 1.0)),
        complexity=PRICE_NEWS_COMPLEXITY,
        seeding="outlet",
    )
    return ev, f"Stock {'up' if pct > 0 else 'down'} {abs(pct):.1f}%"


# --------------------------------------------------------------------------- simulation


class Simulation:
    def __init__(
        self,
        config: Config,
        scenario: Scenario | None = None,
        seed: int | None = None,
        *,
        world: World | None = None,
        on_tick: Callable[[TickFrame], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        node_sample: np.ndarray | None = None,
    ) -> None:
        self.cfg = cfg = config
        self.seed = cfg.seed if seed is None else int(seed)
        self.scenario = scenario or Scenario()
        world = world or World.build(cfg)
        self.pop = pop = copy.deepcopy(world.pop)  # the dynamics change state arrays
        self.graph = world.graph
        streams = [np.random.default_rng(s) for s in np.random.SeedSequence([self.seed, 7]).spawn(5)]
        dc = cfg.diffusion
        self.items = ItemStore(pop.n, dc.max_items, dc.retire_salience, dc.share_ttl)
        self.diffusion = Diffusion(pop, self.graph, self.items, cfg, streams[0])
        self.beliefs = Beliefs(pop, self.items, cfg, streams[1])
        self.trading = Trading(pop, cfg, streams[2])
        self.market_rng, self.event_rng = streams[3], streams[4]
        self.market = MarketState(cfg.market)
        self.props, self.funds = build_firms(cfg.market, float(pop.wealth[pop.investor_ids].sum()))
        self.queue = EventQueue(replace(e) for e in self.scenario.events)
        self.labels = dict(self.scenario.labels)
        self.connectedness = connectedness(pop, self.graph)
        self.on_tick, self.should_stop = on_tick, should_stop
        self.node_sample = None if node_sample is None else np.asarray(node_sample, np.int64)
        self._sample_seen: dict[int, np.ndarray] = {}
        self.tick = 0
        self.cancelled = False
        self._headline_price = self.market.price
        self._series: dict[str, list[float]] = {k: [] for k in SERIES}
        self._aware_rows: list[np.ndarray] = []
        self._family_rows: list[np.ndarray] = []
        self.events_log: list[dict[str, Any]] = []
        self._investors = pop.investor_ids
        self.trading.update_fitness(0.0)  # sets every investor's weights from the priors
        self.trading.equilibrate(self.market)

    # ---------------------------------------------------------------- one tick
    def step(self) -> TickFrame | None:
        t = self.tick
        pop, items, market = self.pop, self.items, self.market
        born: list[dict[str, Any]] = []

        # 1. events
        for ev in self.queue.pop_due(t):
            born.append(self._inject(ev, t))

        # 2. diffusion
        self.diffusion.price = market.price
        dr = self.diffusion.step(t)
        online = dr.online_mask if dr.online_mask is not None else np.zeros(pop.n, bool)

        # 3. beliefs and narratives
        ret_1d = float(market.momentum(TICKS_PER_DAY))
        br = self.beliefs.step(
            t,
            dr.seen_slots,
            dr.seen_agents,
            dr.seen_trust,
            dr.share_slots,
            dr.share_agents,
            online,
            ret_1d,
        )
        for iid in [*br.children, *([br.invented] if br.invented >= 0 else [])]:
            born.append(self._narrative_msg(iid))

        # 4. market
        volume = imbalance = 0.0
        if is_market_open(t):
            retail = self.trading.orders(market, online)
            firm_p, firm_f = self.props.orders(market), self.funds.orders(market)
            q = np.concatenate([retail.qty, firm_p.qty, firm_f.qty])
            lim = np.concatenate([retail.limit, firm_p.limit, firm_f.limit])
            held = float(
                pop.shares.sum()
                + np.maximum(self.props.shares, 0).sum()
                + np.maximum(self.funds.shares, 0).sum()
            )
            buy = q > 0
            res = market.clear(q[buy], lim[buy], -q[~buy], lim[~buy], held, self.market_rng)
            self.trading.settle(retail, res.price)
            self.props.settle(firm_p, res.price)
            self.funds.settle(firm_f, res.price)
            self.props.observe(retail)
            imbalance = self.props.imbalance
            market.record_tick(t, res)
            self.trading.update_fitness(res.log_return)
            volume = res.volume
            # 5. feedback: big moves become news on the next tick
            move = math.log(market.price / self._headline_price)
            if abs(move) > self.cfg.diffusion.price_news_threshold:
                ev, label = price_news_event(move, t + 1)
                ev = self.queue.push(ev)
                self.labels[ev.id] = label
                self._headline_price = market.price
        else:
            market.record_tick(t)
        self.trading.remember_signals(market)

        # metrics
        inv = self._investors
        conf = float(pop.confidence[inv].mean()) if len(inv) else 0.0
        act = items.active_slots()
        counts = items.aware[act].sum(axis=1) if len(act) else np.zeros(0, np.int64)
        ids = items.item_id[act]
        if len(act):
            self._aware_rows.append(np.column_stack([np.full(len(act), t), ids, counts]))
            self._record_families(t, np.unique(items.root[act]))
        values = {
            "price": market.price,
            "v_true": market.v_true,
            "volume": volume,
            "confidence": conf,
            "iv": market.iv_annual(t),
            "atm_call": market.atm_call[-1],
            "mm_inventory": market.mm_inventory,
            "imbalance": imbalance,
            "online": float(online.sum()),
            "active_items": float(len(act)),
        }
        for k, v in values.items():
            self._series[k].append(float(v))

        frame: TickFrame | None = None
        if self.on_tick is not None:
            frame = {
                "tick": t,
                "price": market.price,
                "v_true": market.v_true,
                "volume": volume,
                "confidence": conf,
                "iv": values["iv"],
                "atm_call": values["atm_call"],
                "mm_inventory": market.mm_inventory,
                "imbalance": imbalance,
                "awareness": {str(int(i)): int(c) for i, c in zip(ids, counts, strict=True)},
                "born": born,
            }
            if self.node_sample is not None:
                frame["node_seen"] = self._node_seen(act)
            self.on_tick(frame)
        self.tick += 1
        return frame

    def run(self, n_ticks: int) -> dict[str, Any]:
        for _ in range(n_ticks):
            if self.should_stop is not None and self.should_stop():
                self.cancelled = True
                break
            self.step()
        return self.results()

    # ---------------------------------------------------------------- helpers
    def _inject(self, ev: Event, t: int) -> dict[str, Any]:
        seeds = seed_agents(ev, self.pop, self.event_rng, connectedness=self.connectedness)
        label = self.labels.get(ev.id)
        slot = self.items.from_event(ev, t, seeds=seeds, label=label)
        self.beliefs.absorb(np.full(len(seeds), slot), seeds)
        apply_to_market(ev, self.market)
        self.funds.on_event(ev, self.market, t)
        item = int(self.items.item_id[slot])
        msg: dict[str, Any] = {
            "type": "event",
            "tick": t,
            "id": ev.id,
            "item": item,
            "parent": self.items.lineage[item].parent,
            "kind": ev.kind,
            "seeding": ev.seeding,
            "sentiment": ev.sentiment,
            "credibility": ev.credibility,
            "salience": ev.salience,
            "true_impact": ev.true_impact,
        }
        if label:
            msg["label"] = label
        self.events_log.append({**ev.to_dict(), "item": item, "injected": t, "label": label})
        return msg

    def _narrative_msg(self, iid: int) -> dict[str, Any]:
        rec = self.items.lineage[iid]
        msg: dict[str, Any] = {
            "type": "narrative",
            "tick": rec.born,
            "id": rec.id,
            "parent": rec.parent,
            "origin": rec.origin,
            "sentiment": rec.sentiment,
            "credibility": rec.credibility,
        }
        if rec.label:
            msg["label"] = rec.label
        return msg

    def _record_families(self, t: int, roots: np.ndarray) -> None:
        pop = self.pop
        rows = []
        for root in roots:
            row = self.items.family_aware[int(root)]
            plat = np.count_nonzero(pop.platform_use[row], axis=0)
            cats = np.bincount(pop.category[row], minlength=len(CATEGORIES))
            rows.append(np.concatenate([[t, root, row.sum()], plat, cats]))
        if rows:
            self._family_rows.append(np.asarray(rows, np.int64))

    def _node_seen(self, act: np.ndarray) -> list[list[int]]:
        sample = self.node_sample
        assert sample is not None
        sample = sample[sample < self.pop.n]
        out: list[list[int]] = []
        live = set()
        for slot in act:
            iid = int(self.items.item_id[slot])
            live.add(iid)
            cur = self.items.aware[slot, sample]
            prev = self._sample_seen.get(iid)
            new = cur if prev is None else cur & ~prev
            out.extend([int(i), iid] for i in np.flatnonzero(new))
            self._sample_seen[iid] = cur
        for iid in set(self._sample_seen) - live:
            del self._sample_seen[iid]
        return out

    # ---------------------------------------------------------------- results
    def results(self) -> dict[str, Any]:
        self.items.sync_lineage()
        series = {k: np.asarray(v, np.float64) for k, v in self._series.items()}
        aware = (
            np.concatenate(self._aware_rows) if self._aware_rows else np.zeros((0, len(AWARENESS_COLUMNS)))
        ).astype(np.int64)
        family = (
            np.concatenate(self._family_rows) if self._family_rows else np.zeros((0, len(FAMILY_COLUMNS)))
        ).astype(np.int64)
        ohlc = np.asarray(self.market.ohlc, np.float64).reshape(-1, 4)
        lineage = [r.to_dict() for r in self.items.lineage]
        meta = {
            "engine_version": ENGINE_VERSION,
            "n_agents": self.cfg.n_agents,
            "n_nodes": self.pop.n,
            "n_media": int((self.pop.category == MEDIA).sum()),
            "world_seed": self.cfg.seed,
            "seed": self.seed,
            "n_ticks": self.tick,
            "ticks_per_day": TICKS_PER_DAY,
            "cancelled": self.cancelled,
            "category_sizes": np.bincount(self.pop.category, minlength=len(CATEGORIES)).tolist(),
            "platform_sizes": self.pop.platform_use.sum(axis=0).tolist(),
        }
        return {
            "meta": meta,
            "series": series,
            "awareness": aware,
            "family": family,
            "ohlc": ohlc,
            "lineage": lineage,
            "events": list(self.events_log),
            "summary": summarize(series, family, lineage, meta, self.pop.n),
        }


# --------------------------------------------------------------------------- summary + io


def summarize(
    series: Mapping[str, np.ndarray],
    family: np.ndarray,
    lineage: list[dict[str, Any]],
    meta: Mapping[str, Any],
    n_nodes: int,
) -> dict[str, Any]:
    price = series["price"]
    p0 = float(price[0]) if len(price) else 0.0
    origins = [r["origin"] for r in lineage]
    families = []
    for root in sorted({r["root"] for r in lineage}):
        rows = family[family[:, 1] == root] if len(family) else family
        rec = lineage[root]
        peak = int(rows[:, 2].max()) if len(rows) else int(rec["final_aware"])
        families.append(
            {
                "root": root,
                "origin": rec["origin"],
                "kind": rec["kind"],
                "label": rec["label"],
                "members": sum(1 for r in lineage if r["root"] == root),
                "aware": peak,
                "share": peak / n_nodes if n_nodes else 0.0,
            }
        )
    out: dict[str, Any] = {
        "n_ticks": int(meta["n_ticks"]),
        "days": int(meta["n_ticks"]) / TICKS_PER_DAY,
        "cancelled": bool(meta["cancelled"]),
        "initial_price": p0,
        "final_price": float(price[-1]) if len(price) else 0.0,
        "return": float(price[-1] / p0 - 1.0) if len(price) and p0 else 0.0,
        "v_true_final": float(series["v_true"][-1]) if len(price) else 0.0,
        "max_drawdown": max_drawdown(price),
        "total_volume": float(series["volume"].sum()),
        "mean_confidence_final": float(series["confidence"][-1]) if len(price) else 0.0,
        "n_items": len(lineage),
        **{f"n_{o}": origins.count(o) for o in ORIGINS},
        "families": families,
    }
    if len(price) > 1:
        out["stylized_facts"] = stylized_facts(price)
    return json_safe(out)


def json_safe(x: Any) -> Any:
    """Replace NaN / inf with None so the summary is valid JSON."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: json_safe(v) for k, v in x.items()}
    if isinstance(x, list):
        return [json_safe(v) for v in x]
    return x


def save(results: Mapping[str, Any], path: str | Path) -> Path:
    """Write a results dict to a folder: metrics.npz + lineage / events / summary / meta JSON."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    arrays = {f"series_{k}": v for k, v in results["series"].items()}
    arrays.update(awareness=results["awareness"], family=results["family"], ohlc=results["ohlc"])
    np.savez_compressed(path / "metrics.npz", **arrays)
    for name in ("lineage", "events", "summary", "meta"):
        (path / f"{name}.json").write_text(json.dumps(results[name], indent=1), encoding="utf-8")
    return path


def load(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    with np.load(path / "metrics.npz") as z:
        series = {k[len("series_") :]: z[k] for k in z.files if k.startswith("series_")}
        out: dict[str, Any] = {
            "series": series,
            "awareness": z["awareness"],
            "family": z["family"],
            "ohlc": z["ohlc"],
        }
    for name in ("lineage", "events", "summary", "meta"):
        out[name] = json.loads((path / f"{name}.json").read_text(encoding="utf-8"))
    return out


def run(
    config: Config, scenario: Scenario | None = None, n_ticks: int | None = None, seed: int | None = None
) -> dict[str, Any]:
    """Convenience: build everything and run `n_ticks` (default: 5 days)."""
    sim = Simulation(config, scenario, seed)
    return sim.run(5 * TICKS_PER_DAY if n_ticks is None else n_ticks)
