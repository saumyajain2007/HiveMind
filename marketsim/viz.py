"""Static plots for `run_demo` and the README (issue #11, HANDOFF §4 M4).

Colours are the web app's light-theme tokens (validated for contrast and colour-blind
separation in #19): teal/rose for up/down, violet for narratives, amber for official news,
dashed blue for V_true, and the six categorical hues in a fixed order for families. Every
multi-series chart has a legend, and series also differ by line style or marker shape.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PathCollection

from .config import ALL_PLATFORMS, CATEGORIES, TICKS_PER_DAY
from .metrics import acf, excess_kurtosis, open_tick_returns
from .montecarlo import MonteCarloResult

INK, MUTED, GRID, AXIS = "#0f1420", "#566074", "#eef1f5", "#d5dbe4"
UP, DOWN, NARRATIVE, OFFICIAL, FUNDAMENTAL = "#0d9488", "#e11d48", "#6250d6", "#eda100", "#1c5cab"
CATEGORICAL = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#6250d6", "#e34948")
OTHER = "#9aa3b2"
MARKERS = {"event": "o", "mutation": "^", "invention": "s", "price_news": "D"}
LINESTYLES = ("-", "--", "-.", ":", (0, (5, 1)), (0, (3, 1, 1, 1)))

plt.rcParams.update(
    {
        "figure.dpi": 110,
        "savefig.dpi": 140,
        "font.size": 9,
        "axes.edgecolor": AXIS,
        "axes.labelcolor": MUTED,
        "axes.titlecolor": INK,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "legend.frameon": False,
        "legend.fontsize": 8,
        "lines.linewidth": 2.0,
    }
)


def _days(n: int) -> np.ndarray:
    return np.arange(n) / TICKS_PER_DAY


def _save(fig: Any, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def _event_markers(ax: Any, events: Sequence[Mapping[str, Any]]) -> None:
    shown = [ev for ev in events if ev["kind"] != "price_move"]
    for i, ev in enumerate(shown):
        colour = NARRATIVE if ev["kind"] in ("rumour", "leak") else OFFICIAL
        x = ev["injected"] / TICKS_PER_DAY
        ax.axvline(x, color=colour, lw=1.2, ls=":", zorder=1)
        label = ev.get("label") or ev["kind"]
        ax.annotate(
            label if len(label) <= 28 else label[:27] + "…",
            (x, 1.0),
            xycoords=("data", "axes fraction"),
            xytext=(3, -6 - 11 * (i % 3)),
            textcoords="offset points",
            fontsize=7,
            color=INK,
            rotation=0,
            va="top",
        )


# --------------------------------------------------------------------------- price fan


def fan_chart(mc: MonteCarloResult, path: Path) -> Path:
    q = mc.quantiles()
    x = _days(mc.paths.shape[1])
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.fill_between(x, q["0.05"], q["0.95"], color=UP, alpha=0.14, lw=0, label="5–95%")
    ax.fill_between(x, q["0.25"], q["0.75"], color=UP, alpha=0.30, lw=0, label="25–75%")
    ax.plot(x, q["0.5"], color=UP, lw=2, label="median")
    ax.plot(x, mc.v_true.mean(axis=0), color=FUNDAMENTAL, lw=1.6, ls="--", label="V_true (hidden)")
    if mc.representative is not None:
        _event_markers(ax, mc.representative["events"])
    ax.set_xlabel("day")
    ax.set_ylabel("price")
    ax.set_title(f"Price paths, {mc.n_runs} Monte Carlo runs")
    ax.legend(loc="lower left", ncols=4)
    return _save(fig, path)


# --------------------------------------------------------------------------- awareness


def _top_families(res: Mapping[str, Any], k: int = 6) -> list[dict[str, Any]]:
    fams = [f for f in res["summary"]["families"] if f["aware"] > 0]
    top = sorted(fams, key=lambda f: -f["aware"])[:k]
    return sorted(top, key=lambda f: f["root"])  # colour follows the family, not its rank


def _family_name(f: Mapping[str, Any]) -> str:
    label = f.get("label") or f.get("kind") or f["origin"]
    label = label if len(label) <= 30 else label[:29] + "…"
    return f"#{f['root']} {label}"


def family_awareness(res: Mapping[str, Any], path: Path, share: bool = True) -> Path:
    fam = np.asarray(res["family"])
    n = res["meta"]["n_nodes"]
    T = res["meta"]["n_ticks"]
    fig, ax = plt.subplots(figsize=(9, 4))
    for i, f in enumerate(_top_families(res)):
        rows = fam[fam[:, 1] == f["root"]]
        if not len(rows):
            continue
        # carry the last count forward once the family has no active item
        curve = np.full(T, np.nan)
        curve[rows[:, 0]] = rows[:, 2]
        start = int(rows[0, 0])
        last = np.maximum.accumulate(np.where(np.isnan(curve), -1, curve))
        curve = np.where(np.arange(T) >= start, last, np.nan)
        y = curve / n if share else curve
        ax.plot(_days(T), y, color=CATEGORICAL[i], ls=LINESTYLES[i], label=_family_name(f))
    ax.set_xlabel("day")
    ax.set_ylabel("share of agents aware" if share else "agents aware")
    ax.set_title("Awareness of each event family (root + mutations + follow-ups)")
    ax.legend(loc="upper left")
    return _save(fig, path)


def awareness_breakdown(
    res: Mapping[str, Any], pop_category: np.ndarray, pop_platforms: np.ndarray, path: Path
) -> Path:
    """Final share aware within each category and among each platform's users, per family."""
    fam = np.asarray(res["family"])
    tops = _top_families(res, 4)
    cat_size = np.bincount(pop_category, minlength=len(CATEGORIES))
    plat_size = pop_platforms.sum(axis=0)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    width = 0.8 / max(len(tops), 1)
    for i, f in enumerate(tops):
        rows = fam[fam[:, 1] == f["root"]]
        if not len(rows):
            continue
        last = rows[np.argmax(rows[:, 2])]
        plats = last[3 : 3 + len(ALL_PLATFORMS)] / np.maximum(plat_size, 1)
        cats = last[3 + len(ALL_PLATFORMS) :] / np.maximum(cat_size, 1)
        for ax, vals in ((axes[0], cats), (axes[1], plats)):
            xs = np.arange(len(vals)) + (i - (len(tops) - 1) / 2) * width
            ax.bar(xs, vals, width=width * 0.9, color=CATEGORICAL[i], label=_family_name(f))
    axes[0].set_xticks(np.arange(len(CATEGORIES)), [c.replace("_", " ") for c in CATEGORIES])
    axes[1].set_xticks(np.arange(len(ALL_PLATFORMS)), ALL_PLATFORMS)
    axes[0].set_title("Peak share aware, by category")
    axes[1].set_title("… and among each platform's users")
    axes[0].set_ylabel("share aware")
    axes[1].legend(loc="upper right")
    return _save(fig, path)


# --------------------------------------------------------------------------- lineage


def lineage_tree(res: Mapping[str, Any], path: Path) -> Path:
    lineage = res["lineage"]
    roots = {f["root"]: i for i, f in enumerate(_top_families(res))}
    fig, ax = plt.subplots(figsize=(9, 4.4))
    by_id = {r["id"]: r for r in lineage}
    for r in lineage:
        if r["parent"] >= 0:
            p = by_id[r["parent"]]
            colour = CATEGORICAL[roots[r["root"]]] if r["root"] in roots else OTHER
            xs = np.array([p["born"], r["born"]]) / TICKS_PER_DAY
            ax.plot(xs, [p["sentiment"], r["sentiment"]], color=colour, lw=1.0, alpha=0.7, zorder=1)
    biggest = max([r["final_aware"] for r in lineage] + [1])
    for origin, marker in MARKERS.items():
        rs = [r for r in lineage if r["origin"] == origin]
        if not rs:
            continue
        colours = [CATEGORICAL[roots[r["root"]]] if r["root"] in roots else OTHER for r in rs]
        sizes = [20 + 300 * np.sqrt(r["final_aware"] / biggest) for r in rs]
        ax.scatter(
            [r["born"] / TICKS_PER_DAY for r in rs],
            [r["sentiment"] for r in rs],
            s=sizes,
            c=colours,
            marker=marker,
            edgecolors="white",
            linewidths=1.0,
            label=origin.replace("_", " "),
            zorder=2,
        )
    ax.axhline(0, color=AXIS, lw=1)
    ax.set_ylim(-1.1, 1.1)
    ax.set_xlabel("born (day)")
    ax.set_ylabel("sentiment")
    ax.set_title("Narrative lineage (size = final awareness, shape = origin, colour = family)")
    leg = ax.legend(loc="lower left", ncols=4)
    for h in leg.legend_handles:  # legend shows shape only: neutral colour, one size
        if isinstance(h, PathCollection):
            h.set_sizes([40])
            h.set_facecolor(MUTED)
    return _save(fig, path)


# --------------------------------------------------------------------------- stylised facts


def stylized_facts(paths: np.ndarray, path: Path, lags: int = 10) -> Path:
    rets = [open_tick_returns(p) for p in np.atleast_2d(paths)]
    pooled = np.concatenate(rets)
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    ax = axes[0]
    sd = pooled.std() or 1e-9
    z = pooled / sd
    bins = np.linspace(-6, 6, 61)
    ax.hist(
        z, bins=bins, density=True, color=UP, alpha=0.6, label="open-tick returns", edgecolor="white", lw=0.5
    )
    xs = np.linspace(-6, 6, 400)
    ax.plot(xs, np.exp(-0.5 * xs**2) / np.sqrt(2 * np.pi), color=INK, ls="--", lw=1.5, label="normal")
    ax.set_yscale("log")
    ax.set_ylim(1e-4, 1)
    ax.set_xlabel("return / sd")
    ax.set_title(f"Return distribution (excess kurtosis {excess_kurtosis(pooled):.2f})")
    ax.legend(loc="upper right")
    ax = axes[1]
    a_r = np.nanmean([acf(r, lags) for r in rets], axis=0)
    a_abs = np.nanmean([acf(np.abs(r), lags) for r in rets], axis=0)
    k = np.arange(1, lags + 1)
    ax.bar(k - 0.2, a_r, width=0.38, color=FUNDAMENTAL, label="r")
    ax.bar(k + 0.2, a_abs, width=0.38, color=OFFICIAL, label="|r|")
    band = 1.96 / np.sqrt(max(np.mean([len(r) for r in rets]), 1))
    ax.axhspan(-band, band, color=GRID, zorder=0)
    ax.axhline(0, color=AXIS, lw=1)
    ax.set_xticks(k)
    ax.set_xlabel("lag (open ticks)")
    ax.set_title("Autocorrelation of r and |r|")
    ax.legend(loc="upper right")
    return _save(fig, path)


def all_plots(
    mc: MonteCarloResult, out: Path, pop_category: np.ndarray, pop_platforms: np.ndarray
) -> list[Path]:
    rep = mc.representative
    paths = [fan_chart(mc, out / "fan_chart.png"), stylized_facts(mc.paths, out / "stylized_facts.png")]
    if rep is not None:
        paths += [
            family_awareness(rep, out / "family_awareness.png"),
            awareness_breakdown(rep, pop_category, pop_platforms, out / "awareness_breakdown.png"),
            lineage_tree(rep, out / "lineage_tree.png"),
        ]
    return paths
