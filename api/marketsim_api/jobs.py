"""Job execution and live-stream fan-out (issue #17).

    POST /runs ──► JobRegistry.submit ──► pool (processes) ──► worker.execute
                                                                  │ queue: (run_id, kind, payload)
    WS /runs/{id}/stream ◄── Channel (buffer of messages) ◄── dispatcher thread

* The pool is a `ProcessPoolExecutor` (spawn) with `MARKETSIM_MAX_JOBS` workers; jobs beyond
  that wait as `queued`. `MARKETSIM_EXECUTOR=thread` swaps in threads (handy for debugging).
* A single dispatcher thread drains the result queue, updates the run index, and appends every
  message to the run's `Channel`. The worker never waits for a client.
* Each WebSocket client reads the channel from its own position at most `FLUSH_HZ` times a
  second. Ticks are coalesced: a flush keeps the last tick of every simulated hour it covers
  plus the newest tick, so a client always gets at least one frame per simulated hour. Event and
  narrative messages are never dropped; Monte Carlo progress keeps only the newest.
* A reconnecting client passes `?after=<tick>` and gets the buffered tail, then the live feed.
  Finished single runs are replayed from their saved results once their channel is gone.
"""

from __future__ import annotations

import contextlib
import functools
import logging
import multiprocessing as mp
import queue as queue_mod
import threading
from collections import OrderedDict
from collections.abc import Iterable
from concurrent.futures import Executor, Future, ProcessPoolExecutor, ThreadPoolExecutor
from multiprocessing.managers import SyncManager
from pathlib import Path
from typing import Any

import numpy as np

from marketsim.config import TICKS_PER_DAY

from .schemas import RunDetail, RunMode, RunSpec, RunStatus
from .storage import NotFound, Store
from .worker import execute, tick_message

logger = logging.getLogger("marketsim_api.jobs")

FLUSH_HZ = 20
TICKS_PER_HOUR = TICKS_PER_DAY // 24
KEEP_CHANNELS = 32  # finished channels kept in memory for fast replay
FINAL_TYPES = ("done", "error")


class Channel:
    """Every message of one run, in order, plus the final done / error message."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.hello: dict[str, Any] | None = None
        self.messages: list[dict[str, Any]] = []
        self.final: dict[str, Any] | None = None

    @property
    def finished(self) -> bool:
        return self.final is not None


def coalesce(batch: Iterable[dict[str, Any]], after: int | None = None) -> list[dict[str, Any]]:
    """Messages to send for one flush. Keeps every non-tick message, the last tick of each
    simulated hour, the newest tick, and only the newest Monte Carlo progress message."""
    items = [m for m in batch if after is None or "tick" not in m or m["tick"] > after]
    ticks = [i for i, m in enumerate(items) if m["type"] == "tick"]
    progress = [i for i, m in enumerate(items) if m["type"] == "progress"]
    keep_ticks = {i for i in ticks if items[i]["tick"] % TICKS_PER_HOUR == TICKS_PER_HOUR - 1}
    if ticks:
        keep_ticks.add(ticks[-1])
    drop = (set(ticks) - keep_ticks) | set(progress[:-1])
    return [m for i, m in enumerate(items) if i not in drop]


class JobRegistry:
    def __init__(self, store: Store, max_jobs: int = 2, executor: str = "process") -> None:
        self.store = store
        self.kind = executor
        self.pool: Executor
        self._manager: SyncManager | None
        if executor == "process":
            ctx = mp.get_context("spawn")
            self._manager = ctx.Manager()
            self.queue: Any = self._manager.Queue()
            self.pool = ProcessPoolExecutor(max_workers=max_jobs, mp_context=ctx)
        elif executor == "thread":
            self._manager = None
            self.queue = queue_mod.Queue()
            self.pool = ThreadPoolExecutor(max_workers=max_jobs, thread_name_prefix="job")
        else:
            raise ValueError(f"unknown executor {executor!r}")
        self.channels: OrderedDict[str, Channel] = OrderedDict()
        self.cancel_flags: dict[str, Any] = {}
        self.futures: dict[str, Future[None]] = {}
        self._lock = threading.Lock()
        self._dispatcher = threading.Thread(target=self._dispatch, name="job-dispatch", daemon=True)
        self._dispatcher.start()

    # ---------------------------------------------------------------- submit / cancel
    def _event(self) -> Any:
        return self._manager.Event() if self._manager is not None else threading.Event()

    def submit(self, run: RunDetail, pace: float = 0.0) -> None:
        flag = self._event()
        with self._lock:
            self.channels[run.id] = Channel(run.id)
            self.cancel_flags[run.id] = flag
        fut = self.pool.submit(
            execute,
            run.id,
            run.spec.model_dump_json(),
            str(self.store.run_dir(run.id)),
            self.queue,
            flag,
            pace,
        )
        self.futures[run.id] = fut
        fut.add_done_callback(functools.partial(self._on_future_done, run.id))

    def cancel(self, run_id: str) -> bool:
        """Ask a run to stop. Returns False if it is not active in this registry."""
        fut = self.futures.get(run_id)
        flag = self.cancel_flags.get(run_id)
        if fut is None or flag is None or fut.done():
            return False
        flag.set()
        if fut.cancel():  # still waiting in the pool: it will never start
            self._finish(run_id, RunStatus.cancelled, summary=None, error=None)
        return True

    def is_active(self, run_id: str) -> bool:
        fut = self.futures.get(run_id)
        return fut is not None and not fut.done()

    def shutdown(self) -> None:
        for flag in list(self.cancel_flags.values()):
            with contextlib.suppress(Exception):  # the manager may already be gone
                flag.set()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.queue.put(None)
        self._dispatcher.join(timeout=5)
        if self._manager is not None:
            self._manager.shutdown()

    # ---------------------------------------------------------------- dispatcher
    def _dispatch(self) -> None:
        while True:
            try:
                item = self.queue.get()
            except (EOFError, OSError, BrokenPipeError):
                return
            if item is None:
                return
            run_id, kind, payload = item
            ch = self.channels.get(run_id)
            if ch is None:
                continue
            try:
                if kind == "msg":
                    ch.messages.append(payload)
                elif kind == "started":
                    ch.hello = payload
                    self.store.set_status(run_id, RunStatus.running)
                elif kind == "finished":
                    self._finish(run_id, RunStatus(payload["status"]), payload["summary"], None)
                elif kind == "failed":
                    logger.error("run failed", extra={"run_id": run_id, "trace": payload.get("trace")})
                    self._finish(run_id, RunStatus.failed, None, payload["error"])
            except NotFound:  # the run was deleted meanwhile
                pass

    def _finish(
        self, run_id: str, status: RunStatus, summary: dict[str, Any] | None, error: str | None
    ) -> None:
        ch = self.channels.get(run_id)
        if ch is None or ch.finished:
            return
        with contextlib.suppress(NotFound):
            self.store.set_status(run_id, status, summary=summary, error=error)
        if error is not None:
            ch.final = {"type": "error", "message": error}
        else:
            ch.final = {"type": "done", "status": status.value, "summary": summary or {}}
        self.cancel_flags.pop(run_id, None)
        self._trim()

    def _on_future_done(self, run_id: str, fut: Future[None]) -> None:
        if fut.cancelled():
            return
        exc = fut.exception()
        if exc is not None:  # the worker process died (e.g. out of memory)
            self._finish(run_id, RunStatus.failed, None, f"{type(exc).__name__}: {exc}")

    def _trim(self) -> None:
        with self._lock:
            finished = [k for k, c in self.channels.items() if c.finished]
            for k in finished[:-KEEP_CHANNELS] if len(finished) > KEEP_CHANNELS else []:
                self.channels.pop(k, None)
                self.futures.pop(k, None)


# --------------------------------------------------------------------------- replay from disk


def replay_messages(run_dir: Path, spec: RunSpec, run_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Rebuild a finished single run's stream (hello + messages) from its saved results."""
    from marketsim.sim import load

    res = load(run_dir / "result")
    meta = res["meta"]
    hello = {
        "type": "hello",
        "run_id": run_id,
        "mode": RunMode.single.value,
        "runs": 1,
        "n_agents": spec.scenario.n_agents,
        "n_nodes": meta["n_nodes"],
        "days": spec.scenario.days,
        "seed": spec.seed,
        "ticks_per_day": TICKS_PER_DAY,
        "initial_price": float(res["series"]["price"][0]) if len(res["series"]["price"]) else 0.0,
        "node_sample": [],
        "replay": True,
    }
    born: dict[int, list[dict[str, Any]]] = {}
    for ev in res["events"]:
        msg = {
            "type": "event",
            "tick": ev["injected"],
            "id": ev["id"],
            "item": ev["item"],
            "parent": res["lineage"][ev["item"]]["parent"],
            "kind": ev["kind"],
            "seeding": ev["seeding"],
            "sentiment": ev["sentiment"],
            "credibility": ev["credibility"],
            "salience": ev["salience"],
            "true_impact": ev["true_impact"],
        }
        if ev.get("label"):
            msg["label"] = ev["label"]
        born.setdefault(ev["injected"], []).append(msg)
    for rec in res["lineage"]:
        if rec["origin"] in ("mutation", "invention"):
            msg = {
                "type": "narrative",
                "tick": rec["born"],
                "id": rec["id"],
                "parent": rec["parent"],
                "origin": rec["origin"],
                "sentiment": rec["sentiment"],
                "credibility": rec["credibility"],
            }
            if rec.get("label"):
                msg["label"] = rec["label"]
            born.setdefault(rec["born"], []).append(msg)
    aware: dict[int, dict[str, int]] = {}
    for t, item, n in np.asarray(res["awareness"]).tolist():
        aware.setdefault(t, {})[str(item)] = n
    s = res["series"]
    out: list[dict[str, Any]] = []
    for t in range(int(meta["n_ticks"])):
        out.extend(born.get(t, []))
        frame = {
            "tick": t,
            "price": float(s["price"][t]),
            "v_true": float(s["v_true"][t]),
            "volume": float(s["volume"][t]),
            "confidence": float(s["confidence"][t]),
            "iv": float(s["iv"][t]),
            "atm_call": float(s["atm_call"][t]),
            "mm_inventory": float(s["mm_inventory"][t]),
            "imbalance": float(s["imbalance"][t]),
            "awareness": aware.get(t, {}),
        }
        out.append(tick_message(frame))
    return hello, out
