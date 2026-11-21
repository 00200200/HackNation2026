-- Step 2c (#19): our own source store, a local PostgreSQL. Pages fetched by web search (#8), split
-- into chunks, with full-text search. `docker compose` applies this file when the database volume is
-- created; `make db-migrate` applies it to an existing one (safe to rerun).
--
-- Full text only: pgvector and the embedding model are UNDECIDED (WORKLOG). Stock Postgres has no
-- Polish text search configuration, so the index uses 'simple' (lower-case words, no stemming);
-- the app widens recall with prefix terms (prawdowid/cache.py, build_tsquery).

create table if not exists documents (
    id bigint generated always as identity primary key,
    -- Canonical URL (prawdowid/rerank.py canonical_url): the doc id rerank (#9) keys on.
    doc_id text not null unique,
    url text not null,
    title text not null,
    publisher text not null,
    domain text not null,
    source_type text not null,
    -- Licence of this page. UNCONFIRMED for every domain until the team checks the terms
    -- (docs/sources.md); until then we quote short passages with a link and never republish.
    licence text not null,
    published_at date not null,
    fetched_at timestamptz not null,
    content_hash text not null,
    text text not null,
    -- Retention: a page is deleted after this time (delete_expired_documents below).
    delete_after timestamptz not null default now() + interval '90 days'
);

create table if not exists chunks (
    id bigint generated always as identity primary key,
    document_id bigint not null references documents (id) on delete cascade,
    position int not null,
    text text not null,
    tsv tsvector generated always as (to_tsvector('simple', text)) stored,
    unique (document_id, position)
);

create index if not exists chunks_tsv on chunks using gin (tsv);
create index if not exists documents_delete_after on documents (delete_after);

-- Access control: the database is reachable only on the compose network and on 127.0.0.1
-- (compose.yaml); the backend is the only service given DATABASE_URL.

-- Deletion procedure: drops expired pages (chunks go with them). The seed script runs it first.
create or replace function delete_expired_documents()
returns int
language sql
set search_path = public
as $$
    with gone as (delete from documents where delete_after <= now() returning 1)
    select count(*)::int from gone
$$;

-- Functions are callable by every role by default; keep this one to the owner (the backend).
revoke execute on function delete_expired_documents() from public;
