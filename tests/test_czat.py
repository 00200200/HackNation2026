"""The /czat demo adapter (#116) answers like the Discord bot, through the same API.

The page is static JavaScript, so these tests read its files: the notices and section names in
frontend/public/czat.js must stay word for word the bot's (prawdowid/discord_bot.py), and the first
words of each answer the web page's (frontend/public/app.js). The API side is in test_app.py.
"""

import re
from pathlib import Path

import pytest

from prawdowid import app, discord_bot

ROOT = Path(__file__).parent.parent
PUBLIC = ROOT / "frontend" / "public"
CZAT_JS = (PUBLIC / "czat.js").read_text(encoding="utf-8")
BOT_SOURCE = (ROOT / "prawdowid" / "discord_bot.py").read_text(encoding="utf-8")
LABEL = (
    "Adapter demonstracyjny kanału komunikatora (np. WhatsApp, Messenger): ta sama logika "
    "sprawdzania co strona; prawdziwy komunikator podłącza się do tego samego API"
)


@pytest.mark.parametrize(
    "text",
    [
        discord_bot.SECURITY_NOTE,
        discord_bot.SECURITY_NOTE_ONLY,
        discord_bot.SOURCE_SECURITY_NOTE,
        discord_bot.PAGE_NOTE,
        discord_bot.UNCHECKED_NOTE,
        discord_bot.INCIDENT_NOTE,
        discord_bot.CONNECTION_ERROR,
        app.TECHNICAL_ERROR_MESSAGE,
        *discord_bot.KIND_LABELS.values(),
        *discord_bot.MATCH_LABELS.values(),
    ],
)
def test_notices_are_the_bots_word_for_word(text):
    assert f'"{text}"' in CZAT_JS


@pytest.mark.parametrize(
    "name",
    [
        "Brak oceny.",
        "Polecenia dla modelu.",
        "Brak twierdzeń.",
        "Usługa nie zwróciła żadnego twierdzenia.",
        "Sprawdzony tekst pochodzi ze strony: ",
        "Podobne znane incydenty",
        "Niesprawdzone twierdzenia",
        "W tekście: ",
        "Bez oceny",
        "Ocena",
        "Uzasadnienie:",
        "Siła dowodów:",
        "Przesłanki",
        "Źródła",
        "Ograniczenia",
        "brak",
    ],
)
def test_sections_carry_the_bots_names(name):
    assert name in BOT_SOURCE and name in CZAT_JS


def test_first_words_of_an_answer_match_the_web_page():
    def leads(js: str) -> dict[str, str]:
        block = re.search(r"const ANSWER_LEAD = \{(.*?)\};", js, re.DOTALL).group(1)
        return dict(re.findall(r'(\w+): "([^"]*)"', block))

    web = leads((PUBLIC / "app.js").read_text(encoding="utf-8"))
    assert len(web) == 6 and leads(CZAT_JS) == web


def test_page_calls_the_api_as_the_demo_channel():
    assert re.search(r'const CHANNEL = "demo";', CZAT_JS)
    assert "demo" in app.CHANNELS
    assert f"const MAX_CHARS = {app.MAX_INPUT_CHARS};" in CZAT_JS
    assert '"X-Channel": CHANNEL' in CZAT_JS and '"X-Session-Id"' in CZAT_JS


def test_page_says_it_is_a_demo_adapter_and_the_web_page_links_to_it():
    html = (PUBLIC / "czat.html").read_text(encoding="utf-8")
    text = " ".join(re.sub(r"<[^>]+>", "", html).split())
    assert LABEL in text
    assert 'href="/czat"' in (PUBLIC / "index.html").read_text(encoding="utf-8")


def test_nginx_serves_the_page_without_its_extension():
    conf = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    assert re.search(r"try_files \$uri \$uri\.html ", conf)


def test_sources_show_the_fact_checkers_rating_and_the_search_snippet_label():
    assert "s.rating" in CZAT_JS and "Ocena fact-checkera: " in CZAT_JS
    assert "s.snippet_only" in CZAT_JS and "fragment z wyników wyszukiwarki" in CZAT_JS


def test_no_check_starts_while_a_session_deletion_runs():
    assert CZAT_JS.count("if (busy || deleting) return;") == 2
