"""Stock import: one stock's prices, filings as headlines, social chatter and the event classifier.

`universe()` lists the downloaded stocks. `build(ticker)` returns, for the last two years:

* prices and volume (data/<T>/prices.csv),
* headlines: the stock's SEC filings, worded from their form and 8-K items, with the real
  abnormal return of each reaction day,
* social: daily mention counts and sentiment per platform plus a feed of posts. These are
  generated (seeded by the ticker) from the real returns, volume and filing dates; see the
  README section "Stock import",
* classification: the pooled event classifier (`marketsim.event_library`, trained on all 50
  stocks' events before the split) applied to this stock's events after the split, with the
  real outcome next to each prediction. Nothing after the split is used to fit it.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from .event_library import _event_rows, _fit, tickers_in
from .impact_model import CLASSES
from .realdata import DATA_ROOT, feature_matrix, load_dataset

SPLIT = "2024-01-01"
WINDOW_DAYS = 504  # two years of trading days

ITEM_TEXT = {
    "1.01": "enters a material agreement",
    "1.02": "ends a material agreement",
    "2.01": "completes an acquisition or disposition",
    "2.02": "reports quarterly results",
    "2.03": "takes on a new financial obligation",
    "2.05": "announces restructuring costs",
    "2.06": "records a material impairment",
    "3.02": "sells unregistered shares",
    "5.02": "announces a change of directors or officers",
    "5.03": "amends its articles or bylaws",
    "5.07": "reports shareholder vote results",
    "7.01": "makes a Regulation FD disclosure",
    "8.01": "discloses other events",
}
FORM_TEXT = {
    "10-Q": "files its quarterly report (10-Q)",
    "10-K": "files its annual report (10-K)",
    "DEF 14A": "files its proxy statement",
    "S-3": "files a shelf registration",
    "SC 13G": "discloses a large holder (13G)",
    "SC 13G/A": "updates a large holder filing (13G/A)",
    "4": "insider transaction (Form 4)",
}
PLATFORMS = ("Reddit", "X", "StockTwits", "YouTube", "TikTok")
PLATFORM_SHARE = (0.30, 0.32, 0.22, 0.09, 0.07)


def universe(root: Path = DATA_ROOT) -> list[dict[str, Any]]:
    out = []
    for t in tickers_in(root):
        d = root / t
        name = t
        with contextlib.suppress(OSError, ValueError):
            name = json.loads((d / "filings.json").read_text(encoding="utf-8")).get("name", t)
        last = (d / "prices.csv").read_text(encoding="utf-8").strip().splitlines()[-1].split(",")
        out.append({"ticker": t, "name": name.title(), "last_date": last[0], "last_close": float(last[1])})
    return out


def _headline(name: str, form: str, items: list[str]) -> str:
    if form.startswith("8-K"):
        parts = [ITEM_TEXT[i] for i in items if i in ITEM_TEXT]
        what = " and ".join(parts[:2]) if parts else "files a current report"
        return f"{name} {what} (8-K)"
    return f"{name} {FORM_TEXT.get(form, f'files a {form}')}"


@functools.lru_cache(maxsize=1)
def _classifier(root: str) -> tuple[Any, dict[str, list[dict[str, Any]]]]:
    """Pooled classifier trained on every stock's events before SPLIT; rows by ticker."""
    rows_by: dict[str, list[dict[str, Any]]] = {}
    tr = []
    for t in tickers_in(Path(root)):
        rows = _event_rows(t, Path(root))
        rows_by[t] = rows
        tr += [r for r in rows if r["date"] < SPLIT]
    tr.sort(key=lambda r: r["date"])
    model = _fit(feature_matrix([r["_event"] for r in tr]), np.array([r["ar"] for r in tr]))
    return model, rows_by


def _seed(ticker: str) -> int:
    return int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16)


HANDLES = (
    "thetagang_mike",
    "valuehunter22",
    "chartwizard",
    "divi_dad",
    "quantqueen",
    "bagholder_bob",
    "macro_maddie",
    "tendieman",
    "longtermlarry",
    "optionsoracle",
    "deepvalue_dee",
    "swingking",
    "fintwit_fred",
    "bullbear_bea",
    "capexcarl",
    "earningseve",
    "momentum_mo",
    "riskparity_ray",
)
UP_POSTS = (
    "${t} up {m} today. {why}",
    "Not selling a single share of ${t}. {m} and climbing.",
    "${t} breaking out, {m} on {v}x volume",
    "Called it. ${t} {m}. {why}",
    "${t} calls printing today ({m})",
)
DOWN_POSTS = (
    "${t} down {m}. {why}",
    "Bought the dip on ${t} at {p}. Down {m} feels like an overreaction",
    "${t} {m} on {v}x volume, someone knows something",
    "Rough day for ${t} holders ({m})",
    "${t} puts paying off, {m}",
)
QUIET_POSTS = (
    "${t} going nowhere this week. Waiting for the next catalyst",
    "Anyone adding ${t} at {p}?",
    "${t} chart looks like it's coiling. Watching {p}",
    "Holding ${t} for the long run, ignoring the noise",
)
WHY = {
    "earnings": ("Numbers came out after the bell.", "Earnings did it.", "That quarter though."),
    "periodic_report": ("Reading the 10-Q now.", "Filing just dropped."),
    "management": ("Leadership change news.",),
    "deal": ("Deal news.",),
    None: ("No news I can see.", "Market-wide move?", ""),
}


def _social(
    ticker: str, dates: list[str], close: np.ndarray, volume: np.ndarray, event_day: dict[int, str]
) -> dict[str, Any]:
    rng = np.random.default_rng(_seed(ticker))
    r = np.concatenate([[0.0], np.diff(np.log(close))])
    sd = float(np.std(r[1:])) or 0.01
    vol_ratio = volume / np.maximum(np.convolve(volume, np.ones(20) / 20, "same"), 1.0)
    base = 400.0 * (1 + rng.random())
    z = np.abs(r) / sd
    earn = np.array([1.0 if event_day.get(i) == "earnings" else 0.0 for i in range(len(r))])
    mentions = base * (1 + 0.6 * z + 2.5 * earn) * vol_ratio**0.7 * rng.lognormal(0, 0.2, len(r))
    sentiment = np.tanh(0.55 * r / sd + rng.normal(0, 0.25, len(r)))
    by_platform = {
        p: np.round(mentions * s * rng.lognormal(0, 0.15, len(r))).astype(int).tolist()
        for p, s in zip(PLATFORMS, PLATFORM_SHARE, strict=True)
    }
    posts = []
    order = np.argsort(-(z + 3 * earn))[:60]  # the loudest days get posts
    quiet = rng.choice(len(r), size=20, replace=False)
    for i in sorted(set(order.tolist()) | set(quiet.tolist())):
        loud = z[i] > 1.2 or earn[i] > 0
        k = 1 + int(rng.integers(1, 4)) if loud else 1
        for _ in range(k):
            pool = UP_POSTS if r[i] > 0 and loud else DOWN_POSTS if loud else QUIET_POSTS
            text = (
                pool[int(rng.integers(len(pool)))]
                .format(
                    t=ticker,
                    m=f"{abs(r[i]) * 100:.1f}%",
                    p=f"${close[i]:.0f}",
                    v=f"{vol_ratio[i]:.1f}",
                    why=WHY.get(event_day.get(i), WHY[None])[
                        int(rng.integers(len(WHY.get(event_day.get(i), WHY[None]))))
                    ],
                )
                .strip()
            )
            pi = int(rng.choice(len(PLATFORMS), p=np.array(PLATFORM_SHARE)))
            posts.append(
                {
                    "date": dates[i],
                    "platform": PLATFORMS[pi],
                    "handle": f"@{HANDLES[int(rng.integers(len(HANDLES)))]}",
                    "text": text,
                    "likes": int(rng.lognormal(3.5 + 1.2 * min(z[i], 4) / 4, 1.0)),
                    "sentiment": float(
                        np.clip(np.sign(r[i]) * (0.3 + 0.2 * z[i]) if loud else rng.normal(0, 0.2), -1, 1)
                    ),
                }
            )
    seen: set[tuple[str, str]] = set()
    unique = []
    for post in posts:
        if (post["date"], post["text"]) not in seen:
            seen.add((post["date"], post["text"]))
            unique.append(post)
    posts = unique
    posts.sort(key=lambda p: p["date"], reverse=True)
    return {
        "platforms": list(PLATFORMS),
        "mentions": np.round(mentions).astype(int).tolist(),
        "by_platform": by_platform,
        "sentiment": np.round(sentiment, 3).tolist(),
        "posts": posts,
        "n_posts": int(sum(sum(v) for v in by_platform.values())),
    }


@functools.lru_cache(maxsize=64)
def build(ticker: str, root: Path = DATA_ROOT) -> dict[str, Any]:
    ticker = ticker.upper()
    ds = load_dataset(ticker, root)
    h = ds.history
    n = len(h.dates)
    lo = max(0, n - WINDOW_DAYS)
    dates = list(h.dates[lo:])
    close = np.asarray(h.close[lo:], np.float64)
    volume = np.asarray(h.volume[lo:], np.float64)
    name = h.name.title() if h.name else ticker
    cik = int(json.loads((root / ticker / "filings.json").read_text(encoding="utf-8")).get("cik", 0))

    model, rows_by = _classifier(str(root))
    rows = {r["_event"].id: r for r in rows_by.get(ticker, [])}

    headlines: list[dict[str, Any]] = []
    event_day: dict[int, str] = {}
    for e in ds.events:
        if e.reaction_idx < lo or e.reaction_idx >= n:
            continue
        i = e.reaction_idx - lo
        event_day.setdefault(i, e.group)
        row = rows.get(e.id)
        headlines.append(
            {
                "date": e.released[:10],
                "released": e.released,
                "reaction_date": dates[i],
                "index": i,
                "source": "SEC EDGAR",
                "form": e.form,
                "group": e.group,
                "headline": _headline(name, e.form, e.items),
                "abnormal_return": None if row is None else row["ar"],
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{e.accession.replace('-', '')}/"
                if e.accession and cik
                else None,
            }
        )
    headlines.sort(key=lambda x: str(x["released"]), reverse=True)

    # classifier on this stock's out-of-sample events
    test = [r for r in rows_by.get(ticker, []) if r["date"] >= SPLIT]
    cls: dict[str, Any] = {"split": SPLIT, "classes": list(CLASSES), "events": [], "metrics": {}}
    if test:
        X = feature_matrix([r["_event"] for r in test])
        P, size, exp = model.proba(X), model.size(X), model.expected(X)
        y = np.array([r["ar"] for r in test])
        truth = model.classes_of(y, model.tau)
        pred = np.argmax(P, axis=1)
        for k, r in enumerate(test):
            cls["events"].append(
                {
                    "date": r["date"],
                    "form": r["form"],
                    "group": r["group"],
                    "proba": [round(float(p), 4) for p in P[k]],
                    "predicted": CLASSES[int(pred[k])],
                    "actual": CLASSES[int(truth[k])],
                    "expected_ar": float(exp[k]),
                    "predicted_size": float(size[k]),
                    "actual_ar": float(r["ar"]),
                }
            )
        moved = truth != 1
        dir_hit = float(np.mean(np.sign(exp[moved]) == np.sign(y[moved]))) if moved.any() else None
        size_corr = (
            float(np.corrcoef(np.log(size + 1e-3), np.log(np.abs(y) + 1e-3))[0, 1]) if len(y) > 2 else None
        )
        base = int(np.argmax(np.bincount(truth, minlength=3)))
        cls["metrics"] = {
            "n": len(test),
            "accuracy": float(np.mean(pred == truth)),
            "majority_accuracy": float(np.mean(truth == base)),
            "direction_hit_rate": dir_hit,
            "size_corr": size_corr,
            "size_mae": float(np.mean(np.abs(size - np.abs(y)))),
            "mean_abs_ar": float(np.mean(np.abs(y))),
        }

    social = _social(ticker, dates, close, volume, event_day)
    return {
        "ticker": ticker,
        "name": name,
        "period": [dates[0], dates[-1]],
        "dates": dates,
        "close": close.round(4).tolist(),
        "volume": volume.astype(np.int64).tolist(),
        "sources": [
            {"name": "Prices", "provider": "Yahoo Finance", "count": len(dates)},
            {"name": "Filings", "provider": "SEC EDGAR", "count": len(headlines)},
            *[{"name": p, "provider": p, "count": int(sum(social["by_platform"][p]))} for p in PLATFORMS],
        ],
        "headlines": headlines,
        "social": social,
        "classification": cls,
    }
