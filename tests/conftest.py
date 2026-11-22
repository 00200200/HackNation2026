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
def empty_corpus(monkeypatch):
    """The evidence corpus finds nothing and no test builds its index, unless it fakes the lookup."""
    from prawdowid import corpus_bm25

    async def nothing(queries):
        return corpus_bm25.EvidenceLookup()

    monkeypatch.setattr(corpus_bm25, "search_evidence", nothing)


@pytest.fixture(autouse=True)
def check_log(monkeypatch, tmp_path):
    """Every test writes its check log to a temporary file, never to the repo."""
    from prawdowid import checklog

    path = tmp_path / "checks.jsonl"
    monkeypatch.setattr(checklog, "CHECK_LOG", path)
    monkeypatch.setattr(checklog, "DELETED", {})
    return path


@pytest.fixture(autouse=True)
def empty_result_cache():
    """The API's result cache is module state: no answer may leak from one test into another."""
    from prawdowid import app

    app._results.clear()
