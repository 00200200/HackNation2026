import pytest
from pydantic_ai import models

# Tests never reach a real model; each one overrides the agent with a FunctionModel.
models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture(autouse=True)
def offline_sources(monkeypatch):
    """No test reaches the web, Tavily, Google or a database: search fails fast unless a test fakes it."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_FACTCHECK_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("EUVSDISINFO_API_KEY", raising=False)
