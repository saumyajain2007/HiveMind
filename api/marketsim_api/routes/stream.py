"""`WS /api/v1/runs/{id}/stream`: live frames of a run (issue #17).

Message shapes are defined by the web app (`web/src/lib/live/types.ts`): `hello`, then `tick`,
`event`, `narrative` (and `progress` for Monte Carlo) in order, then `done` or `error`.
`?after=<tick>` skips everything up to that tick (used when reconnecting).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..jobs import FLUSH_HZ, Channel, JobRegistry, coalesce, replay_messages
from ..schemas import RunMode, RunStatus
from ..storage import NotFound, Store

router = APIRouter(tags=["runs"])
HELLO_TIMEOUT_S = 600.0  # a queued run may wait this long for a free worker


async def _send_all(ws: WebSocket, msgs: list[dict[str, Any]]) -> None:
    for m in msgs:
        await ws.send_json(m)


async def _from_channel(ws: WebSocket, ch: Channel, after: int | None) -> None:
    waited = 0.0
    while ch.hello is None and not ch.finished:
        await asyncio.sleep(1 / FLUSH_HZ)
        waited += 1 / FLUSH_HZ
        if waited > HELLO_TIMEOUT_S:
            await ws.send_json({"type": "error", "message": "timed out waiting for the run to start"})
            return
    if ch.hello is not None:
        await ws.send_json(ch.hello)
    pos = 0
    while True:
        final = ch.final  # read before the messages, so nothing sent after it is missed
        end = len(ch.messages)
        if end > pos:
            await _send_all(ws, coalesce(ch.messages[pos:end], after))
            pos = end
        if final is not None and pos == len(ch.messages):
            await ws.send_json(final)
            return
        await asyncio.sleep(1 / FLUSH_HZ)


@router.websocket("/runs/{run_id}/stream")
async def stream(ws: WebSocket, run_id: str, after: int | None = None) -> None:
    await ws.accept()
    store: Store = ws.app.state.store
    jobs: JobRegistry | None = ws.app.state.jobs
    try:
        try:
            run = store.get_run(run_id)
        except NotFound:
            await ws.send_json({"type": "error", "message": f"run {run_id} not found"})
            return
        ch = jobs.channels.get(run_id) if jobs is not None else None
        if ch is not None:
            await _from_channel(ws, ch, after)
        elif (
            run.status in (RunStatus.done, RunStatus.cancelled)
            and run.mode == RunMode.single
            and (store.run_dir(run_id) / "result").exists()
        ):
            hello, msgs = await asyncio.to_thread(replay_messages, store.run_dir(run_id), run.spec, run_id)
            await ws.send_json(hello)
            # a replay sends every tick (the client scrubs through them), not a coalesced feed
            await _send_all(ws, [m for m in msgs if after is None or m.get("tick", after + 1) > after])
            await ws.send_json({"type": "done", "status": run.status.value, "summary": run.summary or {}})
        else:
            message = run.error or f"run {run_id} is {run.status.value} and has no live stream"
            await ws.send_json({"type": "error", "message": message})
    except WebSocketDisconnect:
        return
    finally:
        with contextlib.suppress(RuntimeError):  # already closed by the client
            await ws.close()
