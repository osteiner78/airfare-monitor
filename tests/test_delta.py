import pytest
from backend.pages import _enrich_summaries


@pytest.mark.asyncio
async def test_delta_new_when_no_previous_snapshot():
    summaries = [{
        "id": 1,
        "best_price": 100.0,
        "previous_best_price": None,
        "currency": "EUR",
    }]
    result = _enrich_summaries(summaries)
    assert result[0]["price_delta"] is None


@pytest.mark.asyncio
async def test_delta_down_when_price_decreased():
    summaries = [{
        "id": 1,
        "best_price": 80.0,
        "previous_best_price": 100.0,
        "currency": "EUR",
    }]
    result = _enrich_summaries(summaries)
    assert result[0]["price_delta"]["type"] == "down"
    assert result[0]["price_delta"]["amount"] == 20.0


@pytest.mark.asyncio
async def test_delta_up_when_price_increased():
    summaries = [{
        "id": 1,
        "best_price": 120.0,
        "previous_best_price": 100.0,
        "currency": "EUR",
    }]
    result = _enrich_summaries(summaries)
    assert result[0]["price_delta"]["type"] == "up"
    assert result[0]["price_delta"]["amount"] == 20.0


@pytest.mark.asyncio
async def test_delta_same_when_prices_equal():
    summaries = [{
        "id": 1,
        "best_price": 100.0,
        "previous_best_price": 100.0,
        "currency": "EUR",
    }]
    result = _enrich_summaries(summaries)
    assert result[0]["price_delta"]["type"] == "same"


@pytest.mark.asyncio
async def test_delta_none_when_best_price_is_none():
    summaries = [{
        "id": 1,
        "best_price": None,
        "previous_best_price": 100.0,
        "currency": "EUR",
    }]
    result = _enrich_summaries(summaries)
    assert result[0]["price_delta"] is None


@pytest.mark.asyncio
async def test_delta_none_when_both_are_none():
    summaries = [{
        "id": 1,
        "best_price": None,
        "previous_best_price": None,
        "currency": "EUR",
    }]
    result = _enrich_summaries(summaries)
    assert result[0]["price_delta"] is None
