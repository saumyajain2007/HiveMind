"""Run and scenario storage: a SQLite index plus one folder per run (issue #16).

Layout under the data directory:

    index.sqlite3          runs + scenarios tables
    runs/<run id>/spec.json    exact spec needed to reproduce the run
    runs/<run id>/...          results written by the job runner (issue #17)

Every operation opens its own short-lived connection, so the store is safe to use from
FastAPI's thread pool. WAL mode lets readers proceed while a writer commits.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schemas import RunDetail, RunRecord, RunSpec, RunStatus, ScenarioRecord, ScenarioSpec

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL,
    mode        TEXT NOT NULL,
    runs        INTEGER NOT NULL,
    n_agents    INTEGER NOT NULL,
    days        INTEGER NOT NULL,
    seed        INTEGER NOT NULL,
    scenario_id TEXT,
    spec_hash   TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    summary     TEXT,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS runs_created ON runs (created_at DESC);
CREATE INDEX IF NOT EXISTS runs_hash ON runs (spec_hash);
CREATE TABLE IF NOT EXISTS scenarios (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    spec        TEXT NOT NULL
);
"""


class NotFound(KeyError):
    pass


class Conflict(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def spec_hash(spec: RunSpec) -> str:
    """sha256 of the parts of the spec that determine the results (not names or worker count)."""
    data = spec.model_dump(mode="json")
    data.pop("workers", None)
    data.pop("scenario_id", None)
    data["scenario"].pop("name", None)
    data["scenario"].pop("description", None)
    for e in data["scenario"]["events"]:
        e.pop("label", None)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.runs_dir = self.data_dir / "runs"
        self.db_path = self.data_dir / "index.sqlite3"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    # ------------------------------------------------------------------ scenarios
    def create_scenario(self, spec: ScenarioSpec) -> ScenarioRecord:
        now = _now()
        rec = ScenarioRecord(id=_new_id(), created_at=now, updated_at=now, spec=spec)
        with self._conn() as c:
            c.execute(
                "INSERT INTO scenarios (id, name, created_at, updated_at, spec) VALUES (?, ?, ?, ?, ?)",
                (rec.id, spec.name, now.isoformat(), now.isoformat(), spec.model_dump_json()),
            )
        return rec

    def get_scenario(self, scenario_id: str) -> ScenarioRecord:
        with self._conn() as c:
            row = c.execute("SELECT * FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
        if row is None:
            raise NotFound(scenario_id)
        return self._scenario(row)

    def list_scenarios(self) -> list[ScenarioRecord]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM scenarios ORDER BY updated_at DESC").fetchall()
        return [self._scenario(r) for r in rows]

    def update_scenario(self, scenario_id: str, spec: ScenarioSpec) -> ScenarioRecord:
        now = _now()
        with self._conn() as c:
            cur = c.execute(
                "UPDATE scenarios SET name = ?, updated_at = ?, spec = ? WHERE id = ?",
                (spec.name, now.isoformat(), spec.model_dump_json(), scenario_id),
            )
        if cur.rowcount == 0:
            raise NotFound(scenario_id)
        return self.get_scenario(scenario_id)

    def delete_scenario(self, scenario_id: str) -> None:
        with self._conn() as c:
            cur = c.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
        if cur.rowcount == 0:
            raise NotFound(scenario_id)

    @staticmethod
    def _scenario(row: sqlite3.Row) -> ScenarioRecord:
        return ScenarioRecord(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            spec=ScenarioSpec.model_validate_json(row["spec"]),
        )

    # ------------------------------------------------------------------ runs
    def create_run(self, spec: RunSpec, name: str) -> RunDetail:
        now = _now()
        run_id = _new_id()
        h = spec_hash(spec)
        d = self.run_dir(run_id)
        d.mkdir(parents=True)
        (d / "spec.json").write_text(spec.model_dump_json(indent=1), encoding="utf-8")
        with self._conn() as c:
            c.execute(
                "INSERT INTO runs (id, name, status, mode, runs, n_agents, days, seed, scenario_id,"
                " spec_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    name,
                    RunStatus.queued.value,
                    spec.mode.value,
                    spec.runs,
                    spec.scenario.n_agents,
                    spec.scenario.days,
                    spec.seed,
                    spec.scenario_id,
                    h,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> RunDetail:
        with self._conn() as c:
            row = c.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise NotFound(run_id)
        spec = RunSpec.model_validate_json((self.run_dir(run_id) / "spec.json").read_text(encoding="utf-8"))
        return RunDetail(**self._run(row).model_dump(), spec=spec)

    def list_runs(
        self, limit: int = 50, offset: int = 0, status: RunStatus | None = None
    ) -> tuple[list[RunRecord], int]:
        where, args = ("WHERE status = ?", [status.value]) if status else ("", [])
        with self._conn() as c:
            total = c.execute(f"SELECT COUNT(*) FROM runs {where}", args).fetchone()[0]
            rows = c.execute(
                f"SELECT * FROM runs {where} ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        return [self._run(r) for r in rows], int(total)

    def set_status(
        self,
        run_id: str,
        status: RunStatus,
        summary: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE runs SET status = ?, updated_at = ?, summary = COALESCE(?, summary), error = ?"
                " WHERE id = ?",
                (
                    status.value,
                    _now().isoformat(),
                    json.dumps(summary) if summary is not None else None,
                    error,
                    run_id,
                ),
            )
        if cur.rowcount == 0:
            raise NotFound(run_id)

    def delete_run(self, run_id: str) -> None:
        run = self.get_run(run_id)
        if run.status in (RunStatus.queued, RunStatus.running):
            raise Conflict(f"run {run_id} is {run.status.value}; cancel it first")
        with self._conn() as c:
            c.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        shutil.rmtree(self.run_dir(run_id), ignore_errors=True)

    @staticmethod
    def _run(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            id=row["id"],
            name=row["name"],
            status=RunStatus(row["status"]),
            mode=row["mode"],
            runs=row["runs"],
            n_agents=row["n_agents"],
            days=row["days"],
            seed=row["seed"],
            scenario_id=row["scenario_id"],
            spec_hash=row["spec_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            summary=json.loads(row["summary"]) if row["summary"] else None,
            error=row["error"],
        )
