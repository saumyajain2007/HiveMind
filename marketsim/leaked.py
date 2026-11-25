"""LEAKED / RIGGED results: a thought experiment on what test-set leakage buys. NOT a strategy.

    uv run python -m marketsim.leaked AAPL      # -> docs/experiments/AAPL/leaked/

Every number this module writes uses information from the future and is labelled LEAKED. It
never touches the honest results (results.json, strategy.json). Three tiers:

1. **In-sample overfit.** A ridge predictor of the next day's return is fitted on the *test
   period itself* (2024 onwards), with features that include the true abnormal reaction of every
   filing that reacts the next day (perfect event knowledge) and the oracle agent model run with
   those true reactions. Every feature subset x penalty x position rule is tried and the best on
   the same data is kept: classic data snooping.
2. **Hindsight blend ("rigged").** The prediction is blended with the actual next-day return,
   p = (1 - w) * model + w * truth, and the smallest leak w that reaches the target Sharpe and
   fitness is reported. This is the quantity the experiment is about: how much of the answer
   has to be handed to the model to hit the numbers.
3. **What it would really earn.** The same tier-1 recipe walked forward (each day fitted only
   on earlier days, events at their *predicted* reaction), and the deflated Sharpe of the tier-1
   winner given how many variants were tried.

"Fitness" is the information coefficient (correlation of prediction and next-day return) and
its t-statistic; the target "fitness >= 2" is read as an IC t-statistic of at least 2.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .backtester import Backtest, Costs, Signal, expected_max_sharpe, forecast_fitness, probabilistic_sharpe
from .experiment import ROOT, Experiment, ExperimentConfig, Recalibration
from .realdata import feature_matrix
from .sim import json_safe

BANNER = "LEAKED: uses future data (test-period labels and outcomes). Not achievable; a thought experiment."
FEATURES = (
    "abm_mu",
    "abm_sd",
    "oracle_mu",
    "event_true_ar",
    "earnings_next",
    "ret_1d",
    "ret_5d",
    "ret_20d",
    "trailing_vol",
)
LEAKY = {"oracle_mu", "event_true_ar"}


def _design(exp: Experiment, res: dict[str, Any], ens: Any) -> dict[str, Any]:
    hist = exp.ds.history
    close = hist.close
    origins = [int(o) for o in ens["test_h1_origins"]]
    rc = Recalibration(**res["simulation"]["recalibration"]["1"])
    abm, orc = ens["test_h1"], ens["test_h1_oracle"]
    # filings that react on day o+1: their true abnormal reaction (LEAK) and predicted reaction
    true_ar: dict[int, float] = {}
    pred_ar: dict[int, float] = {}
    for e in exp.labelled:
        shared = e.group != "earnings" and e.reaction_idx in exp.earn_days
        if shared or e.label is None:
            continue
        true_ar[e.reaction_idx] = true_ar.get(e.reaction_idx, 0.0) + float(e.label)
        x = exp._masked_features(e, e.reaction_idx - 1) if e.scheduled else feature_matrix([e])
        pred_ar[e.reaction_idx] = pred_ar.get(e.reaction_idx, 0.0) + float(
            exp.jump_scale * exp.model.expected(x)[0]
        )
    rows = []
    for i, o in enumerate(origins):
        mu, s = rc.params(abm[i], exp.trailing_vol(o))
        lr = np.log(orc[i])
        rows.append(
            {
                "abm_mu": mu,
                "abm_sd": s,
                "oracle_mu": float(lr.mean()),
                "event_true_ar": true_ar.get(o + 1, 0.0),
                "event_pred_ar": pred_ar.get(o + 1, 0.0),
                "earnings_next": float(bool(exp.scheduled_in_horizon(o, 1))),
                "ret_1d": float(math.log(close[o] / close[o - 1])),
                "ret_5d": float(math.log(close[o] / close[o - 5])),
                "ret_20d": float(math.log(close[o] / close[o - 20])),
                "trailing_vol": exp.trailing_vol(o),
                "y": float(close[o + 1] / close[o] - 1.0),
                "date": hist.dates[o + 1],
            }
        )
    return {"rows": rows, "y": np.array([r["y"] for r in rows]), "dates": [r["date"] for r in rows]}


def _ridge(X: np.ndarray, y: np.ndarray, lam: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mu, sd = X.mean(axis=0), X.std(axis=0) + 1e-12
    Z = (X - mu) / sd
    A = np.c_[Z, np.ones(len(y))]
    reg = lam * np.eye(A.shape[1])
    reg[-1, -1] = 0.0
    beta = np.linalg.solve(A.T @ A + reg, A.T @ y)
    return beta, mu, sd


def _predict(X: np.ndarray, fit: tuple[np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
    beta, mu, sd = fit
    return np.c_[(X - mu) / sd, np.ones(len(X))] @ beta


def _positions(pred: np.ndarray, rule: str) -> np.ndarray:
    z = pred / (np.std(pred) + 1e-12)
    if rule == "sign":
        return np.sign(pred)
    if rule == "scaled":
        return np.clip(z, -2.0, 2.0)
    return np.where(np.abs(z) > 0.5, np.sign(pred), 0.0)  # "threshold"


def _fast_sharpe(w: np.ndarray, y: np.ndarray, cost: float) -> float:
    """Annualised Sharpe after costs, without the bootstrap (for the search loops)."""
    net = w * y - np.abs(np.diff(np.concatenate([[0.0], w]))) * cost
    sd = net.std()
    return float(net.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0


def run(ticker: str = "AAPL", target_sharpe: float = 3.5, target_fitness_t: float = 2.0) -> dict[str, Any]:
    out = ROOT / "docs" / "experiments" / ticker.upper()
    res = json.loads((out / "results.json").read_text(encoding="utf-8"))
    ens = np.load(out / "ensembles.npz")
    c = res["config"]
    exp = Experiment(
        ExperimentConfig(
            ticker=ticker,
            split=c["split"],
            n_agents=c["n_agents"],
            agent_params=c.get("agent_params") or {},
            survey=c.get("survey", ""),
        )
    )
    d = _design(exp, res, ens)
    rows, y, dates = d["rows"], d["y"], d["dates"]
    costs = Costs()
    bt = Backtest(dates, y, benchmark=y, costs=costs)
    cost = costs.per_trade
    rules = ("sign", "scaled", "threshold")
    lams = (0.1, 1.0, 10.0, 100.0)

    # ---------------------------------------------------------------- tier 1: in-sample overfit
    trials: list[dict[str, Any]] = []
    for k in range(1, len(FEATURES) + 1):
        for subset in itertools.combinations(FEATURES, k):
            X = np.array([[r[f] for f in subset] for r in rows])
            for lam in lams:
                pred = _predict(X, _ridge(X, y, lam))  # fitted on the test period itself: LEAK
                for rule in rules:
                    sr = _fast_sharpe(_positions(pred, rule), y, cost)
                    trials.append({"features": subset, "lambda": lam, "rule": rule, "sharpe": sr})
    best = max(trials, key=lambda t: t["sharpe"])
    X = np.array([[r[f] for f in best["features"]] for r in rows])
    pred1 = _predict(X, _ridge(X, y, best["lambda"]))
    tier1 = bt.run(Signal("leaked_overfit", "LEAKED in-sample overfit", "", _positions(pred1, best["rule"])))
    sr_trials = np.array([t["sharpe"] for t in trials]) / math.sqrt(252)
    sr0 = expected_max_sharpe(len(trials), float(sr_trials.var(ddof=1)))
    st1 = tier1.stats
    dsr = probabilistic_sharpe(
        st1["sharpe"] / math.sqrt(252), st1["periods"], st1["skew"], st1["kurtosis"] + 3, sr0
    )

    # ---------------------------------------------------------------- tier 2: hindsight blend
    def fitness_t(p: np.ndarray) -> float:
        return float(forecast_fitness(p, 0.5 + 0.5 * np.tanh(p / (np.std(p) + 1e-12)), y)["ic_t"])

    zm = (pred1 - pred1.mean()) / (pred1.std() + 1e-12)
    zy = (y - y.mean()) / (y.std() + 1e-12)
    blend = []
    w_hit = None
    for w in np.round(np.arange(0.0, 1.0001, 0.01), 2):
        p = (1 - w) * zm + w * zy  # LEAK: the actual next-day return
        sr = _fast_sharpe(_positions(p, best["rule"]), y, cost)
        ft = fitness_t(p)
        blend.append({"w": float(w), "sharpe": sr, "fitness_t": ft, "ic": float(np.corrcoef(p, y)[0, 1])})
        if w_hit is None and sr >= target_sharpe and ft >= target_fitness_t:
            w_hit = float(w)
    w_use = w_hit if w_hit is not None else 1.0
    p2 = (1 - w_use) * zm + w_use * zy
    tier2 = bt.run(
        Signal("leaked_rigged", f"LEAKED hindsight blend (w = {w_use:.2f})", "", _positions(p2, best["rule"]))
    )

    # ---------------------------------------------------------------- tier 3: honest walk-forward
    honest_feats = tuple(f for f in best["features"] if f not in LEAKY) or ("abm_mu",)
    Xh = np.array(
        [[r[f] if f != "event_true_ar" else r["event_pred_ar"] for f in honest_feats] for r in rows]
    )
    pred3 = np.zeros(len(y))
    start = 120
    for t in range(start, len(y)):
        pred3[t] = _predict(Xh[t : t + 1], _ridge(Xh[:t], y[:t], best["lambda"]))[0]
    pos3 = np.zeros(len(y))
    pos3[start:] = _positions(pred3[start:], best["rule"])
    tier3 = bt.run(Signal("honest_walk_forward", "Honest walk-forward of the same recipe", "", pos3))
    bh = bt.run(Signal("buy_hold", "Buy and hold", "", np.ones(len(y))))

    def fit_of(p: np.ndarray, mask: slice = slice(None)) -> dict[str, Any]:
        f = forecast_fitness(p[mask], 0.5 + 0.5 * np.tanh(p[mask] / (np.std(p[mask]) + 1e-12)), y[mask])
        f.pop("calibration")
        return f

    def pack(r: Any, fit: dict[str, Any]) -> dict[str, Any]:
        dct = r.to_dict()
        dct.pop("positions")
        dct.pop("trades")
        return {**dct, "fitness": fit}

    return json_safe(
        {
            "banner": BANNER,
            "ticker": ticker.upper(),
            "period": [dates[0], dates[-1]],
            "targets": {"sharpe": target_sharpe, "fitness_ic_t": target_fitness_t},
            "dates": dates,
            "tier1_in_sample_overfit": {
                **pack(tier1, fit_of(pred1)),
                "chosen": best,
                "variants_tried": len(trials),
                "deflated_sharpe": dsr,
                "expected_max_sharpe_by_luck": sr0 * math.sqrt(252),
            },
            "tier2_hindsight_blend": {
                **pack(tier2, fit_of(p2)),
                "leak_weight": w_use,
                "target_reached": w_hit is not None,
                "curve": blend,
            },
            # the demo page's data: the tier-2 run, with prices, positions and trades
            "demo": {
                "dates": dates,
                "close": [float(exp.ds.history.close[exp.ds.history.index_on_or_after(d)]) for d in dates],
                "positions": tier2.positions.tolist(),
                "equity": tier2.equity.tolist(),
                "drawdown": tier2.drawdown.tolist(),
                "buy_hold_equity": bh.equity.tolist(),
                "trades": [t.to_dict() for t in tier2.trades[-40:]],
                "stats": {k: v for k, v in tier2.stats.items() if not isinstance(v, list)},
                "sharpe_ci95": tier2.stats["sharpe_ci95"],
                "fitness": fit_of(p2),
                "features": list(best["features"]),
                "rule": best["rule"],
            },
            "tier3_honest_walk_forward": {
                **pack(tier3, fit_of(pred3, slice(start, None))),
                "features": honest_feats,
            },
            "buy_hold": pack(bh, {}),
        }
    )


def write_report(doc: dict[str, Any], out: Path) -> Path:
    t1, t2, t3, bh = (
        doc["tier1_in_sample_overfit"],
        doc["tier2_hindsight_blend"],
        doc["tier3_honest_walk_forward"],
        doc["buy_hold"],
    )
    lines = [
        f"# {doc['ticker']}: LEAKED / RIGGED results (thought experiment)",
        "",
        f"> **{doc['banner']}**",
        "",
        f"Test period {doc['period'][0]} to {doc['period'][1]}. Generated by `python -m marketsim.leaked`. "
        "The honest results are in `../report.md` and on the Strategy page.",
        "",
        "| | Sharpe | total return | max drawdown | IC | IC t (fitness) |",
        "|---|---|---|---|---|---|",
    ]
    for name, x in (
        (f"LEAKED tier 1: best of {t1['variants_tried']} in-sample overfits", t1),
        (f"LEAKED tier 2: hindsight blend, leak w = {t2['leak_weight']:.2f}", t2),
        ("Honest: same recipe, walked forward", t3),
        ("Buy and hold", bh),
    ):
        f = x.get("fitness") or {}
        ic = f"{f['information_coefficient']:+.3f}" if f else ""
        ict = f"{f['ic_t']:+.1f}" if f else ""
        lines.append(
            f"| {name} | {x['sharpe']:.2f} | {x['total_return'] * 100:+.1f}% | {x['max_drawdown'] * 100:.1f}% | {ic} | {ict} |"
        )
    lines += [
        "",
        f"Tier 1 chose features {', '.join(t1['chosen']['features'])}, ridge lambda {t1['chosen']['lambda']}, "
        f"rule `{t1['chosen']['rule']}`. Its deflated Sharpe, given {t1['variants_tried']} variants tried, is "
        f"{t1['deflated_sharpe']:.2f}; the best Sharpe expected from that many skill-less tries is "
        f"{t1['expected_max_sharpe_by_luck']:.2f}.",
        "",
        f"Tier 2 needed a leak weight of **{t2['leak_weight']:.2f}** (the share of the actual next-day return mixed "
        f"into the prediction) to reach Sharpe >= {doc['targets']['sharpe']} and IC t >= {doc['targets']['fitness_ic_t']}"
        + ("." if t2["target_reached"] else " (not reached even at w = 1)."),
    ]
    p = out / "report.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="LEAKED thought experiment: how much leakage reaches a target Sharpe."
    )
    ap.add_argument("ticker", nargs="?", default="AAPL")
    ap.add_argument("--sharpe", type=float, default=3.5)
    ap.add_argument("--fitness-t", type=float, default=2.0)
    args = ap.parse_args(argv)
    doc = run(args.ticker, args.sharpe, args.fitness_t)
    out = ROOT / "docs" / "experiments" / args.ticker.upper() / "leaked"
    out.mkdir(parents=True, exist_ok=True)
    (out / "leaked.json").write_text(json.dumps(doc), encoding="utf-8")
    write_report(doc, out)
    print(BANNER)
    for k in ("tier1_in_sample_overfit", "tier2_hindsight_blend", "tier3_honest_walk_forward", "buy_hold"):
        x = doc[k]
        f = x.get("fitness") or {}
        print(
            f"{k:28s} Sharpe {x['sharpe']:6.2f}  return {x['total_return'] * 100:+8.1f}%  "
            f"IC {f.get('information_coefficient', float('nan')):+.3f}  IC t {f.get('ic_t', float('nan')):+.1f}"
        )
    t1, t2 = doc["tier1_in_sample_overfit"], doc["tier2_hindsight_blend"]
    print(
        f"tier 1: {t1['variants_tried']} variants, deflated Sharpe {t1['deflated_sharpe']:.2f}; tier 2 leak w = {t2['leak_weight']}"
    )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
