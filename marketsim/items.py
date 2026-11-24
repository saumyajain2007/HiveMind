"""Active news / narrative items, awareness and lineage (issue #5, HANDOFF §4 M2 `items.py`).

An *item* is one piece of circulating content: an injected event, a mutation of a narrative,
an invented explanation, or a price headline. Items live in a fixed number of slots
(`max_items`). Per slot there are attribute arrays, and two boolean matrices of shape
(max_items, N):

* `aware[slot, agent]`: the agent has seen the item;
* `shared[slot, agent]`: the agent has shared it (each agent shares an item at most once).

Shares stay in feeds for `share_ttl` ticks: `share_log[slot]` holds (start tick, agents)
batches, live while start <= tick < start + share_ttl. A share decided at tick t starts at
t + 1; seeds start at the item's birth tick.

A slot is retired when its salience falls below `retire_salience` and nobody is about to share
it. Its final awareness is written to the lineage log first, and the slot is wiped before reuse.

The lineage log keeps every item ever created (id, parent, origin, sentiment, credibility,
born, final_aware, ...), so narrative trees survive slot reuse. Awareness of each *family*
(a root item and all its descendants) is kept as one boolean row per family, for the
family-level metrics of #10.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from .config import TOPICS
from .events import Event

ORIGINS = ("event", "mutation", "invention", "price_news")
_TOPIC = {t: i for i, t in enumerate(TOPICS)}


@dataclass
class LineageRecord:
    id: int
    parent: int  # parent item id, or -1
    root: int  # id of the family root (itself for roots)
    origin: str  # event / mutation / invention / price_news
    sentiment: float
    credibility: float
    salience: float  # at birth
    born: int  # tick
    is_narrative: bool
    topic: str
    event_id: int = -1  # source Event id for origin "event" / "price_news"
    kind: str = ""
    label: str | None = None
    final_aware: int = 0  # updated live while active; frozen at retirement
    total_shares: int = 0
    retired: int = -1  # tick, or -1 while active

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ItemStore:
    n_agents: int
    max_items: int = 128
    retire_salience: float = 0.03
    share_ttl: int = 32

    lineage: list[LineageRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        m, n = self.max_items, self.n_agents
        self.active = np.zeros(m, bool)
        self.item_id = np.full(m, -1, np.int64)
        self.sentiment = np.zeros(m)
        self.credibility = np.zeros(m)
        self.salience = np.zeros(m)
        self.complexity = np.zeros(m)
        self.true_impact = np.zeros(m)
        self.topic = np.zeros(m, np.int32)
        self.parent = np.full(m, -1, np.int64)
        self.root = np.full(m, -1, np.int64)
        self.is_narrative = np.zeros(m, bool)
        self.origin = np.zeros(m, np.int8)  # index into ORIGINS
        self.born = np.zeros(m, np.int64)
        self.total_shares = np.zeros(m, np.int64)
        self.broadcast = np.zeros(m, bool)  # carried by TV / push alerts on its first tick
        self.aware = np.zeros((m, n), bool)
        self.shared = np.zeros((m, n), bool)
        self.share_log: list[list[tuple[int, np.ndarray]]] = [[] for _ in range(m)]
        self.slot_of: dict[int, int] = {}  # active item id -> slot
        self.family_aware: dict[int, np.ndarray] = {}  # root id -> bool (N,)
        self.evicted = 0  # active items dropped because every slot was full

    # ---------------------------------------------------------------- queries
    def active_slots(self) -> np.ndarray:
        return np.flatnonzero(self.active)

    def record(self, item_id: int) -> LineageRecord:
        return self.lineage[item_id]

    def aware_count(self, slot: int) -> int:
        return int(self.aware[slot].sum())

    def family_of(self, root_id: int) -> list[int]:
        """Ids of `root_id` and all its descendants, in creation order."""
        members = {root_id}
        out = []
        for rec in self.lineage:  # parents are always created before children
            if rec.id == root_id or rec.parent in members:
                members.add(rec.id)
                out.append(rec.id)
        return out

    def family_aware_count(self, root_id: int) -> int:
        row = self.family_aware.get(root_id)
        return int(row.sum()) if row is not None else 0

    # ---------------------------------------------------------------- creation
    def create(
        self,
        *,
        sentiment: float,
        credibility: float,
        salience: float,
        complexity: float,
        born: int,
        origin: str,
        true_impact: float = 0.0,
        topic: str = "finance",
        parent: int = -1,
        is_narrative: bool = False,
        event_id: int = -1,
        kind: str = "",
        label: str | None = None,
        seeds: np.ndarray | None = None,
        broadcast: bool = False,
    ) -> int:
        """Create an item and return its slot. `seeds` know it and share it from `born`."""
        if origin not in ORIGINS:
            raise ValueError(f"unknown origin {origin!r}")
        if parent >= 0 and not 0 <= parent < len(self.lineage):
            raise ValueError(f"unknown parent item {parent}")
        slot = self._free_slot(born)
        item_id = len(self.lineage)
        root = self.lineage[parent].root if parent >= 0 else item_id
        self.active[slot] = True
        self.item_id[slot] = item_id
        self.sentiment[slot] = float(np.clip(sentiment, -1.0, 1.0))
        self.credibility[slot] = float(np.clip(credibility, 0.0, 1.0))
        self.salience[slot] = float(np.clip(salience, 0.0, 1.0))
        self.complexity[slot] = float(np.clip(complexity, 0.0, 1.0))
        self.true_impact[slot] = float(true_impact)
        self.topic[slot] = _TOPIC[topic]
        self.parent[slot] = parent
        self.root[slot] = root
        self.is_narrative[slot] = is_narrative
        self.origin[slot] = ORIGINS.index(origin)
        self.born[slot] = born
        self.total_shares[slot] = 0
        self.broadcast[slot] = broadcast
        self.slot_of[item_id] = slot
        self.family_aware.setdefault(root, np.zeros(self.n_agents, bool))
        self.lineage.append(
            LineageRecord(
                id=item_id,
                parent=parent,
                root=root,
                origin=origin,
                sentiment=float(self.sentiment[slot]),
                credibility=float(self.credibility[slot]),
                salience=float(self.salience[slot]),
                born=born,
                is_narrative=is_narrative,
                topic=topic,
                event_id=event_id,
                kind=kind,
                label=label,
            )
        )
        if seeds is not None and len(seeds):
            seeds = np.unique(np.asarray(seeds, np.int64))
            self.mark_aware(np.full(len(seeds), slot), seeds)
            self.add_sharers(slot, seeds, start=born)
        return slot

    def from_event(
        self, event: Event, tick: int, seeds: np.ndarray | None = None, label: str | None = None
    ) -> int:
        """Item for an injected event (origin `price_news` for `price_move` events).

        Official and outlet events, and price headlines, are carried by TV / push alerts on their
        first tick; rumours from anonymous accounts, influencers or insiders are not.
        """
        return self.create(
            sentiment=event.sentiment,
            credibility=event.credibility,
            salience=event.salience,
            complexity=event.complexity,
            true_impact=event.true_impact,
            topic=event.topic,
            parent=self.item_for_event(event.parent),
            is_narrative=event.is_narrative,
            origin="price_news" if event.kind == "price_move" else "event",
            born=tick,
            event_id=event.id,
            kind=event.kind,
            label=label,
            seeds=seeds,
            broadcast=event.seeding in ("official", "outlet") or event.kind == "price_move",
        )

    def item_for_event(self, event_id: int) -> int:
        """Item id created for `event_id` (follow-up events hang under their parent's item)."""
        if event_id < 0:
            return -1
        for rec in reversed(self.lineage):
            if rec.event_id == event_id and rec.origin == "event":
                return rec.id
        return -1

    # ---------------------------------------------------------------- awareness / sharing
    def mark_aware(self, slots: np.ndarray, agents: np.ndarray) -> None:
        slots = np.asarray(slots, np.int64)
        agents = np.asarray(agents, np.int64)
        self.aware[slots, agents] = True
        for root in np.unique(self.root[slots]):
            sel = self.root[slots] == root
            self.family_aware[int(root)][agents[sel]] = True

    def add_sharers(self, slot: int, agents: np.ndarray, start: int) -> np.ndarray:
        """`agents` share `slot` from tick `start` for `share_ttl` ticks. Agents who already
        shared it are ignored (each agent shares an item at most once). Returns those added."""
        agents = np.unique(np.asarray(agents, np.int64))
        agents = agents[~self.shared[slot, agents]]
        if len(agents):
            self.shared[slot, agents] = True
            self.share_log[slot].append((int(start), agents))
            self.total_shares[slot] += len(agents)
            self.lineage[int(self.item_id[slot])].total_shares += len(agents)
        return agents

    def live_sharers(self, slot: int, tick: int) -> np.ndarray:
        """Agents whose share of `slot` is in feeds at `tick`; drops expired batches."""
        log = [(s, a) for s, a in self.share_log[slot] if s + self.share_ttl > tick]
        self.share_log[slot] = log
        live = [a for s, a in log if s <= tick]
        return np.concatenate(live) if live else np.zeros(0, np.int64)

    def starting_sharers(self, slot: int, tick: int) -> np.ndarray:
        """Agents whose share of `slot` starts exactly at `tick`."""
        parts = [a for s, a in self.share_log[slot] if s == tick]
        return np.concatenate(parts) if parts else np.zeros(0, np.int64)

    def has_pending_shares(self, slot: int, tick: int) -> bool:
        return any(s + self.share_ttl > tick for s, _ in self.share_log[slot])

    # ---------------------------------------------------------------- lifecycle
    def decay(self, factor: float) -> None:
        self.salience[self.active] *= factor

    def retire_eligible(self, tick: int, keep: set[int] | None = None) -> list[int]:
        """Retire faded items whose shares have all left the feeds. `keep`: item ids to hold
        on to (e.g. with pending YouTube uploads). Returns retired item ids."""
        keep = keep or set()
        out = []
        for slot in self.active_slots():
            iid = int(self.item_id[slot])
            faded = self.salience[slot] < self.retire_salience
            if faded and not self.has_pending_shares(int(slot), tick) and iid not in keep:
                self._retire(int(slot), tick)
                out.append(iid)
        return out

    def sync_lineage(self) -> None:
        """Copy live awareness counts of active items into the lineage log."""
        for slot in self.active_slots():
            self.lineage[int(self.item_id[slot])].final_aware = self.aware_count(int(slot))

    def resize(self, n_agents: int) -> None:
        """Grow the agent dimension (nodes are only ever added)."""
        if n_agents < self.n_agents:
            raise ValueError("agents are never removed")
        extra = n_agents - self.n_agents
        if extra == 0:
            return
        pad = np.zeros((self.max_items, extra), bool)
        self.aware = np.concatenate([self.aware, pad], axis=1)
        self.shared = np.concatenate([self.shared, pad.copy()], axis=1)
        for root, row in self.family_aware.items():
            self.family_aware[root] = np.concatenate([row, np.zeros(extra, bool)])
        self.n_agents = n_agents

    def _retire(self, slot: int, tick: int) -> None:
        iid = int(self.item_id[slot])
        rec = self.lineage[iid]
        rec.final_aware = self.aware_count(slot)
        rec.retired = tick
        self.slot_of.pop(iid, None)
        self.active[slot] = False
        self.item_id[slot] = -1
        self.aware[slot] = False  # wipe before the slot is reused
        self.shared[slot] = False
        self.share_log[slot] = []
        self.salience[slot] = 0.0

    def _free_slot(self, tick: int) -> int:
        free = np.flatnonzero(~self.active)
        if len(free):
            return int(free[0])
        # Every slot is busy: drop the faintest item (its record stays in the lineage).
        slot = int(np.argmin(np.where(self.active, self.salience, np.inf)))
        self._retire(slot, tick)
        self.evicted += 1
        return slot
