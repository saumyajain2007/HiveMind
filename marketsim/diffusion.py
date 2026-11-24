"""Platform diffusion (issue #6, HANDOFF §4 M2 `diffusion.py`).

"How far information travels in one cycle is determined by the nature of the event and
randomness." One `step(tick)`:

1. Online mask from each agent's activity hours; investors check more often while the market
   is open (`trading_online_boost`).
2. Exposure for every active item: each layer's `receivers(live sharers)` (reach applied, times
   `exposure_scale`),
   plus TV / push-alert broadcast on the first tick of media-carried items (official and
   outlet events, price headlines; it reaches people whether or not they are on social
   media) and TikTok's algorithmic feed. All items
   are combined as sparse (item, agent, exposure) triples, so the cost grows with the number of
   sharers' edges, not with N × items.
3. p_see = 1 − exp(−exposure · salience), only for agents online and not yet aware.
4. Attention cap: each agent takes in at most `attention_slots` new items per tick, the
   highest-scoring first.
5. Those (item, agent) pairs become aware.
6. Each newly aware agent may share the item (at most once per item). A share goes out from
   the next tick and stays in followers' feeds for `share_ttl` ticks, so followers who come
   online later in that window can still see it. Share probability:
   p = base_share · salience · (0.3 + impulsiveness)
       · (0.6 + 0.8·max(agreement, 0) + 0.4·|sentiment|·impulsiveness + 0.5·talking_your_book)
   where agreement = sentiment × confidence and talking_your_book = 1 when a holder of the stock
   meets a bullish item (v1 has no short positions).
7. Salience decays; faded items with nobody about to share them retire.

YouTube is the exception to "next step": a creator who decides to cover an item publishes
16-96 ticks later (`youtube_lag_ticks`), so their YouTube push is queued.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

import numpy as np

from .config import MARKET_CLOSE_TICK, MARKET_OPEN_TICK, MEDIA, NON_INVESTOR, TICKS_PER_DAY, Config
from .events import broadcast_hits
from .graph import SocialGraph, YouTubeLayer
from .items import ItemStore
from .population import Population

MINUTES_PER_TICK = 24 * 60 // TICKS_PER_DAY
BROADCAST_EXPOSURE = 1.0  # exposure added for an agent reached by TV / push alerts


@dataclass
class DiffusionResult:
    """What happened in one step. Pairs are aligned arrays (slot, agent)."""

    seen_slots: np.ndarray  # newly aware
    seen_agents: np.ndarray
    share_slots: np.ndarray  # decided to share (goes out next step)
    share_agents: np.ndarray
    online: int = 0
    candidates: int = 0  # (item, agent) pairs that passed the p_see draw before the cap
    exposure_pairs: int = 0
    retired: list[int] = field(default_factory=list)


def _empty() -> np.ndarray:
    return np.zeros(0, np.int64)


class Diffusion:
    def __init__(
        self,
        pop: Population,
        graph: SocialGraph,
        items: ItemStore,
        cfg: Config,
        rng: np.random.Generator,
    ) -> None:
        self.pop, self.graph, self.items, self.cfg, self.rng = pop, graph, items, cfg, rng
        self._yt_queue: list[tuple[int, int, int, np.ndarray]] = []  # (due tick, seq, item id, creators)
        self._yt_seq = 0

    # ---------------------------------------------------------------- 1. who is online
    def online_mask(self, tick: int) -> np.ndarray:
        pop = self.pop
        hour = (tick % TICKS_PER_DAY) * MINUTES_PER_TICK / 60.0
        p = pop.online_prob(hour, self.cfg.diffusion.base_online)
        in_day = tick % TICKS_PER_DAY
        if MARKET_OPEN_TICK <= in_day < MARKET_CLOSE_TICK:
            investor = (pop.category != NON_INVESTOR) & (pop.category != MEDIA)
            p = np.where(investor, p * self.cfg.trading.trading_online_boost, p)
        return self.rng.random(pop.n) < np.minimum(p, 1.0)

    # ---------------------------------------------------------------- YouTube lag
    def pending_youtube(self) -> set[int]:
        """Item ids with a YouTube upload still to come (kept from retiring)."""
        return {iid for _, _, iid, _ in self._yt_queue}

    def _queue_youtube(self, tick: int, item_id: int, sharers: np.ndarray) -> None:
        yt = self.graph.layers.get("youtube")
        if not isinstance(yt, YouTubeLayer) or len(sharers) == 0:
            return
        creators = sharers[np.isin(sharers, yt.creators)]
        if len(creators) == 0:
            return
        lo, hi = yt.lag_ticks
        lags = self.rng.integers(lo, hi + 1, len(creators))
        for lag in np.unique(lags):
            heapq.heappush(self._yt_queue, (tick + int(lag), self._yt_seq, item_id, creators[lags == lag]))
            self._yt_seq += 1

    def _due_youtube(self, tick: int) -> dict[int, np.ndarray]:
        due: dict[int, list[np.ndarray]] = {}
        while self._yt_queue and self._yt_queue[0][0] <= tick:
            _, _, iid, creators = heapq.heappop(self._yt_queue)
            due.setdefault(iid, []).append(creators)
        return {iid: np.concatenate(parts) for iid, parts in due.items()}

    # ---------------------------------------------------------------- the step
    def step(self, tick: int) -> DiffusionResult:
        pop, items, cfg, rng = self.pop, self.items, self.cfg, self.rng
        dc = cfg.diffusion
        n = pop.n
        if items.n_agents != n:
            items.resize(n)
        online = self.online_mask(tick)

        # 2. exposure triples from every layer
        slot_parts: list[np.ndarray] = []
        agent_parts: list[np.ndarray] = []
        w_parts: list[np.ndarray] = []

        forced_parts: list[np.ndarray] = []  # (slot * n + agent) keys reached by broadcast

        scale = dc.exposure_scale

        def add(slot: int, agents: np.ndarray, w: np.ndarray, social: bool = True) -> None:
            if len(agents):
                slot_parts.append(np.full(len(agents), slot, np.int64))
                agent_parts.append(agents)
                w_parts.append(w * scale if social else w)

        due_yt = self._due_youtube(tick)
        tiktok = self.graph.layers.get("tiktok")
        sharing_now: dict[int, np.ndarray] = {}
        for slot in items.active_slots():
            slot = int(slot)
            sharers = items.live_sharers(slot, tick)
            sharing_now[slot] = items.starting_sharers(slot, tick)
            topic = int(items.topic[slot])
            if len(sharers):
                for name, layer in self.graph.layers.items():
                    if name in ("youtube", "tiktok"):
                        continue
                    add(slot, *layer.receivers(sharers))
                if tiktok is not None:
                    on_tiktok = int(np.isin(sharers, tiktok.users).sum())
                    if on_tiktok:
                        add(slot, *tiktok.receivers(sharers, topic=topic, popularity=on_tiktok))
            creators = due_yt.get(int(items.item_id[slot]))
            if creators is not None:
                add(slot, *self.graph.layers["youtube"].receivers(creators))
            if items.born[slot] == tick and items.broadcast[slot]:
                hits = broadcast_hits(
                    float(items.salience[slot]), pop.media_attention, dc.broadcast_rate, rng
                )
                add(slot, hits, np.full(len(hits), BROADCAST_EXPOSURE, np.float32), social=False)
                forced_parts.append(np.full(len(hits), slot, np.int64) * n + hits)

        # Shares that start now schedule their creators' YouTube uploads.
        for slot, sharers in sharing_now.items():
            self._queue_youtube(tick, int(items.item_id[slot]), sharers)

        result = DiffusionResult(_empty(), _empty(), _empty(), _empty(), online=int(online.sum()))
        if slot_parts:
            forced = np.concatenate(forced_parts) if forced_parts else np.zeros(0, np.int64)
            self._absorb(tick, slot_parts, agent_parts, w_parts, online, forced, result)

        # 7. decay and retirement
        items.decay(dc.salience_decay)
        result.retired = items.retire_eligible(tick, keep=self.pending_youtube())
        items.sync_lineage()
        return result

    def _absorb(
        self,
        tick: int,
        slot_parts: list[np.ndarray],
        agent_parts: list[np.ndarray],
        w_parts: list[np.ndarray],
        online: np.ndarray,
        forced: np.ndarray,
        result: DiffusionResult,
    ) -> None:
        pop, items, cfg, rng = self.pop, self.items, self.cfg, self.rng
        dc = cfg.diffusion
        n = pop.n
        slots = np.concatenate(slot_parts)
        agents = np.concatenate(agent_parts)
        w = np.concatenate(w_parts).astype(np.float64)

        # keep agents who are online (or reached by broadcast) and have not seen the item,
        # then sum exposure per (item, agent)
        reached = online[agents]
        if len(forced):
            reached |= np.isin(slots * n + agents, forced)
        keep = reached & ~items.aware[slots, agents]
        slots, agents, w = slots[keep], agents[keep], w[keep]
        if len(slots) == 0:
            return
        keys, inv = np.unique(slots * n + agents, return_inverse=True)
        exposure = np.bincount(inv, weights=w)
        slots, agents = keys // n, keys % n
        result.exposure_pairs = len(keys)

        # 3. p_see
        score = exposure * items.salience[slots]
        hit = rng.random(len(score)) < 1.0 - np.exp(-score)
        slots, agents, score = slots[hit], agents[hit], score[hit]
        result.candidates = len(slots)
        if len(slots) == 0:
            return

        # 4. attention cap: per agent, highest score first
        order = np.lexsort((-score, agents))
        slots, agents = slots[order], agents[order]
        run_start = np.r_[0, np.flatnonzero(np.diff(agents)) + 1]
        run_len = np.diff(np.r_[run_start, len(agents)])
        rank = np.arange(len(agents)) - np.repeat(run_start, run_len)
        take = rank < dc.attention_slots
        slots, agents = slots[take], agents[take]

        # 5. awareness
        items.mark_aware(slots, agents)
        result.seen_slots, result.seen_agents = slots, agents

        # 6. sharing (goes out from the next tick)
        sent = items.sentiment[slots]
        imp = pop.impulsiveness[agents]
        agreement = np.maximum(sent * pop.confidence[agents], 0.0)
        book = ((pop.shares[agents] > 0) & (sent > 0)).astype(np.float64)
        p_share = (
            dc.base_share
            * items.salience[slots]
            * (0.3 + imp)
            * (0.6 + 0.8 * agreement + 0.4 * np.abs(sent) * imp + 0.5 * book)
        )
        share = rng.random(len(slots)) < np.clip(p_share, 0.0, 1.0)
        s_slots, s_agents = slots[share], agents[share]
        share_slot_out, share_agent_out = [], []
        for slot in np.unique(s_slots):
            added = items.add_sharers(int(slot), s_agents[s_slots == slot], start=tick + 1)
            share_slot_out.append(np.full(len(added), slot, np.int64))
            share_agent_out.append(added)
        if share_slot_out:
            result.share_slots = np.concatenate(share_slot_out)
            result.share_agents = np.concatenate(share_agent_out)
