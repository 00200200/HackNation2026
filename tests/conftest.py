import pytest
from pydantic_ai import models

from prawdowid import websearch

# Tests never reach a real model; each one overrides the agent with a FunctionModel.
models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture(autouse=True)
def offline_sources(monkeypatch):
    """No test reaches the web or Google: search fails fast unless a test fakes it."""

    async def no_search(query, **kwargs):
        return websearch.WebSearch(limitation=websearch.SEARCH_UNAVAILABLE)

    monkeypatch.setattr(websearch, "search_web", no_search)
    monkeypatch.delenv("GOOGLE_FACTCHECK_API_KEY", raising=False)
