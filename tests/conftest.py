import pytest
from pydantic_ai import models

# Tests never reach a real model; each one overrides the agent with a FunctionModel.
models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture(autouse=True)
def offline_sources(monkeypatch):
    """No test reaches the web, Perplexity, Tavily, OpenAI, Google or a database: search fails fast unless a test fakes it."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
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


@pytest.fixture(autouse=True)
def moderation_db(monkeypatch, tmp_path):
    """Every test keeps moderator cases in a temporary database, never in the repo."""
    from prawdowid import moderation

    path = tmp_path / "moderation.sqlite3"
    monkeypatch.setattr(moderation, "DB", path)
    return path
