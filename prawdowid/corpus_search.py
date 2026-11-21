"""Search in the evidence corpus (`corpus/evidence.jsonl`, loaded by `prawdowid.index`).

Hybrid: the nearest chunks by embedding (pgvector) and the best full-text matches are merged
with reciprocal rank fusion, at most two chunks per document. Each hit is a `Source` whose
`fragment` is a verbatim part of the stored document, so a quote taken from it can be checked.
A missing database, a timeout or an error is a limitation, never evidence of anything.

Try it: DATABASE_URL=... uv run python -m prawdowid.corpus_search "czy strajk we Włoszech"
"""

import asyncio
import logging
import os
import re
import sys

import psycopg
from pgvector.psycopg import register_vector_async
from pydantic import BaseModel

from prawdowid import embeddings
from prawdowid.contract import Source

log = logging.getLogger("prawdowid")

DEADLINE_S = 10
POOL = 40  # candidates taken from each of the two rankings before they are merged
RRF_K = 60  # the usual constant of reciprocal rank fusion
PER_DOC = 2
MAX_TERMS = 12
# Words that match half the corpus and only blur the full-text ranking.
STOPWORDS = frozenset(
    [
        "czy",
        "się",
        "nie",
        "jest",
        "są",
        "był",
        "była",
        "było",
        "być",
        "oraz",
        "dla",
        "jak",
        "ten",
        "tak",
        "tym",
        "przez",
        "który",
        "która",
        "które",
        "tylko",
        "ale",
        "już",
        "tego",
        "też",
        "jego",
        "jej",
        "ich",
        "lub",
        "albo",
        "ponieważ",
        "może",
        "można",
        "gdzie",
        "kiedy",
        "jaki",
        "jaka",
        "jakie",
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
    ]
)

INDEX_INCOMPLETE = "Indeks korpusu był w trakcie przebudowy, więc wyniki z tego zbioru mogą być niepełne."
SEARCH_UNAVAILABLE = (
    "Wyszukiwanie w korpusie źródeł urzędowych i weryfikatorów było niedostępne, "
    "więc nie sprawdziliśmy dokumentów z tego zbioru."
)

SQL = """
WITH semantic AS (  -- ranks only the candidates, so the HNSW index serves the inner query
    SELECT doc_id, ord, row_number() OVER (ORDER BY distance) AS rank
    FROM (
        SELECT doc_id, ord, embedding <=> %(vector)s AS distance
        FROM corpus_chunks ORDER BY embedding <=> %(vector)s LIMIT %(pool)s
    ) AS nearest
), lexical AS (
    SELECT doc_id, ord, row_number() OVER (ORDER BY relevance DESC) AS rank
    FROM (
        SELECT doc_id, ord, ts_rank_cd(tsv, q) AS relevance
        FROM corpus_chunks, to_tsquery('simple', %(terms)s) AS q
        WHERE tsv @@ q ORDER BY relevance DESC LIMIT %(pool)s
    ) AS matching
), fused AS (
    SELECT doc_id, ord, sum(1.0 / (%(rrf_k)s + rank)) AS score
    FROM (SELECT * FROM semantic UNION ALL SELECT * FROM lexical) AS both_rankings
    GROUP BY doc_id, ord
), ranked AS (
    SELECT *, row_number() OVER (PARTITION BY doc_id ORDER BY score DESC) AS nth FROM fused
)
SELECT d.title, d.publisher, d.published_at, d.retrieved_at, d.url, d.source_type,
       d.rating, d.claim, c.text, r.score
FROM ranked AS r
JOIN corpus_chunks AS c USING (doc_id, ord)
JOIN corpus_documents AS d ON d.id = r.doc_id
WHERE r.nth <= %(per_doc)s
ORDER BY r.score DESC
LIMIT %(k)s
"""


class CorpusHit(BaseModel):
    source: Source  # `fragment` holds the matching chunk, verbatim
    score: float
    # For fact-checks: the fact-checker's rating and the claim it reviewed. Signals, not verdicts.
    rating: str | None = None
    reviewed_claim: str | None = None


class CorpusLookup(BaseModel):
    hits: list[CorpusHit] = []
    limitation: str | None = None  # set when the search could not run


def tsquery_terms(query: str) -> str:
    """Words of the query as an OR of prefixes ("strajk:*" also finds "strajku"); "" for none."""
    words = [w for w in re.findall(r"\w{3,}", query.lower()) if w not in STOPWORDS]
    return " | ".join(f"{w}:*" for w in dict.fromkeys(words[:MAX_TERMS]))


def to_hit(row: tuple) -> CorpusHit:
    title, publisher, published, retrieved, url, kind, rating, claim, text, score = row
    return CorpusHit(
        source=Source(
            title=title,
            publisher=publisher,
            published_at=published.date() if published else None,
            fetched_at=retrieved,
            url=url,
            source_type=kind,
            fragment=text,
            # Also on the source, where the judge reads them.
            rating=rating,
            reviewed_claim=claim,
        ),
        score=float(score),
        rating=rating,
        reviewed_claim=claim,
    )


async def search_corpus(query: str, *, k: int = 8) -> CorpusLookup:
    url = os.getenv("DATABASE_URL")
    if not url:
        log.warning("corpus search skipped: DATABASE_URL is not set")
        return CorpusLookup(limitation=SEARCH_UNAVAILABLE)
    if not embeddings.is_ready():
        embeddings.warm_up()
        log.warning("corpus search skipped: the embedding model is still loading")
        return CorpusLookup(limitation=SEARCH_UNAVAILABLE)
    params = {
        "terms": tsquery_terms(query),
        "pool": POOL,
        "rrf_k": RRF_K,
        "per_doc": PER_DOC,
        "k": k,
    }
    try:
        async with asyncio.timeout(DEADLINE_S):
            # The model runs on the CPU; a thread keeps the event loop free meanwhile.
            params["vector"] = await asyncio.to_thread(embeddings.embed_query, query)
            async with await psycopg.AsyncConnection.connect(
                url, connect_timeout=5
            ) as conn:
                await register_vector_async(conn)
                rows = await (await conn.execute(SQL, params)).fetchall()
                state = await (
                    await conn.execute(
                        "SELECT value FROM corpus_meta WHERE key = 'complete'"
                    )
                ).fetchone()
    except TimeoutError:
        log.warning("corpus search unavailable: no answer within %s s", DEADLINE_S)
        return CorpusLookup(limitation=SEARCH_UNAVAILABLE)
    # Database, driver, or the model (fastembed raises ValueError, onnxruntime RuntimeError):
    # never a crash of the whole check.
    except (psycopg.Error, OSError, ValueError, RuntimeError) as exc:
        log.warning("corpus search unavailable: %s", type(exc).__name__)
        return CorpusLookup(limitation=SEARCH_UNAVAILABLE)
    complete = state is not None and state[0] == "true"
    return CorpusLookup(
        hits=[to_hit(row) for row in rows],
        limitation=None if complete else INDEX_INCOMPLETE,
    )


if __name__ == "__main__":
    embeddings.embed_query("")  # load the model first: a one-off command has no warm-up
    found = asyncio.run(search_corpus(" ".join(sys.argv[1:])))
    for hit in found.hits:
        s = hit.source
        print(f"{hit.score:.4f}  {s.published_at}  {s.publisher} | {s.title[:80]}")
        print(f"        {s.url}  {hit.rating or ''}")
        print(f"        {s.fragment[:220]!r}")
    if found.limitation:
        print(found.limitation)
