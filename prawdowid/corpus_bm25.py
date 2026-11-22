"""Step 2 lookup in the evidence corpus (`corpus/evidence.jsonl`, docs/corpus.md): BM25 in memory.

Every check searches the corpus next to Fact Check, EUvsDisinfo, the www.gov.pl site search and web
search. Each document is cut into passages of at most `PASSAGE_CHARS` characters and the passages are
indexed once (about a second) with BM25 (`bm25s`, numpy only): the API builds the index at startup
(`app.lifespan`), anything else on its first lookup. No database, no embedding model and no
network, so it runs on the server and on a juror's laptop alike.

Polish gets the minimum: words are lowercased, stripped of diacritics, cut to their first
`STEM_CHARS` letters (a crude stemmer: "Włochy" meets "Włoch", "strajku" meets "strajków") and
stopwords are dropped. Each query is ranked on its own and the rankings are merged with reciprocal
rank fusion; a document keeps at most `PER_DOC` passages and a lookup returns at most `MAX_DOCS`
documents. A hit is a `Source` whose `fragment` is a verbatim part of the document (its best
passages joined by a blank line), so a quote taken from it passes the judge's check. A file that is
missing, unreadable or holds no usable record is a limitation, never evidence of anything.

Try it: uv run python -m prawdowid.corpus_bm25 "czy MSZ odradza podróże do Izraela"
"""

import asyncio
import json
import logging
import re
import sys
import threading
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import bm25s
import numpy as np
from pydantic import BaseModel

from prawdowid import factcheck
from prawdowid.contract import Source

log = logging.getLogger("prawdowid")

CORPUS_PATH = Path(__file__).resolve().parent.parent / "corpus" / "evidence.jsonl"
# Close to the 800-character fragments rerank cuts pages into, so a passage is one fragment.
PASSAGE_CHARS = 800
STEM_CHARS = 5
# A title that names the subject ("Izrael – informacje dla podróżujących") tells more than one more
# mention in the body: its BM25 score is added, with this weight, to every passage of the document.
TITLE_WEIGHT = 1.0
# BM25 ranks something for any word that occurs anywhere ("szczepionki" finds "szczególnie"): a
# passage counts only when it, or the title of its document, holds a word of the query that is rare
# there (an entity, a specific noun): found in at most this share of the passages or of the titles,
# or in at most RARE_FLOOR of them, so a small corpus (a juror's own, a test) still answers.
RARE_SHARE = 0.035
RARE_FLOOR = 3
MAX_TERMS = 32  # distinct words used from one query
POOL = 30  # passages taken from each query's ranking before the rankings are merged
RRF_K = 60  # the usual constant of reciprocal rank fusion
PER_DOC = 2
MAX_DOCS = 5
# The corpus says "fact_checker"; the judge knows a fact-checker's source as `fact_check`.
SOURCE_TYPES = {"fact_checker": factcheck.SOURCE_TYPE}

CORPUS_UNAVAILABLE = (
    "Korpus źródeł urzędowych i weryfikatorów był niedostępny, "
    "więc nie sprawdziliśmy dokumentów z tego zbioru."
)

_COMBINING = re.compile(r"[̀-ͯ]")
# Words of 3+ letters only: shorter ones are function words and would only add noise.
_WORD = re.compile(r"\w{3,}")


def fold(text: str) -> str:
    """Lowercase, no diacritics: "Łódź" -> "lodz". NFKD does not split "ł", so it is replaced."""
    folded = unicodedata.normalize("NFKD", text.casefold())
    return _COMBINING.sub("", folded).replace("ł", "l")


# Words that sit in nearly every Polish text (and a few English ones: some pages are in English).
STOPWORDS = frozenset(
    _WORD.findall(
        fold(
            """
    czy nie jest są był była było były byli być będzie będą oraz dla jak ten tak tym tych tego
    temu jako także również tylko ale już też jego jej ich lub albo ponieważ może można należy
    gdzie kiedy gdy jaki jaka jakie który która które których którym którego której przez przed
    przy nad pod bez aby żeby więc jednak jeśli jeżeli bardzo więcej został została zostało
    zostały zostać the and for that this with from are was http https www
    """
        )
    )
)


def terms(text: str) -> list[str]:
    """The searchable words of `text`: folded, without stopwords, cut to their stem."""
    return [w[:STEM_CHARS] for w in _WORD.findall(fold(text)) if w not in STOPWORDS]


def passages(text: str, limit: int = PASSAGE_CHARS) -> list[str]:
    """Consecutive pieces of at most `limit` characters, cut at line breaks, else at spaces.
    Each piece is a verbatim part of `text`. Same cut as `prawdowid.index.chunk_text`, which
    cannot be imported here: it pulls in numpy, psycopg and the embedding model."""
    pieces: list[str] = []
    for line in text.split("\n"):
        while len(line) > limit:
            cut = line.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            pieces.append(line[:cut])
            line = line[cut:].lstrip(" ")
        pieces.append(line)
    chunks: list[str] = []
    for piece in pieces:
        if chunks and len(chunks[-1]) + 1 + len(piece) <= limit:
            chunks[-1] += "\n" + piece
        else:
            chunks.append(piece)
    return [c.strip("\n") for c in chunks if c.strip()]


class EvidenceHit(BaseModel):
    source: Source  # `fragment` holds the best passages of the document, verbatim
    score: float  # reciprocal rank fusion of the document's best passage


class EvidenceLookup(BaseModel):
    hits: list[EvidenceHit] = []
    # Set when the corpus could not be searched; goes to ClaimResult.limitations.
    limitation: str | None = None


@dataclass(frozen=True)
class _Index:
    sources: list[Source]  # one per document, without a fragment
    reviews: dict[int, str]  # document -> fragment, for a fact-checker's review
    texts: list[str]  # the passages
    owner: np.ndarray  # document of each passage
    body: bm25s.BM25  # over the passages
    titles: (
        bm25s.BM25 | None
    )  # over the titles, one entry per document; None: no title has a word
    rare_in_body: frozenset[str]  # words found in few passages
    rare_in_title: frozenset[str]  # words found in few titles

    def search(self, queries: list[str]) -> list[EvidenceHit]:
        fused: dict[int, float] = {}
        for query in queries:
            for rank, passage in enumerate(self._rank(query)):
                fused[passage] = fused.get(passage, 0.0) + 1 / (RRF_K + rank + 1)
        best: dict[int, list[int]] = {}  # document -> its best passages
        for passage in sorted(fused, key=lambda p: (-fused[p], p)):
            doc = int(self.owner[passage])
            if doc not in best and len(best) == MAX_DOCS:
                continue
            if len(best.setdefault(doc, [])) < PER_DOC:
                best[doc].append(passage)
        return [self._hit(doc, ps, fused[ps[0]]) for doc, ps in best.items()]

    def _rank(self, query: str) -> list[int]:
        """Passages that match a rare word of the query, best first."""
        words = list(dict.fromkeys(terms(query)))[:MAX_TERMS]
        scores = np.zeros(self.owner.size, dtype=np.float32)
        anchored = np.zeros(self.owner.size, dtype=bool)
        for word in words:
            in_body = self.body.get_scores([word])
            in_title = 0.0
            if self.titles is not None:
                in_title = self.titles.get_scores([word])[self.owner]
            scores += in_body + TITLE_WEIGHT * in_title
            if word in self.rare_in_body:
                anchored |= in_body > 0
            if word in self.rare_in_title:
                anchored |= in_title > 0
        scores[~anchored] = 0
        k = min(POOL, scores.size)
        top = np.argpartition(scores, -k)[-k:]
        top = top[np.lexsort((top, -scores[top]))]  # ties: the earlier passage first
        return [int(i) for i in top if scores[i] > 0]

    def _hit(self, doc: int, passages_: list[int], score: float) -> EvidenceHit:
        # Reading order, not rank order.
        fragment = self.reviews.get(doc) or "\n\n".join(
            self.texts[p] for p in sorted(passages_)
        )
        source = self.sources[doc].model_copy(update={"fragment": fragment})
        return EvidenceHit(source=source, score=score)


def _source(record: dict) -> Source | None:
    """The record as a `Source` without a fragment; None when a field is missing or invalid."""
    try:
        published = record.get("published_at")
        return Source(
            title=record["title"],
            publisher=record["publisher"],
            published_at=date.fromisoformat(published[:10]) if published else None,
            fetched_at=datetime.fromisoformat(record["retrieved_at"]),
            url=record["url"],
            source_type=SOURCE_TYPES.get(record["source_type"], record["source_type"]),
        )
    except (
        KeyError,
        TypeError,
        ValueError,
    ):  # pydantic's ValidationError is a ValueError
        return None


def _parse(line: bytes) -> dict | None:
    """A line of the file as a record; None when it is no JSON object (or no UTF-8)."""
    try:
        record = json.loads(line)
    except ValueError:  # invalid JSON or UTF-8
        return None
    return record if isinstance(record, dict) else None


def _review(record: dict) -> str | None:
    """A fact-checker's rating in the form the judge reads: never the reviewed claim alone.
    A field of another type is no rating or claim; one odd record must not fail the build."""
    rating, claim = record.get("rating"), record.get("claim")
    if not isinstance(rating, str):
        return None
    return factcheck.review_fragment(rating, claim if isinstance(claim, str) else None)


def _build(path: Path) -> _Index | None:
    try:
        # Bytes, split at "\n" only: a stray U+2028 inside a JSON string is no line break.
        lines = [line for line in path.read_bytes().splitlines() if line.strip()]
    except OSError as exc:
        log.warning("corpus unreadable path=%s error=%s", path, type(exc).__name__)
        return None
    sources: list[Source] = []
    reviews: dict[int, str] = {}
    texts: list[str] = []
    owner: list[int] = []
    body_terms: list[list[str]] = []
    title_terms: list[list[str]] = []
    skipped = 0
    for line in lines:
        record = _parse(line)
        source = _source(record) if record else None
        text = record.get("text") if source else None
        if not isinstance(text, str):
            skipped += 1
            continue
        doc = len(sources)
        sources.append(source)
        title_terms.append(terms(source.title))
        if review := _review(record):
            reviews[doc] = review
        for passage in passages(text):
            if words := terms(passage):  # a passage of stopwords only can never match
                texts.append(passage)
                owner.append(doc)
                body_terms.append(words)
    if skipped:
        log.warning("corpus records skipped: %d of %d unusable", skipped, len(lines))
    if not texts:
        log.warning("corpus has no usable record path=%s", path)
        return None
    body = bm25s.BM25()
    body.index(body_terms, show_progress=False)
    titles = None  # bm25s cannot index titles that hold no word at all
    if any(title_terms):
        titles = bm25s.BM25()
        titles.index(title_terms, show_progress=False)
    return _Index(
        sources,
        reviews,
        texts,
        np.array(owner),
        body,
        titles,
        _rare(body_terms),
        _rare(title_terms),
    )


def _rare(entries: list[list[str]]) -> frozenset[str]:
    """Words found in at most `RARE_SHARE` of the entries (`RARE_FLOOR` entries at the least)."""
    found = Counter(w for words in entries for w in set(words))
    limit = max(RARE_FLOOR, RARE_SHARE * len(entries))
    return frozenset(w for w, n in found.items() if n <= limit)


_lock = threading.Lock()
# Successful builds only: after a failure (file missing, unreadable) the next lookup tries again.
_indexes: dict[Path, _Index] = {}


def _index(path: Path) -> _Index | None:
    """The index of the corpus file. The first lookup builds it; concurrent ones wait for that
    one build instead of making their own."""
    with _lock:
        if path not in _indexes:
            started = time.perf_counter()
            if index := _build(path):
                _indexes[path] = index
                log.info(
                    "corpus indexed documents=%d passages=%d ms=%d",
                    len(index.sources),
                    len(index.texts),
                    (time.perf_counter() - started) * 1000,
                )
        return _indexes.get(path)


def _search(queries: list[str]) -> EvidenceLookup:
    index = _index(CORPUS_PATH)
    if index is None:
        return EvidenceLookup(limitation=CORPUS_UNAVAILABLE)
    return EvidenceLookup(hits=index.search(queries))


async def search_evidence(queries: list[str]) -> EvidenceLookup:
    """The corpus passages that best answer any of `queries`. Runs in a worker thread, so the event
    loop is not blocked while the first call builds the index. A thread cannot be cancelled: a
    caller that gives up (the pipeline's budget) leaves the build to finish in the background."""
    return await asyncio.to_thread(_search, queries)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    started = time.perf_counter()
    found = asyncio.run(search_evidence([" ".join(sys.argv[1:])]))
    print(f"{(time.perf_counter() - started) * 1000:.0f} ms (index built in this call)")
    for hit in found.hits:
        s = hit.source
        print(f"{hit.score:.4f}  {s.published_at}  {s.publisher} | {s.title[:80]}")
        print(f"        {s.url}  [{s.source_type}]")
        print(f"        {s.fragment[:220]!r}")
    if found.limitation:
        print(found.limitation)
