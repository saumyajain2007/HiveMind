"""Real-data population inputs (US Census + Federal Reserve SCF), see scripts/fetch_population_data.py.

`PopulationConfig.survey = "us"` (the default) replaces these PLACEHOLDER values with data from
`data/population/us.json`:

* the **age** marginal: Census Vintage 2024 adult age distribution (empirical quantiles);
* the **wealth** marginal: SCF 2022 household financial assets (empirical, log-interpolated);
* the **knowledge** marginal: SCF 0-10 self-rated financial knowledge, scaled to 0-1;
* the **investor share**: SCF share of households owning stocks directly (21%);
* the **investor logit**: SCF weighted logistic regression of stock ownership on the normal
  scores of wealth, knowledge and risk tolerance;
* **correlations** between age, wealth, knowledge and risk tolerance (SCF, normal scores).

Every other trait (impulsiveness, belief tolerance, media attention, loss aversion, the
investor-category mix) and the social graph keep their PLACEHOLDER values: these surveys do not
measure them. `survey = ""` restores the placeholders everywhere.
"""

from __future__ import annotations

import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import PopulationConfig

DATA = Path(__file__).resolve().parents[1] / "data" / "population"


@lru_cache(maxsize=4)
def load_survey(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))
    return doc


def apply_survey(pc: PopulationConfig) -> PopulationConfig:
    if not pc.survey:
        return pc
    s = load_survey(pc.survey)
    marginals = dict(pc.marginals)
    marginals["age"] = ("empirical", tuple(s["age_quantiles"]))
    marginals["wealth"] = ("empirical_log", tuple(s["wealth_quantiles"]))
    marginals["knowledge"] = ("empirical", tuple(s["knowledge_quantiles"]))
    corr = dict(pc.correlations)
    for k, v in s["correlations"].items():
        a, b = k.split(",")
        corr.pop((b, a), None)
        corr[(a, b)] = float(v)
    return replace(
        pc,
        marginals=marginals,
        correlations=corr,
        investor_share=float(s["investor_share"]),
        investor_logit={k: float(v) for k, v in s["investor_logit"].items()},
    )
