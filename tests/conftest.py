import pytest
from ddgs.exceptions import DDGSException
from pydantic_ai import models

from prawdowid import websearch

# Tests never reach a real model; each one overrides the agent with a FunctionModel.
models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture(autouse=True)
def offline_sources(monkeypatch):
    """No test reaches the web, Google or a database: search fails fast unless a test fakes it."""

    class OfflineDDGS:
        def __init__(self, **kwargs):
            pass

        def text(self, *args, **kwargs):
            raise DDGSException("offline test")

    monkeypatch.setattr(websearch, "DDGS", OfflineDDGS)
    monkeypatch.delenv("GOOGLE_FACTCHECK_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("EUVSDISINFO_API_KEY", raising=False)
