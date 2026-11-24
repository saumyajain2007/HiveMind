"""Real stock history and the company's own filings as events (offline: reads `data/<TICKER>/`).

The files come from `scripts/fetch_market_data.py`: adjusted daily closes for the stock and for
the market (SPY), the company's SEC filings (8-K item codes, 10-Q, 10-K) with their exact
acceptance time, and quarterly diluted EPS and revenue as first reported.

For every filing this module works out:

* **when the market could react**: a filing accepted before 16:00 New York time on a trading day
  is reflected in that day's close; later (or on a non-trading day) in the next close;
* **its group** from the 8-K item codes (earnings 2.02, executive change 5.02, shareholder vote
  5.07, other events 8.01, ...; 10-Q / 10-K are periodic reports);
* **features known at the announcement**: the stock's 5- and 20-day return, the market's 5-day
  return, 20-day realised volatility and volume ratio, all from closes *before* the reaction
  day, the release time, and for earnings the year-on-year growth of the reported EPS and revenue;
* **the actual reaction (the label)**: the abnormal log return on the reaction day from a
  market-model event study (`event_parser.event_study`). Labels are for training and evaluation
  only; using them as forecast inputs would be lookahead leakage.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from .event_parser import event_study

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
CLOSE_MINUTES = 16 * 60  # 16:00 New York

GROUPS = (
    "earnings",
    "periodic_report",
    "executive",
    "vote",
    "governance",
    "other_event",
    "disclosure",
    "agreement",
)
FEATURES = (
    *(f"is_{g}" for g in GROUPS),
    "after_close",
    "ret_5d",
    "ret_20d",
    "mkt_ret_5d",
    "vol_20d",
    "volume_ratio",
    "eps_yoy",
    "rev_yoy",
)


# --------------------------------------------------------------------------- time


def _nth_sunday(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def utc_to_new_york(t: datetime) -> datetime:
    """US Eastern time (EST/EDT, rules since 2007) for a naive UTC datetime."""
    start = datetime.combine(_nth_sunday(t.year, 3, 2), datetime.min.time()) + timedelta(hours=7)  # 2:00 EST
    end = datetime.combine(_nth_sunday(t.year, 11, 1), datetime.min.time()) + timedelta(hours=6)  # 2:00 EDT
    return t - timedelta(hours=4 if start <= t < end else 5)


# --------------------------------------------------------------------------- data


@dataclass
class StockHistory:
    ticker: str
    name: str
    dates: list[str]  # trading days present for both the stock and the market
    close: np.ndarray
    market: np.ndarray
    volume: np.ndarray

    def index_on_or_after(self, day: str) -> int:
        """Index of the first trading day on or after `day` (len(dates) if none)."""
        import bisect

        return bisect.bisect_left(self.dates, day)


@dataclass
class RealEvent:
    id: int
    form: str
    items: list[str]
    group: str
    released: str  # New York time, ISO
    reaction_idx: int  # first close that reflects it
    after_close: bool
    features: dict[str, float]
    label: float | None = None  # abnormal log return on the reaction day
    label_t: float | None = None
    accession: str = ""

    @property
    def scheduled(self) -> bool:
        """Earnings dates are announced weeks ahead, so a forecaster may know them in advance."""
        return self.group == "earnings"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "form": self.form,
            "items": self.items,
            "group": self.group,
            "released": self.released,
            "reaction_idx": self.reaction_idx,
            "after_close": self.after_close,
            "features": self.features,
            "label": self.label,
            "label_t": self.label_t,
            "accession": self.accession,
        }


@dataclass
class Dataset:
    history: StockHistory
    events: list[RealEvent] = field(default_factory=list)


def _read_prices(path: Path) -> dict[str, tuple[float, float]]:
    with path.open(encoding="utf-8", newline="") as f:
        return {r["date"]: (float(r["close"]), float(r.get("volume") or 0)) for r in csv.DictReader(f)}


def load_history(ticker: str, root: Path | None = None) -> StockHistory:
    d = (root or DATA_ROOT) / ticker.upper()
    stock = _read_prices(d / "prices.csv")
    market = _read_prices(d / "market.csv")
    dates = sorted(set(stock) & set(market))
    name = json.loads((d / "filings.json").read_text(encoding="utf-8")).get("name", ticker)
    return StockHistory(
        ticker=ticker.upper(),
        name=name,
        dates=dates,
        close=np.array([stock[x][0] for x in dates]),
        market=np.array([market[x][0] for x in dates]),
        volume=np.array([stock[x][1] for x in dates]),
    )


def group_of(form: str, items: list[str]) -> str:
    if form in ("10-Q", "10-K"):
        return "periodic_report"
    s = set(items)
    for code, g in (
        ("2.02", "earnings"),
        ("5.02", "executive"),
        ("5.07", "vote"),
        ("5.03", "governance"),
        ("1.01", "agreement"),
        ("2.01", "agreement"),
        ("2.03", "other_event"),
        ("8.01", "other_event"),
        ("7.01", "disclosure"),
    ):
        if code in s:
            return g
    return "other_event"


# --------------------------------------------------------------------------- fundamentals


def _quarters(rows: list[dict]) -> dict[str, float]:
    """Quarter-end date -> value for 3-month periods; Q4 derived as the year minus nine months."""
    out: dict[str, float] = {}
    by_start: dict[str, list[dict]] = {}
    for r in rows:
        days = (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days
        if 80 <= days <= 100:
            out[r["end"]] = float(r["value"])
        by_start.setdefault(r["start"], []).append({**r, "days": days})
    for rs in by_start.values():
        year = [r for r in rs if 350 <= r["days"] <= 380]
        nine = [r for r in rs if 260 <= r["days"] <= 290]
        if year and nine and year[0]["end"] not in out:
            out[year[0]["end"]] = float(year[0]["value"]) - float(nine[0]["value"])
    return out


def _yoy(quarters: dict[str, float], before: str) -> float:
    """Growth of the latest quarter ending before `before` over the same quarter a year earlier."""
    ends = sorted(e for e in quarters if e < before)
    if not ends:
        return 0.0
    last = ends[-1]
    target = date.fromisoformat(last) - timedelta(days=364)
    prev = [e for e in ends if abs((date.fromisoformat(e) - target).days) <= 12]
    if not prev or quarters[prev[-1]] == 0:
        return 0.0
    g = quarters[last] / quarters[prev[-1]] - 1.0
    return float(np.clip(g, -1.0, 1.0))


# --------------------------------------------------------------------------- events


def features_at(h: StockHistory, idx: int) -> dict[str, float]:
    """Market features from closes strictly before index `idx`."""
    c, m, v = h.close, h.market, h.volume
    last = idx - 1
    if last < 21:
        return {"ret_5d": 0.0, "ret_20d": 0.0, "mkt_ret_5d": 0.0, "vol_20d": 0.02, "volume_ratio": 1.0}
    r = np.diff(np.log(c[last - 20 : last + 1]))
    avg_vol = float(np.mean(v[last - 20 : last])) or 1.0
    return {
        "ret_5d": float(math.log(c[last] / c[last - 5])),
        "ret_20d": float(math.log(c[last] / c[last - 20])),
        "mkt_ret_5d": float(math.log(m[last] / m[last - 5])),
        "vol_20d": float(r.std(ddof=1)),
        "volume_ratio": float(v[last] / avg_vol) if avg_vol > 0 else 1.0,
    }


def load_dataset(ticker: str, root: Path | None = None, label_window: tuple[int, int] = (0, 0)) -> Dataset:
    d = (root or DATA_ROOT) / ticker.upper()
    h = load_history(ticker, root)
    filings = json.loads((d / "filings.json").read_text(encoding="utf-8"))["filings"]
    fund = json.loads((d / "fundamentals.json").read_text(encoding="utf-8"))
    eps_q, rev_q = _quarters(fund.get("eps_diluted", [])), _quarters(fund.get("revenue", []))
    events: list[RealEvent] = []
    for f in filings:
        ny = utc_to_new_york(datetime.fromisoformat(f["accepted"]))
        day = ny.date().isoformat()
        idx = h.index_on_or_after(day)
        trading_day = idx < len(h.dates) and h.dates[idx] == day
        after = ny.hour * 60 + ny.minute >= CLOSE_MINUTES
        if trading_day and after:
            idx += 1
        if idx >= len(h.dates) or idx < 22:
            continue
        group = group_of(f["form"], f["items"])
        feats = {f"is_{g}": float(g == group) for g in GROUPS}
        feats["after_close"] = float(after or not trading_day)
        feats.update(features_at(h, idx))
        feats["eps_yoy"] = _yoy(eps_q, day) if group == "earnings" else 0.0
        feats["rev_yoy"] = _yoy(rev_q, day) if group == "earnings" else 0.0
        ev = RealEvent(
            id=len(events),
            form=f["form"],
            items=f["items"],
            group=group,
            released=ny.isoformat(timespec="minutes"),
            reaction_idx=idx,
            after_close=bool(feats["after_close"]),
            features=feats,
            accession=f.get("accession", ""),
        )
        try:
            es = event_study(h.close, h.market, idx, est_window=120, event_window=label_window)
            ev.label, ev.label_t = es.car, es.t_stat
        except ValueError:
            pass
        events.append(ev)
    return Dataset(h, events)


def feature_matrix(events: list[RealEvent], mask_announcement: bool = False) -> np.ndarray:
    """Rows of FEATURES. With `mask_announcement`, the numbers only the release reveals (EPS and
    revenue growth) are zeroed: what a forecaster knows *before* a scheduled release."""
    X = np.array([[e.features[k] for k in FEATURES] for e in events], np.float64).reshape(-1, len(FEATURES))
    if mask_announcement:
        for k in ("eps_yoy", "rev_yoy"):
            X[:, FEATURES.index(k)] = 0.0
    return X
