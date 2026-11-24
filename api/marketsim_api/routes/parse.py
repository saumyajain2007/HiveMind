"""`POST /events/parse`: headlines -> scenario events with a pluggable LLM (issue #18).

With no provider configured (the default), the first call returns the prompts; paste each into
any LLM and post the replies back as `responses` to get validated events. With
`MARKETSIM_LLM_PROVIDER=anthropic` the API calls Claude itself (see `marketsim_api.llm`).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from marketsim.event_parser import EventParseError, Headline, build_prompt, parse_headlines

from ..llm import LLM, ProviderError, cache_path, get_llm, provider_name
from ..schemas import EventSpec, ParseRequest, ParseResponse

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/parse", response_model=ParseResponse)
def parse(body: ParseRequest, request: Request) -> ParseResponse:
    texts = [h.text for h in body.headlines]
    prompts = [build_prompt(t, texts[:i]) for i, t in enumerate(texts)]
    if body.responses is not None:
        if len(body.responses) != len(body.headlines):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "give exactly one response per headline"
            )
        replies = dict(zip(prompts, body.responses, strict=True))
        llm: LLM = replies.__getitem__
        provider, cache = "manual", None
    else:
        try:
            configured = get_llm()
        except ProviderError as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None
        if configured is None:
            return ParseResponse(provider="none", prompts=prompts)
        llm, provider = configured, provider_name()
        cache = cache_path(request.app.state.settings.data_dir)
    headlines = [Headline(h.text, h.tick) for h in body.headlines]
    errors: list[str] = []
    try:
        events = parse_headlines(
            headlines, llm, cache, first_id=body.first_id, ticker=body.ticker, on_error="skip"
        )
    except ProviderError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    except EventParseError as e:  # pragma: no cover - on_error="skip" collects these
        errors.append(str(e))
        events = []
    parsed_ids = {e.id for e in events}
    expected = set(range(body.first_id, body.first_id + len(texts)))
    for missing in sorted(expected - parsed_ids):
        errors.append(
            f"headline {missing - body.first_id} could not be parsed: {texts[missing - body.first_id]!r}"
        )
    out = [
        EventSpec(
            id=e.id,
            tick=e.tick,
            kind=e.kind,
            ticker=e.ticker,
            true_impact=max(-0.5, min(0.5, e.true_impact)),
            sentiment=e.sentiment,
            credibility=e.credibility,
            salience=e.salience,
            complexity=e.complexity,
            seeding=e.seeding,
            parent=e.parent,
            topic=e.topic,
            label=texts[e.id - body.first_id][:200],
        )
        for e in events
    ]
    return ParseResponse(
        provider=provider, prompts=prompts if provider == "manual" else [], events=out, errors=errors
    )
