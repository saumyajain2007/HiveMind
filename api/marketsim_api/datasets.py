"""Uploaded datasets: a daily close series plus dated events (issue #18).

Stored as files under `<data dir>/datasets/<id>/`: `prices.csv`, `events.json`, `meta.json`.
Runs that use a dataset copy both files into their own folder, so deleting or re-uploading a
dataset never changes a past calibration or backtest.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from marketsim.backtest import load_price_csv, parse_dated_events

from .schemas import DatasetDetail, DatasetRecord, DatasetUpload
from .storage import NotFound

PRICES, EVENTS, META = "prices.csv", "events.json", "meta.json"


class DatasetStore:
    def __init__(self, data_dir: Path) -> None:
        self.root = Path(data_dir) / "datasets"
        self.root.mkdir(parents=True, exist_ok=True)

    def dir(self, dataset_id: str) -> Path:
        d = self.root / dataset_id
        if not dataset_id.isalnum() or not (d / META).exists():
            raise NotFound(dataset_id)
        return d

    def create(self, body: DatasetUpload) -> DatasetRecord:
        """Validate (raises ValueError with a readable message) and store."""
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / PRICES
            csv_path.write_text(body.csv, encoding="utf-8")
            dates, closes = load_price_csv(csv_path)
            if len(closes) < 2:
                raise ValueError("need at least two days of prices")
            parse_dated_events(body.events, dates)  # validates; raises ValueError
        sha = hashlib.sha256((body.csv + json.dumps(body.events, sort_keys=True)).encode("utf-8")).hexdigest()
        rec = DatasetRecord(
            id=uuid.uuid4().hex[:12],
            name=body.name,
            created_at=datetime.now(UTC),
            n_days=len(closes),
            first_date=dates[0],
            last_date=dates[-1],
            n_events=len(body.events),
            sha256=sha,
        )
        d = self.root / rec.id
        d.mkdir(parents=True)
        (d / PRICES).write_text(body.csv, encoding="utf-8")
        (d / EVENTS).write_text(json.dumps(body.events, indent=1), encoding="utf-8")
        (d / META).write_text(rec.model_dump_json(indent=1), encoding="utf-8")
        return rec

    def get(self, dataset_id: str) -> DatasetRecord:
        return DatasetRecord.model_validate_json((self.dir(dataset_id) / META).read_text(encoding="utf-8"))

    def detail(self, dataset_id: str) -> DatasetDetail:
        d = self.dir(dataset_id)
        rec = self.get(dataset_id)
        dates, closes = load_price_csv(d / PRICES)
        events = json.loads((d / EVENTS).read_text(encoding="utf-8"))
        return DatasetDetail(**rec.model_dump(), dates=dates, closes=closes.tolist(), events=events)

    def list(self) -> list[DatasetRecord]:
        out = []
        for d in self.root.iterdir():
            if (d / META).exists():
                out.append(DatasetRecord.model_validate_json((d / META).read_text(encoding="utf-8")))
        return sorted(out, key=lambda r: r.created_at, reverse=True)

    def delete(self, dataset_id: str) -> None:
        shutil.rmtree(self.dir(dataset_id))

    def copy_into(self, dataset_id: str, run_dir: Path) -> None:
        d = self.dir(dataset_id)
        for name in (PRICES, EVENTS):
            shutil.copyfile(d / name, run_dir / name)
