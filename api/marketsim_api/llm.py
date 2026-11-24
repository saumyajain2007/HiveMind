"""Pluggable LLM providers for `POST /events/parse` (issue #18).

The engine never makes network calls (HANDOFF §0); the parser takes a callable. The API picks
that callable from `MARKETSIM_LLM_PROVIDER`:

* `none` (the default): no network. The endpoint returns the prompts so a person can paste them
  into any LLM, then post the replies back as `responses`.
* `anthropic`: calls the Claude Messages API through the official `anthropic` SDK
  (`uv sync --extra llm`). Needs an Anthropic credential in the environment
  (`ANTHROPIC_API_KEY`, or an `ant auth login` profile). Model: `MARKETSIM_LLM_MODEL`
  (default `claude-opus-5-5`); effort: `MARKETSIM_LLM_EFFORT` (default `low`, enough for a short
  extraction). Current Claude models do not take a temperature, so repeatability comes from the
  parser's response cache (`MARKETSIM_LLM_CACHE`, default `<data dir>/llm_cache.json`).
  Server-side refusal fallbacks are on (`fallbacks: "default"`).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import cast

LLM = Callable[[str], str]
DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ProviderError(RuntimeError):
    pass


def provider_name() -> str:
    return os.environ.get("MARKETSIM_LLM_PROVIDER", "none").strip().lower() or "none"


def cache_path(data_dir: Path) -> Path:
    return Path(os.environ.get("MARKETSIM_LLM_CACHE", str(Path(data_dir) / "llm_cache.json")))


def anthropic_llm(model: str | None = None, effort: str | None = None) -> LLM:
    try:
        import anthropic
        from anthropic.types.beta import BetaMessageParam, BetaOutputConfigParam
    except ImportError as e:  # pragma: no cover - depends on the optional extra
        raise ProviderError("the 'anthropic' package is not installed: uv sync --extra llm") from e

    client = anthropic.Anthropic()
    model_id: str = model or os.environ.get("MARKETSIM_LLM_MODEL", DEFAULT_MODEL)
    effort = effort or os.environ.get("MARKETSIM_LLM_EFFORT", "low")

    output_config = cast("BetaOutputConfigParam", {"effort": effort})

    def call(prompt: str) -> str:
        messages: list[BetaMessageParam] = [{"role": "user", "content": prompt}]
        try:
            response = client.beta.messages.create(
                model=model_id,
                max_tokens=16_000,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                output_config=output_config,
                messages=messages,
            )
        except anthropic.RateLimitError as e:
            raise ProviderError(f"rate limited by the Claude API: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Claude API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("could not reach the Claude API") from e
        if response.stop_reason == "refusal":
            raise ProviderError("the model declined to parse this headline")
        return "".join(block.text for block in response.content if block.type == "text")

    return call


def get_llm() -> LLM | None:
    """The configured provider's callable, or None for the manual (`none`) flow."""
    name = provider_name()
    if name == "none":
        return None
    if name == "anthropic":
        return anthropic_llm()
    raise ProviderError(f"unknown MARKETSIM_LLM_PROVIDER {name!r}; expected 'none' or 'anthropic'")
