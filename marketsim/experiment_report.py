"""Plots and a Markdown report for `marketsim.experiment` results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from . import viz  # noqa: F401  (house style: rcParams)
from .viz import CATEGORICAL, DOWN, FUNDAMENTAL, INK, MUTED, OFFICIAL, UP

LABEL = {
    "random_walk": "Random walk",
    "event_random_walk": "Event-aware random walk",
    "abm_raw": "Agent model, raw ensemble",
    "abm": "Agent model, recalibrated",
    "abm_oracle": "Agent model + true event reactions (oracle)",
}
COLOR = {
    "random_walk": MUTED,
    "event_random_walk": OFFICIAL,
    "abm_raw": CATEGORICAL[3],
    "abm": UP,
    "abm_oracle": FUNDAMENTAL,
}


def _save(fig: Any, path: Path) -> str:
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path.name


def _dates(rows: list[dict[str, Any]], key: str = "target") -> np.ndarray:
    return np.array([np.datetime64(r[key]) for r in rows])


def plot_forecast_band(rows: list[dict[str, Any]], out: Path, h: int) -> str:
    d = _dates(rows)
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.fill_between(
        d,
        [r["random_walk"]["q05"] for r in rows],
        [r["random_walk"]["q95"] for r in rows],
        color=MUTED,
        alpha=0.18,
        lw=0,
        step="mid",
        label="Random walk 90% interval",
    )
    ax.fill_between(
        d,
        [r["abm"]["q05"] for r in rows],
        [r["abm"]["q95"] for r in rows],
        color=UP,
        alpha=0.30,
        lw=0,
        step="mid",
        label="ABM 90% interval",
    )
    ax.plot(d, [r["actual"] for r in rows], color=INK, lw=1.4, label="Actual close")
    earn = [r for r in rows if r["earnings_in_horizon"]]
    ax.scatter(
        _dates(earn),
        [r["actual"] for r in earn],
        s=26,
        color=OFFICIAL,
        zorder=3,
        edgecolors="white",
        linewidths=1,
        label="Earnings in the horizon",
    )
    ax.set_title(f"{h}-day-ahead forecasts, out of sample")
    ax.set_ylabel("price")
    ax.legend(loc="upper left", ncols=2)
    return _save(fig, out / f"forecast_band_h{h}.png")


def plot_skill(summary: dict[str, Any], out: Path, h: int) -> str:
    groups = [
        ("all", "All days"),
        ("earnings_in_horizon", "Earnings in horizon"),
        ("no_earnings", "Other days"),
    ]
    models = ["event_random_walk", "abm_raw", "abm", "abm_oracle"]
    fig, ax = plt.subplots(figsize=(9, 3.8))
    x = np.arange(len(groups))
    w = 0.2
    for i, m in enumerate(models):
        vals = [summary[g].get(m, {}).get("skill_vs_random_walk", 0.0) * 100 for g, _ in groups]
        off = (i - (len(models) - 1) / 2) * w
        ax.bar(x + off, vals, width=w * 0.92, color=COLOR[m], label=LABEL[m])
        for xi, v in zip(x + off, vals, strict=True):
            ax.annotate(
                f"{v:+.1f}%",
                (xi, v),
                xytext=(0, 3 if v >= 0 else -11),
                textcoords="offset points",
                ha="center",
                fontsize=7,
                color=INK,
            )
    ax.axhline(0, color=INK, lw=0.8)
    ax.set_xticks(x, [f"{name}\n(n={summary[g]['n']})" for g, name in groups])
    ax.set_ylabel("CRPS skill vs random walk (%)")
    ax.set_title(f"Forecast skill, {h}-day horizon (higher is better; 0 = random walk)")
    ax.legend(loc="upper left", fontsize=7)
    return _save(fig, out / f"skill_h{h}.png")


def plot_earnings(rows: list[dict[str, Any]], out: Path, h: int) -> str | None:
    earn = [r for r in rows if r["earnings_in_horizon"]]
    if not earn:
        return None
    fig, ax = plt.subplots(figsize=(10, 4))
    x = np.arange(len(earn))
    for off, m in ((-0.18, "random_walk"), (0.0, "event_random_walk"), (0.18, "abm")):
        lo = np.array([(r[m]["q05"] / r["close"] - 1) * 100 for r in earn])
        hi = np.array([(r[m]["q95"] / r["close"] - 1) * 100 for r in earn])
        ax.vlines(x + off, lo, hi, color=COLOR[m], lw=4, alpha=0.8, label=f"{LABEL[m]} 90%")
    act = np.array([r["actual_return"] * 100 for r in earn])
    ax.scatter(x, act, color=INK, zorder=3, s=30, marker="D", label="Actual move")
    ax.axhline(0, color=MUTED, lw=0.8)
    ax.set_xticks(x, [r["origin"][2:] for r in earn], rotation=45, ha="right", fontsize=7)
    ax.set_ylabel(f"{h}-day return (%)")
    ax.set_title("Earnings releases: predicted 90% intervals vs the actual move")
    ax.legend(loc="lower left", ncols=4, fontsize=7)
    return _save(fig, out / f"earnings_h{h}.png")


def plot_crps_gap(rows: list[dict[str, Any]], out: Path, h: int) -> str:
    d = _dates(rows, "origin")
    gap = np.array([(r["random_walk"]["crps"] - r["abm"]["crps"]) * 100 for r in rows])
    fig, ax = plt.subplots(figsize=(11, 3.2))
    ax.bar(d, gap, width=1.5, color=np.where(gap >= 0, UP, DOWN))
    ax.axhline(0, color=INK, lw=0.8)
    ax.set_ylabel("RW CRPS − ABM CRPS\n(% of price)")
    ax.set_title("Where the agent model beat (up) or lost to (down) the random walk")
    return _save(fig, out / f"crps_gap_h{h}.png")


def plot_impact(res: dict[str, Any], out: Path) -> str:
    w = res["impact_model"]["size_weights"]
    k = sorted(w, key=lambda n: abs(w[n]))[-10:]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.barh(k, [w[n] for n in k], color=[CATEGORICAL[0] if w[n] >= 0 else CATEGORICAL[1] for n in k])
    ax.axvline(0, color=INK, lw=0.8)
    ax.set_title("Impact model: what makes a reaction bigger (standardised weights)")
    return _save(fig, out / "impact_size_weights.png")


def _params(p: dict[str, float]) -> str:
    return ", ".join(f"{k.split('.')[-1]}={v}" for k, v in p.items())


def _pct(x: float, d: int = 1) -> str:
    return f"{x * 100:+.{d}f}%"


def write_report(res: dict[str, Any], out: Path) -> Path:
    plots: list[str] = [plot_impact(res, out)]
    for h, b in res["backtest"].items():
        rows, s = b["origins"], b["summary"]
        hh = int(h)
        plots += [plot_forecast_band(rows, out, hh), plot_skill(s, out, hh), plot_crps_gap(rows, out, hh)]
        if (p := plot_earnings(rows, out, hh)) is not None:
            plots.append(p)
    im = res["impact_model"]
    t = im["test"]
    lines = [
        f"# {res['ticker']} ({res['name']}): real events, trained then tested out of sample",
        "",
        f"Train: {res['period']['train'][0]} to {res['period']['train'][1]} · "
        f"Test: {res['period']['test'][0]} to {res['period']['test'][1]} · "
        f"{res['events']['total']} SEC filings as events ({res['events']['train']} labelled for training, "
        f"{res['events']['test']} in the test period). Generated by `python -m marketsim.experiment {res['ticker']}`.",
        "",
        "## 1. Impact model (classifier + size)",
        "",
        f"Trained on {im['n_train']} past events (L2 = {im['l2']}, picked on the last 30% of the training years), "
        f"tested on {im['n_test']} later ones.",
        "",
        "| | test |",
        "|---|---|",
        f"| Class accuracy (down / flat / up) | {t['accuracy']:.0%} (always-majority: {t['majority_accuracy']:.0%}) |",
        f"| Log loss | {t['log_loss']:.3f} (base rates: {t['base_rate_log_loss']:.3f}) |",
        f"| Direction hit rate on real moves | {t['direction_hit_rate']:.0%} of {t['n_moves']} |",
        f"| Size error, mean abs. log | {t['size_mae_log']:.2f} (constant guess: {t['constant_size_mae_log']:.2f}) |",
        f"| Predicted vs actual size, correlation | {t['size_corr']:.2f} |",
    ]
    if "test_earnings" in im:
        te = im["test_earnings"]
        lines.append(
            f"| Earnings only: direction hit rate / size corr. | {te['direction_hit_rate']:.0%} of {te['n_moves']} / "
            f"{te['size_corr']:.2f} |"
        )
    if im.get("events"):
        big = sorted(im["events"], key=lambda e: -abs(e["actual"]))[:15]
        lines += [
            "",
            "**Predicted vs actual reaction, the 15 biggest test-period events** (abnormal return on the reaction day):",
            "",
            "| reaction day | filing | actual | P(down / flat / up) | predicted size | called it? |",
            "|---|---|---|---|---|---|",
        ]
        for e in big:
            call = "up" if e["p_up"] >= e["p_down"] else "down"
            real = "up" if e["actual"] > 0 else "down"
            lines.append(
                f"| {e['date']} | {e['form']} {', '.join(e['items'])} ({e['group']}) | {_pct(e['actual'])} | "
                f"{e['p_down']:.0%} / {e['p_flat']:.0%} / {e['p_up']:.0%} | ±{e['size'] * 100:.1f}% | "
                f"{'yes' if call == real else 'no'} ({call}) |"
            )
    lines += ["", "![impact weights](impact_size_weights.png)", ""]
    sim = res["simulation"]
    lines += [
        "## 2. Simulation training",
        "",
        "Grid over market parameters, scored by the mean one-day CRPS on training origins:",
        "",
        "| parameters | mean CRPS (% of price) |",
        "|---|---|",
        *[
            f"| {_params(g['params'])} | {g['mean_crps'] * 100:.4f} |"
            for g in sorted(sim["grid"], key=lambda g: g["mean_crps"])
        ],
        "",
        f"Chosen: `{sim['params']}`.",
        "",
    ]
    if sim.get("recalibration"):
        lines += [
            "**Recalibration** (fitted on the same training origins): log return ~ Normal(shrink x ensemble mean, "
            "sqrt((spread x ensemble sd)^2 + (vol weight x trailing vol)^2)).",
            "",
            "| horizon | shrink | spread | vol weight | training CRPS, raw -> recalibrated (log-return %) |",
            "|---|---|---|---|---|",
            *[
                f"| {h} d | {r['shrink']:.2f} | {r['spread']:.2f} | {r['vol_weight']:.2f} | "
                f"{r['raw_train_crps'] * 100:.3f} -> {r['train_crps'] * 100:.3f} |"
                for h, r in sim["recalibration"].items()
            ],
            "",
        ]
    for h, b in res["backtest"].items():
        s, rows = b["summary"], b["origins"]
        lines += [
            f"## 3. Out-of-sample backtest, {h}-day horizon ({s['all']['n']} forecasts)",
            "",
            "| model | CRPS (% of price) | skill vs RW | 90% coverage | direction acc. | Brier (up) |",
            "|---|---|---|---|---|---|",
        ]
        for m in LABEL:
            if m not in s["all"]:
                continue
            x = s["all"][m]
            lines.append(
                f"| {LABEL[m]} | {x['mean_crps_pct']:.3f} | {_pct(x['skill_vs_random_walk'])} | {x['coverage_90']:.0%} | "
                f"{x['direction_accuracy']:.0%} | {x['brier_up']:.3f} |"
            )
        lines += ["", "| skill vs random walk | earnings in horizon | other days |", "|---|---|---|"]
        for m in ("event_random_walk", "abm_raw", "abm", "abm_oracle"):
            e, o = s["earnings_in_horizon"], s["no_earnings"]
            if m not in o:
                continue
            lines.append(
                f"| {LABEL[m]} | {_pct(e[m]['skill_vs_random_walk']) if e['n'] else '–'} (n={e['n']}) | "
                f"{_pct(o[m]['skill_vs_random_walk'])} (n={o['n']}) |"
            )
        # biggest differences between the models
        diff = sorted(rows, key=lambda r: -abs(r["abm"]["crps"] - r["random_walk"]["crps"]))[:12]
        lines += [
            "",
            "**Biggest differences between the agent model and the random walk** (CRPS gap, % of price):",
            "",
            "| origin → target | actual move | RW 90% | ABM 90% | ABM P(up) | RW CRPS | ABM CRPS | earnings? |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in diff:
            c = r["close"]
            lines.append(
                f"| {r['origin']} → {r['target']} | {_pct(r['actual_return'])} | "
                f"{_pct(r['random_walk']['q05'] / c - 1)} … {_pct(r['random_walk']['q95'] / c - 1)} | "
                f"{_pct(r['abm']['q05'] / c - 1)} … {_pct(r['abm']['q95'] / c - 1)} | {r['abm']['p_up']:.0%} | "
                f"{r['random_walk']['crps'] * 100:.2f} | {r['abm']['crps'] * 100:.2f} | "
                f"{'yes' if r['earnings_in_horizon'] else ''} |"
            )
        earn = [r for r in rows if r["earnings_in_horizon"] and r["origin"] == r["origin"]]
        if earn and h == "1":
            lines += [
                "",
                "**Every earnings release in the test period** (one day ahead, forecast made at the close before):",
                "",
                "| release day | actual move | RW 90% | event-RW 90% | ABM 90% | ABM P(up) | oracle median | winner (CRPS) |",
                "|---|---|---|---|---|---|---|---|",
            ]
            for r in earn:
                c = r["close"]
                best = min(("random_walk", "event_random_walk", "abm"), key=lambda m: r[m]["crps"])
                lines.append(
                    f"| {r['target']} | {_pct(r['actual_return'])} | "
                    f"{_pct(r['random_walk']['q05'] / c - 1)} … {_pct(r['random_walk']['q95'] / c - 1)} | "
                    f"{_pct(r['event_random_walk']['q05'] / c - 1)} … {_pct(r['event_random_walk']['q95'] / c - 1)} | "
                    f"{_pct(r['abm']['q05'] / c - 1)} … {_pct(r['abm']['q95'] / c - 1)} | {r['abm']['p_up']:.0%} | "
                    f"{_pct(r['abm_oracle']['median'] / c - 1)} | {LABEL[best]} |"
                )
        lines += [
            "",
            f"![forecast band](forecast_band_h{h}.png)",
            "",
            f"![skill](skill_h{h}.png)",
            "",
            f"![crps gap](crps_gap_h{h}.png)",
            "",
        ]
        if f"earnings_h{h}.png" in plots:
            lines += [f"![earnings](earnings_h{h}.png)", ""]
    lines += [
        "## How to read this",
        "",
        "- **CRPS** scores the whole forecast distribution against what happened (lower is better); "
        "**skill** = 1 − CRPS / CRPS(random walk).",
        "- The **oracle** knows every event's true reaction, including future unscheduled ones: it is an upper "
        "bound on what event knowledge could add, not a forecast.",
        "- Daily returns of a large stock are close to unpredictable in direction; realistic gains come from "
        "getting the *spread* right (wider before earnings, tighter on quiet days).",
        "",
    ]
    path = out / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
