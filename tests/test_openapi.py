"""docs/openapi.json is the integration point for new channels (README, "API")."""

import base64
import hashlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from prawdowid.app import CheckRequest, app
from prawdowid.contract import Source, SourceStance

ROOT = Path(__file__).parent.parent
SPEC_FILE = ROOT / "docs" / "openapi.json"
NGINX_CONF = ROOT / "frontend" / "nginx.conf"


def test_committed_spec_matches_the_app():
    committed = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    assert committed == app.openapi(), "docs/openapi.json is stale: run `make openapi`"


def test_spec_and_docs_are_served_under_api():
    client = TestClient(app)
    assert client.get("/api/openapi.json").json() == app.openapi()
    page = client.get("/api/docs")
    assert page.status_code == 200 and "/api/openapi.json" in page.text
    # Nothing else is added: the default root paths, ReDoc and the OAuth2 redirect stay off.
    for path in ("/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"):
        assert client.get(path).status_code == 404


def test_docs_page_policy_names_the_hash_of_its_inline_script():
    """nginx lets /api/docs run FastAPI's inline script by its hash, not by 'unsafe-inline'.

    A FastAPI upgrade or a docs setting that changes the script must fail here and not
    leave the public docs page blank.
    """
    html = TestClient(app).get("/api/docs").text
    script = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.DOTALL)
    inline = script.findall(html)
    hashes = {
        f"'sha256-{base64.b64encode(hashlib.sha256(s.encode()).digest()).decode()}'"
        for s in inline
    }
    conf = NGINX_CONF.read_text(encoding="utf-8")
    policy = re.search(r'/api/docs "(.*?)";', conf).group(1)
    assert hashes and hashes == set(re.findall(r"'sha256-[^']+'", policy))
    assert "'unsafe-inline'" not in policy


def test_checks_operation_documents_what_a_channel_needs():
    post = app.openapi()["paths"]["/api/checks"]["post"]
    headers = {p["name"] for p in post["parameters"] if p["in"] == "header"}
    assert headers == {"X-Channel", "X-Session-Id"}
    ok = post["responses"]["200"]
    assert "X-Session-Id" in ok["headers"]
    assert ok["content"]["application/json"]["schema"]["$ref"].endswith("/CheckResult")
    assert "429" in post["responses"]


def test_request_example_is_valid_input():
    [example] = CheckRequest.model_json_schema()["examples"]
    assert CheckRequest(**example).input == example["input"]


def test_a_source_stands_on_one_of_three_sides_or_none():
    """#78: the evidence chain. A channel groups sources by `stance`; null means the verdict
    rules did not count the source."""
    schemas = app.openapi()["components"]["schemas"]
    assert schemas["SourceStance"]["enum"] == ["potwierdza", "przeczy", "kontekst"]
    assert [s.value for s in SourceStance] == schemas["SourceStance"]["enum"]
    stance = schemas["Source"]["properties"]["stance"]
    assert stance["anyOf"] == [
        {"$ref": "#/components/schemas/SourceStance"},
        {"type": "null"},
    ]
    assert "stance" not in schemas["Source"]["required"]


def test_a_source_without_a_stance_stays_valid_and_no_other_side_is():
    """An answer from before the evidence chain (a cached one, say) still validates."""
    old = {
        "title": "Polska w UE",
        "publisher": "gov.pl",
        "published_at": "2024-05-01",
        "fetched_at": "2026-11-21T00:00:00Z",
        "url": "https://www.gov.pl/web/ue",
        "source_type": "official",
    }
    assert Source.model_validate(old).stance is None
    assert (
        Source.model_validate({**old, "stance": "przeczy"}).stance
        is SourceStance.REFUTES
    )
    with pytest.raises(ValidationError):
        Source.model_validate({**old, "stance": "supports"})
