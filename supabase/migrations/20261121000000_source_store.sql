-- Step 2c (#19): our own source store. Pages fetched by web search (#8), split into chunks, with
-- Postgres full-text search. Apply in the Supabase SQL editor or with `supabase db push`.
--
-- Full text only: pgvector and the embedding model are UNDECIDED (WORKLOG). Stock Postgres has no
-- Polish text search configuration, so the index uses 'simple' (lower-case words, no stemming);
-- the app widens recall with prefix terms (prawdowid/cache.py, build_tsquery).

create table documents (
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

create table chunks (
    id bigint generated always as identity primary key,
    document_id bigint not null references documents (id) on delete cascade,
    position int not null,
    text text not null,
    tsv tsvector generated always as (to_tsvector('simple', text)) stored,
    unique (document_id, position)
);

create index chunks_tsv on chunks using gin (tsv);
create index documents_delete_after on documents (delete_after);

-- Access control: row level security on, and no policies, so the public anon and authenticated
-- keys (Supabase Data API) read and write nothing. Only the backend reaches the tables: it
-- connects as the table owner through DATABASE_URL, which lives in the backend .env only.
alter table documents enable row level security;
alter table chunks enable row level security;

-- Deletion procedure: drops expired pages (chunks go with them). The seed script runs it; with
-- pg_cron enabled it can run daily:
--   select cron.schedule('delete-expired-documents', '0 3 * * *',
--                        'select delete_expired_documents()');
create function delete_expired_documents()
returns int
language sql
set search_path = public
as $$
    with gone as (delete from documents where delete_after <= now() returning 1)
    select count(*)::int from gone
$$;

-- Functions are callable by every role by default; keep this one to the backend.
revoke execute on function delete_expired_documents() from public, anon, authenticated;
