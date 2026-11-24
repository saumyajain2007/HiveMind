"""The optional Claude provider builds the right request (no network: the client is faked)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic
import pytest

from marketsim_api import llm


class FakeMessages:
    def __init__(self, reply: Any) -> None:
        self.reply, self.calls = reply, []

    def create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        return self.reply


def fake_client(monkeypatch: pytest.MonkeyPatch, reply: Any) -> FakeMessages:
    msgs = FakeMessages(reply)
    monkeypatch.setattr(anthropic, "Anthropic", lambda: SimpleNamespace(beta=SimpleNamespace(messages=msgs)))
    return msgs


def test_request_shape_and_text(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = SimpleNamespace(
        stop_reason="end_turn",
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text='{"a": 1}'),
        ],
    )
    msgs = fake_client(monkeypatch, reply)
    monkeypatch.delenv("MARKETSIM_LLM_MODEL", raising=False)
    assert llm.anthropic_llm()("parse this") == '{"a": 1}'
    kw = msgs.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["output_config"] == {"effort": "low"}
    assert kw["messages"] == [{"role": "user", "content": "parse this"}]
    assert "temperature" not in kw  # current Claude models reject sampling parameters


def test_refusal_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client(monkeypatch, SimpleNamespace(stop_reason="refusal", content=[]))
    with pytest.raises(llm.ProviderError, match="declined"):
        llm.anthropic_llm()("x")


def test_provider_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARKETSIM_LLM_PROVIDER", raising=False)
    assert llm.get_llm() is None  # off by default: no network
    monkeypatch.setenv("MARKETSIM_LLM_PROVIDER", "other")
    with pytest.raises(llm.ProviderError):
        llm.get_llm()
