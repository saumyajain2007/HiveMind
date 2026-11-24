"""Belief and narrative update (issue #7, HANDOFF §4 M2 `beliefs.py`).

The user's four lines, in order:

* **Belief.** An item only moves Confidence if it is close enough to the current view:
  |eff_sentiment − confidence| < belief_tolerance. The step is

      mu0 · (0.5 + impulsiveness) · (1 − 0.5·knowledge) · cred_eff · (eff_sentiment − confidence)

  with cred_eff = (credibility · trust)^(1 + 2·knowledge) (trust: the platform the item arrived
  on), eff_sentiment = (1−α)·sentiment + α·clip(true_impact · impact_to_sentiment) and
  α = knowledge · (1 − complexity·(1 − knowledge)). Every update of a tick is computed from the
  same starting confidence and applied together with `np.add.at`, then clipped to [-1, 1].
  Agents who learn of a real event also update `perceived_value *= exp(α · true_impact)`.
* **Adopt.** On a belief-moving narrative item, with probability
  adopt_rate · (impulsiveness + 1 − knowledge) / 2, the agent takes it as its `held_narrative`
  and moves `narrative_bias` toward the item's sentiment (`adopt_step`). A belief-moving
  non-narrative item from the same family (an official denial of the rumour) drops the
  narrative and pulls the bias toward the denial instead.
* **Mutate.** Each agent who just decided to share a narrative item mutates it with probability
  mutate_rate · impulsiveness · (1 − knowledge). At most one child per parent per tick:
  sentiment ×1.4, credibility ×0.7, salience ×1.2 (all clipped). The mutators' shares of the
  parent are withdrawn; they seed the child instead.
* **Invent.** Checked hourly. If |1-day return| > invent_threshold, every online person who knows
  no recent item pointing the same way tries, with probability
  invent_rate · impulsiveness · (1 − knowledge) · |ret| / threshold. If anyone does, **one**
  invented narrative is created in the direction of the move (cooldown: one per direction per
  day), seeded by the inventors.

Then, every tick, holders of a narrative are pulled toward `narrative_bias` and every confidence
decays toward 0. Media outlets have no beliefs and are skipped throughout.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import MEDIA, TICKS_PER_DAY, TOPICS, Config
from .items import ItemStore
from .population import Population

MUTATE_SENTIMENT = 1.4  # HANDOFF: sentiment pushed further out
MUTATE_CREDIBILITY = 0.7
MUTATE_SALIENCE = 1.2
INVENT_EVERY = 4  # ticks (hourly)
INVENT_LOOKBACK = TICKS_PER_DAY  # "1-day return"
INVENT_MEMORY = TICKS_PER_DAY  # an item born within a day can serve as an explanation
INVENT_COMPLEXITY = 0.2


@dataclass
class BeliefResult:
    moved: int = 0  # (item, agent) pairs that moved a confidence
    blocked: int = 0  # pairs outside the agent's belief tolerance
    adopted: int = 0
    dropped: int = 0  # narratives given up after a debunking item
    children: list[int] = field(default_factory=list)  # item ids created by mutation
    invented: int = -1  # item id of an invented narrative, or -1


class Beliefs:
    def __init__(self, pop: Population, items: ItemStore, cfg: Config, rng: np.random.Generator) -> None:
        self.pop, self.items, self.cfg, self.rng = pop, items, cfg, rng
        self._last_invent = {1: -(10**9), -1: -(10**9)}  # direction -> tick of the last invention

    # ---------------------------------------------------------------- belief + adopt
    def absorb(self, slots: np.ndarray, agents: np.ndarray, trust: np.ndarray | None = None) -> BeliefResult:
        """Agents just became aware of items (aligned arrays). Moves confidence, perceived value
        and narratives. `trust` defaults to 1 (e.g. seeds who heard an event first-hand)."""
        out = BeliefResult()
        pop, items, bc = self.pop, self.items, self.cfg.belief
        slots = np.asarray(slots, np.int64)
        agents = np.asarray(agents, np.int64)
        trust = np.ones(len(slots)) if trust is None else np.asarray(trust, np.float64)
        person = pop.category[agents] != MEDIA
        slots, agents, trust = slots[person], agents[person], trust[person]
        if len(slots) == 0:
            return out

        k = pop.knowledge[agents]
        imp = pop.impulsiveness[agents]
        alpha = k * (1.0 - items.complexity[slots] * (1.0 - k))
        impact = items.true_impact[slots]
        eff = (1.0 - alpha) * items.sentiment[slots] + alpha * np.clip(
            impact * bc.impact_to_sentiment, -1.0, 1.0
        )
        conf = pop.confidence[agents]
        gap = eff - conf
        moves = np.abs(gap) < pop.belief_tolerance[agents]
        cred = np.clip(items.credibility[slots] * trust, 0.0, 1.0) ** (1.0 + 2.0 * k)
        step = bc.mu0 * (0.5 + imp) * (1.0 - 0.5 * k) * cred * gap
        np.add.at(pop.confidence, agents[moves], step[moves])
        np.clip(pop.confidence, -1.0, 1.0, out=pop.confidence)
        out.moved, out.blocked = int(moves.sum()), int((~moves).sum())

        real = impact != 0.0
        if real.any():
            log_pv = np.zeros(pop.n)
            np.add.at(log_pv, agents[real], alpha[real] * impact[real])
            touched = np.unique(agents[real])
            pop.perceived_value[touched] *= np.exp(log_pv[touched])

        # adopt narratives / drop them after a debunking item of the same family
        narrative = items.is_narrative[slots]
        p_adopt = bc.adopt_rate * (imp + 1.0 - k) / 2.0
        adopt = moves & narrative & (self.rng.random(len(slots)) < p_adopt)
        held = pop.held_narrative[agents]
        held_root = np.where(held >= 0, self._roots(held), -1)
        debunk = moves & ~narrative & (held_root >= 0) & (held_root == items.root[slots])
        for mask, adopting in ((debunk, False), (adopt, True)):
            if not mask.any():
                continue
            # one per agent per tick: the last pair for that agent wins (deterministic order)
            a, s = agents[mask][::-1], slots[mask][::-1]
            a, first = np.unique(a, return_index=True)
            s = s[first]
            pop.narrative_bias[a] += bc.adopt_step * (items.sentiment[s] - pop.narrative_bias[a])
            if adopting:
                pop.held_narrative[a] = items.item_id[s].astype(np.int32)
                out.adopted = len(a)
            else:
                pop.held_narrative[a] = -1
                out.dropped = len(a)
        return out

    def _roots(self, item_ids: np.ndarray) -> np.ndarray:
        lineage = self.items.lineage
        return np.array([lineage[int(i)].root if i >= 0 else -1 for i in item_ids], np.int64)

    # ---------------------------------------------------------------- mutate
    def mutate(self, tick: int, share_slots: np.ndarray, share_agents: np.ndarray) -> list[int]:
        """Sharers of narrative items may post a more extreme, less credible version instead.
        Returns the new items' ids (at most one per parent)."""
        pop, items = self.pop, self.items
        share_slots = np.asarray(share_slots, np.int64)
        share_agents = np.asarray(share_agents, np.int64)
        sel = items.is_narrative[share_slots] & (pop.category[share_agents] != MEDIA)
        s, a = share_slots[sel], share_agents[sel]
        if len(s) == 0:
            return []
        p = self.cfg.diffusion.mutate_rate * pop.impulsiveness[a] * (1.0 - pop.knowledge[a])
        hit = self.rng.random(len(s)) < p
        children = []
        for parent_slot in np.unique(s[hit]):
            ps = int(parent_slot)
            mutators = a[hit & (s == ps)]
            items.withdraw_shares(ps, mutators)
            child = items.create(
                sentiment=float(items.sentiment[ps]) * MUTATE_SENTIMENT,
                credibility=float(items.credibility[ps]) * MUTATE_CREDIBILITY,
                salience=float(items.salience[ps]) * MUTATE_SALIENCE,
                complexity=float(items.complexity[ps]),
                born=tick,
                origin="mutation",
                topic=TOPICS[int(items.topic[ps])],
                parent=int(items.item_id[ps]),
                is_narrative=True,
                seeds=mutators,
            )
            children.append(int(items.item_id[child]))
        return children

    # ---------------------------------------------------------------- invent
    def invent(self, tick: int, ret_1d: float, online: np.ndarray) -> int:
        """After a big unexplained move, online agents may make up a reason. Returns the new item
        id, or -1. Only runs on hourly ticks."""
        dc, bc, pop, items = self.cfg.diffusion, self.cfg.belief, self.pop, self.items
        if tick % INVENT_EVERY or abs(ret_1d) <= dc.invent_threshold:
            return -1
        direction = 1 if ret_1d > 0 else -1
        if tick - self._last_invent[direction] < TICKS_PER_DAY:
            return -1
        candidates = np.flatnonzero(online & (pop.category != MEDIA))
        explained = np.zeros(pop.n, bool)
        for slot in items.active_slots():
            same_way = np.sign(items.sentiment[slot]) == direction
            if same_way and tick - items.born[slot] < INVENT_MEMORY:
                explained |= items.aware[slot]
        candidates = candidates[~explained[candidates]]
        if len(candidates) == 0:
            return -1
        p = (
            dc.invent_rate
            * pop.impulsiveness[candidates]
            * (1.0 - pop.knowledge[candidates])
            * abs(ret_1d)
            / dc.invent_threshold
        )
        inventors = candidates[self.rng.random(len(candidates)) < np.clip(p, 0.0, 1.0)]
        if len(inventors) == 0:
            return -1
        self._last_invent[direction] = tick
        strength = float(np.clip(abs(ret_1d) / dc.invent_threshold * 0.4, 0.3, 1.0))
        slot = items.create(
            sentiment=direction * strength,
            credibility=bc.invent_credibility,
            salience=bc.invent_salience,
            complexity=INVENT_COMPLEXITY,
            born=tick,
            origin="invention",
            is_narrative=True,
            label="up" if direction > 0 else "down",
            seeds=inventors,
        )
        return int(items.item_id[slot])

    # ---------------------------------------------------------------- drift
    def drift(self) -> None:
        """Holders are pulled toward their narrative bias; every confidence decays toward 0."""
        pop, bc = self.pop, self.cfg.belief
        holders = (pop.held_narrative >= 0) & (pop.category != MEDIA)
        pop.confidence[holders] += bc.narrative_pull * (pop.narrative_bias[holders] - pop.confidence[holders])
        pop.confidence *= 1.0 - bc.confidence_decay
        np.clip(pop.confidence, -1.0, 1.0, out=pop.confidence)

    # ---------------------------------------------------------------- one tick
    def step(
        self,
        tick: int,
        seen_slots: np.ndarray,
        seen_agents: np.ndarray,
        seen_trust: np.ndarray | None,
        share_slots: np.ndarray,
        share_agents: np.ndarray,
        online: np.ndarray,
        ret_1d: float = 0.0,
    ) -> BeliefResult:
        out = self.absorb(seen_slots, seen_agents, seen_trust)
        out.children = self.mutate(tick, share_slots, share_agents)
        out.invented = self.invent(tick, ret_1d, online)
        self.drift()
        return out
