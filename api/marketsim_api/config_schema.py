"""Pydantic models generated from the engine's `config.py` dataclasses.

`config.py` is the single source of truth for parameter names, types and defaults. This
module reads it at import time and builds one Pydantic model per section (population, graph,
diffusion, belief, trading, market). Each field carries its default, an allowed range (from
`FIELD_RANGES` below), a description taken from the comment next to the field in `config.py`,
and `placeholder: true` when that comment says PLACEHOLDER.

Non-JSON shapes in `config.py` get a JSON form here:
  * correlations {("age", "wealth"): 0.45}         -> [{"a": "age", "b": "wealth", "rho": 0.45}]
  * per-category dicts {LONG_TERM: ...}             -> {"long_term": ...}
  * tuples                                          -> fixed-length arrays
`parameters_to_engine` / `engine_to_parameters` convert both ways without loss.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import io
import tokenize
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from marketsim import config as engine_config

# Section name in the API -> dataclass in config.py, in display order.
SECTIONS: dict[str, type] = {
    "population": engine_config.PopulationConfig,
    "graph": engine_config.GraphConfig,
    "diffusion": engine_config.DiffusionConfig,
    "belief": engine_config.BeliefConfig,
    "trading": engine_config.TradingConfig,
    "market": engine_config.MarketConfig,
}

# Copula traits (HANDOFF §4 M1). TODO(#2): import COPULA_TRAITS from marketsim.population.
COPULA_TRAITS = (
    "age",
    "wealth",
    "impulsiveness",
    "risk_tolerance",
    "knowledge",
    "belief_tolerance",
    "media_attention",
    "loss_aversion",
)
INVESTOR_CATEGORIES = tuple(
    engine_config.CATEGORIES[i]
    for i in (engine_config.LONG_TERM, engine_config.SWING, engine_config.DAY_TRADER)
)
_CATEGORY_ID = {name: i for i, name in enumerate(engine_config.CATEGORIES)}

# Allowed ranges (inclusive) for every scalar field, and for the values of dict fields.
# A test checks that every numeric field in config.py has an entry here.
FIELD_RANGES: dict[str, tuple[float, float]] = {
    "market.mm_flow_anticipation": (0.0, 1.5),
    "market.flow_rho_ewma": (0.5, 0.999),
    "market.noise_vol_feedback": (0.0, 2.0),
    "market.noise_permanence": (0.0, 1.0),
    "market.noise_intraday_profile": (0.0, 5.0),
    "market.intraday_vol_ewma": (0.5, 0.995),
    "diffusion.mutate_ref_agents": (100.0, 10_000_000.0),
    # population
    "population.investor_share": (0.0, 1.0),
    "population.media_per_100k": (0.0, 1000.0),
    "population.community_mean_size": (2.0, 1000.0),
    "population.correlations": (-0.99, 0.99),
    "population.psd_eps": (1e-12, 0.1),
    "population.investor_logit": (-10.0, 10.0),
    "population.intensity_beta": (0.01, 100.0),
    "population.online_width": (0.1, 12.0),
    "population.community_size_sigma": (0.0, 3.0),
    "population.community_age_noise": (0.0, 50.0),
    "population.interest_concentration": (0.01, 100.0),
    "population.community_interest_mix": (0.0, 1.0),
    "population.influence_alpha": (1.01, 10.0),
    "population.media_influence_mult": (1.0, 1000.0),
    "population.media_credibility_beta": (0.01, 100.0),
    "population.media_bias_sd": (0.0, 2.0),
    "population.confidence_sd": (0.0, 1.0),
    "population.long_term_initial_position": (0.0, 1.0),
    "population.perceived_value_noise": (0.0, 1.0),
    # graph
    "graph.twitter_mean_out": (0.0, 1000.0),
    "graph.twitter_homophily": (0.0, 1.0),
    "graph.instagram_mean_out": (0.0, 1000.0),
    "graph.instagram_homophily": (0.0, 1.0),
    "graph.friendship_mean_degree": (0.0, 500.0),
    "graph.friendship_homophily": (0.0, 1.0),
    "graph.triadic_closure": (0.0, 2.0),
    "graph.reddit_mean_memberships": (1.0, 50.0),
    "graph.reddit_agents_per_sub": (10.0, 1_000_000.0),
    "graph.youtube_creator_share": (0.0001, 1.0),
    "graph.youtube_mean_subs": (1.0, 500.0),
    "graph.youtube_lag_ticks": (0, 960),
    "graph.youtube_homophily": (0.0, 1.0),
    "graph.degree_sigma": (0.0, 3.0),
    "graph.reddit_zipf": (0.0, 3.0),
    "graph.reach": (0.0, 10.0),
    "graph.trust": (0.0, 5.0),
    "graph.attention_boost": (0.0, 10.0),
    # diffusion
    "diffusion.base_online": (0.0, 1.0),
    "diffusion.attention_slots": (1, 50),
    "diffusion.base_share": (0.0, 1.0),
    "diffusion.broadcast_rate": (0.0, 1.0),
    "diffusion.salience_decay": (0.0, 1.0),
    "diffusion.retire_salience": (0.0, 1.0),
    "diffusion.share_ttl": (1, 960),
    "diffusion.exposure_scale": (0.0, 100.0),
    "diffusion.outrage_weight": (0.0, 5.0),
    "diffusion.max_items": (8, 4096),
    "diffusion.mutate_rate": (0.0, 1.0),
    "diffusion.invent_rate": (0.0, 1.0),
    "diffusion.invent_threshold": (0.0, 1.0),
    "diffusion.price_news_threshold": (0.0, 1.0),
    # belief
    "belief.mu0": (0.0, 2.0),
    "belief.impact_to_sentiment": (0.0, 100.0),
    "belief.adopt_rate": (0.0, 1.0),
    "belief.narrative_pull": (0.0, 1.0),
    "belief.confidence_decay": (0.0, 1.0),
    "belief.adopt_step": (0.0, 1.0),
    "belief.invent_credibility": (0.0, 1.0),
    "belief.invent_salience": (0.0, 1.0),
    # trading
    "trading.strategy_prior": (0.0, 1.0),
    "trading.horizon_days": (0.01, 1000.0),
    "trading.momentum_ticks": (1, 100_000),
    "trading.sentiment_scale": (0.0, 1.0),
    "trading.switching": (0.0, 1.0),
    "trading.switching_intensity": (0.0, 10_000.0),
    "trading.fitness_decay": (0.0, 1.0),
    "trading.risk_aversion": (0.0, 100.0),
    "trading.panic_loss": (0.0, 1.0),
    "trading.panic_rate": (0.0, 1.0),
    "trading.trading_online_boost": (0.0, 20.0),
    # market
    "market.initial_price": (0.01, 1_000_000.0),
    "market.implied_vol": (0.01, 5.0),
    "market.impact_Y": (0.01, 10.0),
    "market.adv_turnover": (0.0, 1.0),
    "market.adv_ewma": (0.0, 1.0),
    "market.mm_news_pass_through": (0.0, 2.0),
    "market.noise_frac": (0.0, 5.0),
    "market.circuit_breaker": (0.001, 1.0),
    "market.option_maturity_days": (1.0, 3650.0),
    "market.risk_free_rate": (-0.1, 0.5),
    "market.vol_ewma_lambda": (0.0, 0.999),
    "market.trading_days_per_year": (200, 366),
    "market.n_prop_firms": (0, 100),
    "market.n_funds": (0, 100),
    "market.firm_capital_share": (0.0, 10.0),
    "market.prop_momentum_ticks": (1, 960),
    "market.prop_momentum_k": (0.0, 10_000.0),
    "market.prop_imbalance_k": (0.0, 100.0),
    "market.fund_value_k": (0.0, 100.0),
    "market.fund_lag_ticks": (0, 9600),
    "market.company_buyback_programme": (0.0, 1.0),
    "market.company_buyback_threshold": (0.0, 1.0),
    "market.company_buyback_daily": (0.0, 1.0),
}

# Descriptions for fields whose comment in config.py does not describe them on its own.
DESCRIPTION_OVERRIDES: dict[str, str] = {
    "population.media_influence_mult": "Influence multiplier for media outlets.",
    "population.media_credibility_beta": "Beta(a, b) distribution of media outlets' credibility.",
    "population.confidence_sd": "Spread of agents' initial confidence, N(0, sd).",
    "population.media_bias_sd": "Spread of media outlets' editorial bias, N(0, sd) clipped to [-1, 1].",
    "graph.platforms": "Platforms switched on. All six are on by default; turn some off to compare.",
    "graph.reach": "Exposure per sharer per tick on each platform.",
    "graph.trust": "How much people trust what reaches them on each platform (belief weight).",
    "trading.strategy_prior": "Strategy mix (fundamentalist, chartist, sentiment) per investor category.",
    "trading.horizon_days": "Holding horizon per investor category, in days.",
    "trading.momentum_ticks": "Momentum look-back per investor category, in ticks.",
    "population.correlations": "Trait correlations for the Gaussian copula (repaired to PSD before use).",
    "graph.twitter_mean_out": "Mean number of accounts a Twitter user follows (scaled by activity).",
    "graph.instagram_mean_out": "Mean number of accounts an Instagram user follows (scaled by activity).",
    "graph.friendship_mean_degree": "Mean number of friends per person.",
    "graph.friendship_homophily": "Share of friendships inside the person's offline community.",
    "graph.reddit_mean_memberships": "Mean number of subreddits a Reddit user belongs to.",
    "graph.reddit_agents_per_sub": "Agents per subreddit; the number of subreddits is N divided by this.",
    "graph.youtube_creator_share": "Share of YouTube users who are creators (the most influential).",
    "graph.youtube_mean_subs": "Mean number of creators a YouTube user subscribes to.",
    "diffusion.base_share": "Base probability of sharing an item just seen.",
    "diffusion.retire_salience": "Items below this salience with no sharers are retired.",
    "diffusion.mutate_rate": "Base probability that a sharer mutates a narrative.",
    "diffusion.invent_rate": "Base probability of inventing a narrative after a big unexplained move.",
    "belief.adopt_rate": "Base probability of adopting a narrative that moved the agent's belief.",
    "trading.switching_intensity": "How sharply strategy weights favour the best recent performer.",
    "trading.risk_aversion": "Risk aversion in position sizing.",
    "trading.panic_rate": "Base probability of selling out once the panic loss is reached.",
    "market.initial_price": "Starting share price.",
    "market.trading_days_per_year": "Trading days per year, for annualising volatility.",
    "market.n_prop_firms": "Number of prop-trading firms (short-horizon momentum).",
    "market.n_funds": "Number of funds (fundamental value, known with a 1-day lag).",
    "market.prop_imbalance_k": "Weight of last tick's order imbalance in prop firms' target.",
}


# --------------------------------------------------------------------------- comments in config.py


def _clean_comment(t: str) -> str:
    t = t.replace("PLACEHOLDER:", "").replace("-- PLACEHOLDER", "").replace("PLACEHOLDER", "")
    return " ".join(t.split()).strip(" -:")


def _config_comments() -> dict[str, tuple[str, bool]]:
    """Map 'section.field' -> (description, placeholder) from the comments in config.py.

    The description is the comment on the field's first line or, failing that, the block of
    comment lines directly above it. `placeholder` is True if that comment says PLACEHOLDER.
    """
    src = inspect.getsource(engine_config)
    lines = src.splitlines()
    comments: dict[int, str] = {}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            comments[tok.start[0]] = tok.string.lstrip("#").strip()
    by_class = {cls.__name__: section for section, cls in SECTIONS.items()}
    out: dict[str, tuple[str, bool]] = {}
    for node in ast.parse(src).body:
        if not (isinstance(node, ast.ClassDef) and node.name in by_class):
            continue
        for stmt in node.body:
            if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                continue
            trailing = comments.get(stmt.lineno, "")
            above: list[str] = []
            ln = stmt.lineno - 1
            while ln >= 1 and lines[ln - 1].strip().startswith("#"):
                above.insert(0, comments.get(ln, ""))
                ln -= 1
            block = " ".join(above)
            # The trailing comment wins unless it is only a marker ("# PLACEHOLDER").
            text = _clean_comment(trailing) or _clean_comment(block)
            placeholder = "PLACEHOLDER" in trailing or "PLACEHOLDER" in block
            out[f"{by_class[node.name]}.{stmt.target.id}"] = (text[:1].upper() + text[1:], placeholder)
    return out


FIELD_COMMENTS = _config_comments()


# --------------------------------------------------------------------------- JSON shapes


class Correlation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str = Field(description="First trait")
    b: str = Field(description="Second trait")
    rho: float = Field(ge=-0.99, le=0.99, description="Target correlation")

    @field_validator("a", "b")
    @classmethod
    def _known_trait(cls, v: str) -> str:
        if v not in COPULA_TRAITS:
            raise ValueError(f"unknown trait {v!r}; expected one of {COPULA_TRAITS}")
        return v


def _int_keyed(d: Any) -> bool:
    return isinstance(d, dict) and bool(d) and all(isinstance(k, int) and not isinstance(k, bool) for k in d)


def _jsonify(v: Any) -> Any:
    """Engine value -> JSON: tuples become lists, category-id keys become category names."""
    if isinstance(v, dict):
        if _int_keyed(v):
            return {engine_config.CATEGORIES[k]: _jsonify(x) for k, x in v.items()}
        return {k: _jsonify(x) for k, x in v.items()}
    if isinstance(v, (tuple, list)):
        return [_jsonify(x) for x in v]
    return v


def _engineify(v: Any, template: Any) -> Any:
    """JSON -> engine value, using the engine default as a template for tuples and keys."""
    if isinstance(template, dict) and isinstance(v, dict):
        int_keys = _int_keyed(template)
        sample = next(iter(template.values()), None)
        out = {}
        for k, x in v.items():
            ek = _CATEGORY_ID[k] if int_keys else k
            out[ek] = _engineify(x, template.get(ek, sample))
        return out
    if isinstance(template, tuple) and isinstance(v, (list, tuple)):
        if len(v) == len(template):
            return tuple(_engineify(x, t) for x, t in zip(v, template, strict=True))
        return tuple(_engineify(x, template[0] if template else None) for x in v)
    return v


def _to_json_value(section: str, name: str, value: Any) -> Any:
    if section == "population" and name == "correlations":
        return [{"a": a, "b": b, "rho": rho} for (a, b), rho in value.items()]
    return _jsonify(value)


def _to_engine_value(section: str, name: str, value: Any, default: Any) -> Any:
    if section == "population" and name == "correlations":
        return {(c["a"], c["b"]): float(c["rho"]) for c in value}
    return _engineify(value, default)


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _shape(default_json: Any) -> str:
    """number | numlist (fixed-length numbers) | nummap (str -> number or numlist) | json."""
    if _is_number(default_json):
        return "number"
    if isinstance(default_json, list) and default_json and all(_is_number(x) for x in default_json):
        return "numlist"
    if isinstance(default_json, dict) and default_json:
        vals = list(default_json.values())
        if all(_is_number(x) for x in vals) or all(_shape(x) == "numlist" for x in vals):
            return "nummap"
    return "json"


# --------------------------------------------------------------------------- model generation


def _range(key: str) -> tuple[float, float] | None:
    return FIELD_RANGES.get(key)


def _meta(key: str) -> tuple[str, bool]:
    desc, placeholder = FIELD_COMMENTS.get(key, ("", False))
    return DESCRIPTION_OVERRIDES.get(key, desc), placeholder


def _field_spec(section: str, f: dataclasses.Field[Any], default_json: Any) -> tuple[Any, Any]:
    key = f"{section}.{f.name}"
    desc, placeholder = _meta(key)
    extra: dict[str, Any] = {"placeholder": placeholder}
    rng = _range(key)
    lo, hi = rng if rng else (None, None)

    def field(**kw: Any) -> Any:
        return Field(default=default_json, description=desc or None, json_schema_extra=extra, **kw)

    if section == "population" and f.name == "correlations":
        return list[Correlation], field()
    if section == "graph" and f.name == "platforms":
        # Literal items put the enum on each array item (not on the array) in the JSON schema.
        platform: Any = Literal.__getitem__(tuple(engine_config.ALL_PLATFORMS))
        return list[platform], field(min_length=1)
    if section == "population" and f.name == "survey":
        from marketsim.survey import DATA

        options: Any = Literal.__getitem__(("", *sorted(p.stem for p in DATA.glob("*.json"))))
        return options, field()
    if section == "graph" and f.name == "youtube_lag_ticks":
        extra.update(minimum=lo, maximum=hi)
        return tuple[int, int], field()
    shape = _shape(default_json)
    if shape == "numlist":
        extra.update(minimum=lo, maximum=hi)
        item: Any = int if all(isinstance(x, int) for x in default_json) else float
        return tuple.__class_getitem__((item,) * len(default_json)), field()
    if shape == "json":
        # Nested shapes (e.g. marginals, platform_params) travel as plain JSON; the top-level
        # keys are checked here, and the engine validates the rest when it builds the population.
        extra["kind"] = "json"
        return (dict[str, Any] if isinstance(default_json, dict) else list[Any]), field()
    if isinstance(default_json, dict):
        extra.update(minimum=lo, maximum=hi, keys=list(default_json))
        sample = next(iter(default_json.values()))
        value_type: Any
        if isinstance(sample, list):
            value_type = tuple[float, float, float]
        elif isinstance(sample, int) and not isinstance(sample, bool):
            value_type = int
        else:
            value_type = float
        return dict[str, value_type], field()
    py_type: Any = type(default_json)
    if py_type is int:
        return int, field(ge=lo, le=hi)
    return float, field(ge=lo, le=hi)


def _validators(section: str, defaults: dict[str, Any]) -> dict[str, Any]:
    """Cross-field checks that cannot be expressed as simple bounds."""

    def check(values: Any) -> Any:  # an "after" validator: `values` is the model instance
        for name, default in defaults.items():
            v = getattr(values, name)
            key = f"{section}.{name}"
            rng = _range(key)
            if section == "graph" and name == "platforms":
                bad = set(v) - set(engine_config.ALL_PLATFORMS)
                if bad:
                    raise ValueError(f"graph.platforms: unknown platforms {sorted(bad)}")
                if len(set(v)) != len(v):
                    raise ValueError("graph.platforms: duplicates")
            elif section == "graph" and name == "youtube_lag_ticks":
                a, b = v
                if not (rng and rng[0] <= a <= b <= rng[1]):
                    raise ValueError(f"graph.youtube_lag_ticks: need {rng[0] if rng else 0} <= min <= max")
            elif _shape(default) == "numlist":
                if rng and not all(rng[0] <= x <= rng[1] for x in v):
                    raise ValueError(f"{key}: values must be in [{rng[0]}, {rng[1]}]")
            elif _shape(default) == "json" and not (section == "population" and name == "correlations"):
                if isinstance(default, dict) and set(v) != set(default):
                    raise ValueError(f"{key}: keys must be exactly {sorted(default)}")
            elif isinstance(default, dict):
                if set(v) != set(default):
                    raise ValueError(f"{key}: keys must be exactly {sorted(default)}")
                for k, item in v.items():
                    vals = item if isinstance(item, (list, tuple)) else [item]
                    if rng and not all(rng[0] <= x <= rng[1] for x in vals):
                        raise ValueError(f"{key}[{k}]: values must be in [{rng[0]}, {rng[1]}]")
                    if name == "strategy_prior" and abs(sum(vals) - 1.0) > 1e-6:
                        raise ValueError(f"{key}[{k}]: weights must sum to 1")
            elif section == "population" and name == "correlations":
                pairs = [frozenset((c.a, c.b)) for c in v]
                if any(len(p) < 2 for p in pairs):
                    raise ValueError("population.correlations: a trait cannot correlate with itself")
                if len(set(pairs)) != len(pairs):
                    raise ValueError("population.correlations: duplicate pairs")
        return values

    return {f"_check_{section}": model_validator(mode="after")(check)}


def _build_section_model(section: str, cls: type) -> type[BaseModel]:
    instance = cls()
    fields: dict[str, Any] = {}
    defaults: dict[str, Any] = {}
    for f in dataclasses.fields(instance):
        default_json = _to_json_value(section, f.name, getattr(instance, f.name))
        defaults[f.name] = default_json
        fields[f.name] = _field_spec(section, f, default_json)
    model = create_model(
        f"{section.capitalize()}Params",
        __config__=ConfigDict(extra="forbid", validate_default=True),
        __doc__=f"{section.capitalize()} parameters (generated from config.{cls.__name__}).",
        __validators__=_validators(section, defaults),
        **fields,
    )
    return model


SECTION_MODELS: dict[str, type[BaseModel]] = {s: _build_section_model(s, c) for s, c in SECTIONS.items()}

Parameters: type[BaseModel] = create_model(  # type: ignore[call-overload]
    "Parameters",
    __config__=ConfigDict(extra="forbid"),
    __doc__="All model parameters, one object per config section.",
    **{s: (m, Field(default_factory=m)) for s, m in SECTION_MODELS.items()},
)


# --------------------------------------------------------------------------- conversion


def default_parameters() -> BaseModel:
    return Parameters()


def parameters_to_engine(params: BaseModel, n_agents: int, seed: int) -> engine_config.Config:
    """Build the engine's `Config` from validated parameters plus the scenario's size and seed."""
    kwargs: dict[str, Any] = {}
    for section, cls in SECTIONS.items():
        default = cls()
        sec = getattr(params, section)
        values = {}
        for f in dataclasses.fields(default):
            v = getattr(sec, f.name)
            if isinstance(v, BaseModel):
                v = v.model_dump()
            elif isinstance(v, list) and v and isinstance(v[0], BaseModel):
                v = [x.model_dump() for x in v]
            values[f.name] = _to_engine_value(section, f.name, v, getattr(default, f.name))
        kwargs[section] = cls(**values)
    return engine_config.Config(n_agents=n_agents, seed=seed, **kwargs)


def engine_to_parameters(cfg: engine_config.Config) -> BaseModel:
    data = {
        section: {
            f.name: _to_json_value(section, f.name, getattr(getattr(cfg, section), f.name))
            for f in dataclasses.fields(getattr(cfg, section))
        }
        for section in SECTIONS
    }
    return Parameters.model_validate(data)


# --------------------------------------------------------------------------- UI schema


def ui_schema() -> list[dict[str, Any]]:
    """Field metadata for the Scenario Builder: one entry per section, in display order."""
    out = []
    defaults = default_parameters()
    for section, model in SECTION_MODELS.items():
        fields = []
        for name, finfo in model.model_fields.items():
            key = f"{section}.{name}"
            desc, placeholder = _meta(key)
            rng = _range(key)
            default = getattr(getattr(defaults, section), name)
            if isinstance(default, list) and default and isinstance(default[0], BaseModel):
                default = [x.model_dump() for x in default]
            fields.append(
                {
                    "name": name,
                    "key": key,
                    "kind": _kind(default, finfo.annotation),
                    "default": default,
                    "min": rng[0] if rng else None,
                    "max": rng[1] if rng else None,
                    "description": desc,
                    "placeholder": placeholder,
                }
            )
        out.append({"name": section, "fields": fields})
    return out


def _kind(default: Any, annotation: Any) -> str:
    if _shape(default) == "json":
        return "json"
    if isinstance(default, bool):
        return "bool"
    if isinstance(default, int):
        return "int"
    if isinstance(default, float):
        return "float"
    if isinstance(default, dict):
        return "map"
    if isinstance(default, list):
        return "list"
    return "other"
