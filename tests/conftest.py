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
    # gov.pl needs no key: off unless a test turns it on with a fake transport or search.
    from prawdowid import govpl

    monkeypatch.setattr(govpl, "ENABLED", False)


@pytest.fixture(autouse=True)
def check_log(monkeypatch, tmp_path):
    """Every test writes its check log to a temporary file, never to the repo."""
    from prawdowid import checklog

    path = tmp_path / "checks.jsonl"
    monkeypatch.setattr(checklog, "CHECK_LOG", path)
    monkeypatch.setattr(checklog, "DELETED", {})
    return path


@pytest.fixture
def quiet_sources(monkeypatch):
    """Every source answers and finds nothing (no outage): a check ends in a verdict, not a
    technical error, without any network."""
    from prawdowid import euvsdisinfo, factcheck, websearch

    def empty(model):
        async def search(*args, **kwargs):
            return model()

        return search

    monkeypatch.setattr(factcheck, "search_claims", empty(factcheck.FactCheckLookup))
    monkeypatch.setattr(
        euvsdisinfo, "search_cases", empty(euvsdisinfo.EuvsdisinfoLookup)
    )
    monkeypatch.setattr(websearch, "search_web", empty(websearch.WebSearch))
