"""The event library: every filing of every downloaded stock, its isolated real effect, and an
impact model trained on all of them.

    uv run python scripts/fetch_market_data.py            # the built-in universe of ~50 stocks
    uv run python -m marketsim.event_library               # -> docs/experiments/events/

**Isolating an event's effect in real data.** A stock moves every day, so a filing's effect is
its *abnormal* return: the stock's return minus what the market model (alpha + beta x SPY,
fitted on the 120 days before) predicts. Even abnormal returns are never zero, so the effect an
event type is responsible for is the excess over a normal day:

* ``mean |AR|`` on reaction days vs the ``normal |AR|`` of the same stocks on ordinary days
  (sd of the estimation-window residuals x sqrt(2/pi), the mean of a half-normal);
* the *standardised* abnormal return SAR = AR / residual sd, pooled across events into a
  t-statistic for the direction (does this event type move prices up or down on average?) and a
  mean |SAR| for the size (1 = a normal day, 3 = three times as big);
* the cumulative abnormal return over days 0..5, showing how fast the effect is priced in (and
  whether it drifts on or reverts);
* reaction-day volume against the 20-day average.

The same split as the single-stock experiment applies to the model: events before
`--split` train it, later ones test it. It is compared with a model trained on each stock's
own events only, on exactly the same test events, to measure what pooling buys.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from .event_parser import event_study
from .impact_model import ImpactModel
from .realdata import DATA_ROOT, FEATURES, GROUPS, RealEvent, feature_matrix, load_dataset
from .sim import json_safe

ROOT = Path(__file__).resolve().parents[1]
CAR_DAYS = 5
HALF_NORMAL = math.sqrt(2 / math.pi)


def tickers_in(root: Path) -> list[str]:
    return sorted(
        p.name for p in root.iterdir() if (p / "filings.json").exists() and (p / "prices.csv").exists()
    )


def _event_rows(ticker: str, root: Path) -> list[dict[str, Any]]:
    ds = load_dataset(ticker, root)
    h = ds.history
    rs, rm = np.diff(np.log(h.close)), np.diff(np.log(h.market))
    earn_days = {e.reaction_idx for e in ds.events if e.group == "earnings"}
    rows = []
    for e in ds.events:
        if e.label is None or (e.group != "earnings" and e.reaction_idx in earn_days):
            continue  # earnings own their reaction day (see DECISIONS.md)
        i = e.reaction_idx
        if i + CAR_DAYS >= len(h.dates):
            continue
        try:
            es = event_study(h.close, h.market, i, est_window=120, event_window=(0, 0))
        except ValueError:
            continue
        if es.resid_sd <= 0:
            continue
        ar = np.array([rs[i + k - 1] - (es.alpha + es.beta * rm[i + k - 1]) for k in range(CAR_DAYS + 1)])
        vol_base = float(np.mean(h.volume[max(0, i - 21) : i - 1])) or 1.0
        rows.append(
            {
                "ticker": ticker,
                "name": h.name,
                "date": h.dates[i],
                "released": e.released,
                "form": e.form,
                "items": e.items,
                "group": e.group,
                "ar": float(ar[0]),
                "sar": float(ar[0] / es.resid_sd),
                "resid_sd": es.resid_sd,
                "car": np.cumsum(ar).tolist(),
                "volume_ratio": float(h.volume[i] / vol_base) if vol_base > 0 else 1.0,
                "_event": e,
            }
        )
    return rows


def catalog(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for g in GROUPS:
        sub = [r for r in rows if r["group"] == g]
        if len(sub) < 3:
            continue
        ar = np.array([r["ar"] for r in sub])
        sar = np.array([r["sar"] for r in sub])
        normal = np.array([r["resid_sd"] * HALF_NORMAL for r in sub])
        car = np.array([r["car"] for r in sub])
        vr = np.array([r["volume_ratio"] for r in sub])
        n = len(sub)
        out.append(
            {
                "group": g,
                "n": n,
                "tickers": len({r["ticker"] for r in sub}),
                "mean_ar": float(ar.mean()),
                "median_ar": float(np.median(ar)),
                "t_direction": float(sar.mean() / (sar.std(ddof=1) / math.sqrt(n))) if n > 2 else 0.0,
                "share_up": float((ar > 0).mean()),
                "mean_abs_ar": float(np.abs(ar).mean()),
                "normal_abs_ar": float(normal.mean()),
                "excess_abs_ar": float(np.abs(ar).mean() - normal.mean()),
                "abs_sar": float(np.abs(sar).mean() / HALF_NORMAL),  # 1 = as big as a normal day
                "share_big": float((np.abs(sar) > 3).mean()),  # moves beyond 3 residual sds
                "car_mean": car.mean(axis=0).tolist(),
                "car_abs_mean": np.abs(car).mean(axis=0).tolist(),
                "day0_share_of_5d": float(np.abs(ar).mean() / max(np.abs(car[:, -1]).mean(), 1e-12)),
                "volume_ratio_median": float(np.median(vr)),
            }
        )
    return sorted(out, key=lambda c: -c["abs_sar"])


def per_ticker_earnings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in sorted({r["ticker"] for r in rows}):
        sub = [r for r in rows if r["ticker"] == t and r["group"] == "earnings"]
        if len(sub) < 4:
            continue
        ar = np.array([r["ar"] for r in sub])
        sar = np.array([r["sar"] for r in sub])
        out.append(
            {
                "ticker": t,
                "name": sub[0]["name"],
                "n": len(sub),
                "mean_abs_ar": float(np.abs(ar).mean()),
                "abs_sar": float(np.abs(sar).mean() / HALF_NORMAL),
                "share_up": float((ar > 0).mean()),
                "largest": float(ar[np.argmax(np.abs(ar))]),
            }
        )
    return sorted(out, key=lambda r: -r["abs_sar"])


def _fit(X: np.ndarray, y: np.ndarray) -> ImpactModel:
    cut = int(len(y) * 0.7)
    best = None
    for l2 in (0.3, 1.0, 3.0, 10.0, 30.0, 100.0):
        m = ImpactModel(l2=l2).fit(X[:cut], y[:cut])
        ll = m.evaluate(X[cut:], y[cut:], y[:cut])["log_loss"]
        if best is None or ll < best[0]:
            best = (ll, l2)
    assert best is not None
    return ImpactModel(l2=best[1]).fit(X, y)


def train_and_compare(rows: list[dict[str, Any]], split: str) -> dict[str, Any]:
    rows = sorted(rows, key=lambda r: r["date"])
    tr = [r for r in rows if r["date"] < split]
    te = [r for r in rows if r["date"] >= split]
    ev_tr: list[RealEvent] = [r["_event"] for r in tr]
    ev_te: list[RealEvent] = [r["_event"] for r in te]
    Xtr, ytr = feature_matrix(ev_tr), np.array([r["ar"] for r in tr])
    Xte, yte = feature_matrix(ev_te), np.array([r["ar"] for r in te])
    pooled = _fit(Xtr, ytr)
    res: dict[str, Any] = {
        "n_train": len(tr),
        "n_test": len(te),
        "l2": pooled.l2,
        "pooled": pooled.evaluate(Xte, yte, ytr),
        "by_group": {},
        "size_weights": {k: float(pooled.size_w[i]) for i, k in enumerate(FEATURES)},
        "direction_weights": {k: float(pooled.W[i, 2] - pooled.W[i, 0]) for i, k in enumerate(FEATURES)},
    }
    for g in GROUPS:
        m = np.array([r["group"] == g for r in te])
        if m.sum() >= 10:
            res["by_group"][g] = pooled.evaluate(Xte[m], yte[m], ytr)
    # own-stock models on the same test events (stocks with >= 40 training events)
    own_pred, pool_pred, truth = [], [], []
    for t in sorted({r["ticker"] for r in te}):
        a = [r for r in tr if r["ticker"] == t]
        b = [r for r in te if r["ticker"] == t]
        if len(a) < 40 or not b:
            continue
        ma = _fit(feature_matrix([r["_event"] for r in a]), np.array([r["ar"] for r in a]))
        Xb = feature_matrix([r["_event"] for r in b])
        own_pred.append(np.log(ma.size(Xb) + 1e-3))
        pool_pred.append(np.log(pooled.size(Xb) + 1e-3))
        truth.append(np.log(np.abs([r["ar"] for r in b]) + 1e-3))
    if truth:
        tt, op, pp = np.concatenate(truth), np.concatenate(own_pred), np.concatenate(pool_pred)
        res["own_vs_pooled"] = {
            "n": len(tt),
            "size_mae_own": float(np.mean(np.abs(op - tt))),
            "size_mae_pooled": float(np.mean(np.abs(pp - tt))),
            "size_corr_own": float(np.corrcoef(op, tt)[0, 1]),
            "size_corr_pooled": float(np.corrcoef(pp, tt)[0, 1]),
        }
    res["model"] = {
        "tau": pooled.tau,
        "mu": pooled.mu.tolist(),
        "sd": pooled.sd.tolist(),
        "W": pooled.W.tolist(),
        "b": pooled.b.tolist(),
        "size_w": pooled.size_w.tolist(),
        "size_b": pooled.size_b,
        "size_sigma": pooled.size_sigma,
        "features": list(FEATURES),
    }
    return res


def build(root: Path = DATA_ROOT, split: str = "2024-01-01") -> dict[str, Any]:
    t0 = time.perf_counter()
    rows: list[dict[str, Any]] = []
    skipped = []
    for t in tickers_in(root):
        try:
            got = _event_rows(t, root)
        except Exception as e:  # a malformed download should not stop the library
            skipped.append({"ticker": t, "error": str(e)})
            continue
        rows += got
    cat = catalog(rows)
    model = train_and_compare(rows, split)
    biggest = sorted(rows, key=lambda r: -abs(r["sar"]))[:40]
    clean = [{k: v for k, v in r.items() if k != "_event"} for r in rows]
    return json_safe(
        {
            "tickers": sorted({r["ticker"] for r in rows}),
            "n_events": len(rows),
            "split": split,
            "catalog": cat,
            "earnings_by_ticker": per_ticker_earnings(rows),
            "model": model,
            "biggest": [{k: v for k, v in r.items() if k != "_event"} for r in biggest],
            "events": [
                {k: r[k] for k in ("ticker", "date", "form", "group", "ar", "sar", "volume_ratio")}
                for r in clean
            ],
            "skipped": skipped,
            "seconds": time.perf_counter() - t0,
        }
    )


def write_report(lib: dict[str, Any], out: Path) -> Path:
    m = lib["model"]
    p = m["pooled"]
    lines = [
        f"# Event library: {lib['n_events']} filings from {len(lib['tickers'])} stocks",
        "",
        "Generated by `python -m marketsim.event_library`. Abnormal returns from a market model against SPY "
        "(120-day estimation window); |SAR| = 1 means as big as an ordinary day's abnormal move.",
        "",
        "## Isolated effect of each event type",
        "",
        "| event type | events | stocks | mean AR | direction t | share up | mean \\|AR\\| | normal \\|AR\\| | excess \\|AR\\| | \\|SAR\\| | moves > 3 sd | day-0 share of 5-day move | volume x |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in lib["catalog"]:
        lines.append(
            f"| {c['group']} | {c['n']} | {c['tickers']} | {c['mean_ar'] * 100:+.2f}% | {c['t_direction']:+.1f} | "
            f"{c['share_up']:.0%} | {c['mean_abs_ar'] * 100:.2f}% | {c['normal_abs_ar'] * 100:.2f}% | "
            f"{c['excess_abs_ar'] * 100:+.2f}% | {c['abs_sar']:.2f} | {c['share_big']:.0%} | "
            f"{c['day0_share_of_5d']:.0%} | {c['volume_ratio_median']:.2f} |"
        )
    lines += [
        "",
        f"## Impact model trained on all stocks ({m['n_train']} events before {lib['split']}, tested on {m['n_test']} after)",
        "",
        "| | test |",
        "|---|---|",
        f"| Class accuracy (down / flat / up) | {p['accuracy']:.0%} (always-majority {p['majority_accuracy']:.0%}) |",
        f"| Log loss | {p['log_loss']:.3f} (base rates {p['base_rate_log_loss']:.3f}) |",
        f"| Direction hit rate on moves beyond ±1% | {p['direction_hit_rate']:.0%} of {p['n_moves']} |",
        f"| Size: correlation of predicted and actual log \\|AR\\| | {p['size_corr']:.2f} |",
        f"| Size error (mean abs. log) | {p['size_mae_log']:.2f} (constant guess {p['constant_size_mae_log']:.2f}) |",
    ]
    if "own_vs_pooled" in m:
        o = m["own_vs_pooled"]
        lines += [
            "",
            f"Pooled vs each stock's own model, same {o['n']} test events: size correlation "
            f"{o['size_corr_pooled']:.2f} vs {o['size_corr_own']:.2f}, size error {o['size_mae_pooled']:.2f} vs "
            f"{o['size_mae_own']:.2f}.",
        ]
    lines += ["", "## Earnings reactions by stock (|SAR|: how many normal days an earnings day is worth)", ""]
    lines += [
        "| stock | releases | mean \\|AR\\| | \\|SAR\\| | share up | largest |",
        "|---|---|---|---|---|---|",
    ]
    for r in lib["earnings_by_ticker"]:
        lines.append(
            f"| {r['ticker']} | {r['n']} | {r['mean_abs_ar'] * 100:.2f}% | {r['abs_sar']:.2f} | {r['share_up']:.0%} | "
            f"{r['largest'] * 100:+.1f}% |"
        )
    path = out / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Isolated effects of every filing across many stocks.")
    ap.add_argument("--split", default="2024-01-01")
    ap.add_argument("--data-root")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    lib = build(Path(args.data_root) if args.data_root else DATA_ROOT, args.split)
    out = Path(args.out) if args.out else ROOT / "docs" / "experiments" / "events"
    out.mkdir(parents=True, exist_ok=True)
    (out / "library.json").write_text(json.dumps(lib), encoding="utf-8")
    write_report(lib, out)
    for c in lib["catalog"]:
        print(
            f"{c['group']:16s} n={c['n']:5d}  |SAR| {c['abs_sar']:.2f}  excess |AR| {c['excess_abs_ar'] * 100:+.2f}%  "
            f"direction t {c['t_direction']:+.1f}"
        )
    p = lib["model"]["pooled"]
    print(
        f"pooled model: size corr {p['size_corr']:.2f}, direction {p['direction_hit_rate']:.0%} of {p['n_moves']}"
    )
    print(f"wrote {out} ({lib['n_events']} events, {len(lib['tickers'])} stocks) in {lib['seconds']:.0f}s")


if __name__ == "__main__":
    main()
