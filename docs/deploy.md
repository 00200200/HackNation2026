# Deploy

The public demo runs on one Linux server in the EU with Docker Compose. Caddy is the server's only
reverse proxy: it gets and renews the HTTPS certificates and proxies faktczyfejk.pl to the nginx
frontend, which serves the static UI and forwards `/api/` and `/health` to the backend. It also
serves other projects on the server (see "Other projects on this server"). Only Caddy publishes
ports (80 and 443).

```
browser --HTTPS--> caddy :443 --> frontend (nginx) :80 --> backend (FastAPI) :8000 --> db (Postgres + pgvector) :5432
```

A push to the `prod` branch deploys. Every minute the server fetches `prod`; when it has moved, the
server checks the new commit out in `/opt/faktczyfejk` and runs `docker compose up -d --build`
there. No CI service is involved, and a failed deploy is retried on the next run.

| File | Role |
|---|---|
| `compose.yaml` | backend and frontend, also used for local runs |
| `compose.prod.yaml` | production overlay: Caddy, Postgres with pgvector, no host port on nginx, real client IP for the rate limit |
| `caddy/Caddyfile` | HTTPS sites: `DOMAIN` and `www`, doc2json.pl and `www` |
| `deploy/pull-deploy.sh` | deploys `origin/prod` when it moves |
| `deploy/faktczyfejk-deploy.service`, `.timer` | run the script every minute as `ubuntu` |
| `.env` on the server | `DOMAIN`, `COMPOSE_FILE`, `ANTHROPIC_API_KEY`, `POSTGRES_*` (never committed; deploys leave it alone) |

## What you need

- A server in the EU with Ubuntu 24.04, at least 2 vCPU and 4 GB RAM, and a public IPv4 address.
- The domain, with a DNS zone you can edit.
- An SSH key on your laptop: `ssh-keygen -t ed25519 -N "" -f ~/.ssh/faktczyfejk`.
- An Anthropic API key, and admin rights on the GitHub repository (to add the server's deploy key).

## 1. Server access

The provider sends the login user and a password (OVHcloud: user `ubuntu`, password from a link
in the delivery email). OVHcloud makes you change that password at the first login, which
`ssh-copy-id` cannot do, so log in once by hand first, then install your public key with the new
password and log in with it:

```bash
ssh ubuntu@SERVER_IPV4          # set the new password when asked; the session may close
ssh-copy-id -i ~/.ssh/faktczyfejk.pub ubuntu@SERVER_IPV4
ssh -i ~/.ssh/faktczyfejk ubuntu@SERVER_IPV4
```

## 2. Server setup (once)

On the server, install Docker and give the server a read-only key for the repository:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
sudo docker network create edge     # shared with other projects Caddy serves, see "Other projects"
ssh-keygen -t ed25519 -N "" -C faktczyfejk-vps -f ~/.ssh/github_deploy
printf 'Host github.com\n  IdentityFile ~/.ssh/github_deploy\n  IdentitiesOnly yes\n' >> ~/.ssh/config
ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts
ssh-keygen -lf ~/.ssh/known_hosts | grep github.com
```

The last line must show GitHub's published ED25519 fingerprint
(`gh api meta --jq .ssh_key_fingerprints.SHA256_ED25519` on your laptop). Then, on your laptop, add
the server's public key as a read-only deploy key:

```bash
ssh -i ~/.ssh/faktczyfejk ubuntu@SERVER_IPV4 'cat ~/.ssh/github_deploy.pub' > /tmp/faktczyfejk-vps.pub
gh repo deploy-key add /tmp/faktczyfejk-vps.pub --title faktczyfejk-vps -R 00200200/HackNation2026
```

Back on the server, clone `prod` and write the configuration:

```bash
sudo install -d -o ubuntu -g ubuntu /opt/faktczyfejk
git clone --branch prod git@github.com:00200200/HackNation2026.git /opt/faktczyfejk
cd /opt/faktczyfejk
printf 'DOMAIN=faktczyfejk.pl\nCOMPOSE_FILE=compose.yaml:compose.prod.yaml\nANTHROPIC_API_KEY=\nPRAWDOWID_MODEL=\nTAVILY_API_KEY=\nGOOGLE_FACTCHECK_API_KEY=\nEUVSDISINFO_API_KEY=\nPOSTGRES_DB=prawdowid\nPOSTGRES_USER=prawdowid\nPOSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env
chmod 600 .env
nano .env      # paste the keys after ANTHROPIC_API_KEY=, TAVILY_API_KEY= and the others you have
```

The evidence keys matter as much as the model key: without `TAVILY_API_KEY` (web search, the only
search provider), `GOOGLE_FACTCHECK_API_KEY` and `EUVSDISINFO_API_KEY` every source lookup fails,
`/health` still answers, and every checkable claim ends as "nie sprawdzono". `compose.yaml`
forwards all three to the backend.

The database password is generated on the server and never leaves it; hex keeps it safe inside
the `DATABASE_URL` that Compose builds for the backend. `COMPOSE_FILE` makes every
`docker compose` command in `/opt/faktczyfejk` load both Compose files. Empty `PRAWDOWID_MODEL`
means the default model. `get.docker.com` is Docker's install script; Docker recommends its apt
repository for long-lived production hosts: https://docs.docker.com/engine/install/ubuntu/.

If you turn on the provider's firewall, allow 22/tcp, 80/tcp, 443/tcp and 443/udp, and on a
stateless one (OVHcloud Edge Network Firewall) also "TCP established", or the server's own outgoing
connections (git fetch, image pulls, Let's Encrypt, the Anthropic API) stop working.

## 3. DNS

Create two records in the domain's zone, both of type `A` with the server's IPv4 address: one for
the domain itself (`@` or empty name) and one for `www` (Caddy redirects it to the domain). Remove
any other `A` or `AAAA` record for these two names (registrars often add parking ones).

There is deliberately no `AAAA` record. With Docker's defaults, connections to the host's IPv6
address reach the containers through Docker's userland proxy, which hides the visitor's address
([port publishing](https://docs.docker.com/engine/network/port-publishing/)), so all IPv6
visitors would share one rate-limit bucket.

Before the first deploy, the first two lookups must print the server's address and the last two
nothing:

```bash
dig +short A faktczyfejk.pl
dig +short A www.faktczyfejk.pl
dig +short AAAA faktczyfejk.pl
dig +short AAAA www.faktczyfejk.pl
```

Caddy requests the certificate as soon as it starts, and repeated failures run into Let's Encrypt
rate limits, so wait for DNS first.

## 4. Automatic deploys (once)

Log out and in again so the `docker` group applies, then on the server:

```bash
sudo cp /opt/faktczyfejk/deploy/faktczyfejk-deploy.service /opt/faktczyfejk/deploy/faktczyfejk-deploy.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now faktczyfejk-deploy.timer
```

The first run builds and starts the stack: right away if the server has been up for more than a
minute, otherwise a minute after boot. Copy the two unit files again and run
`sudo systemctl daemon-reload` whenever they change in the repository.

The service runs the script from the checkout, so `prod` must never move back to a commit without
`deploy/`. If it does, every run fails with "cannot open" until you check out a newer `prod` by hand:
`git -C /opt/faktczyfejk fetch origin prod && git -C /opt/faktczyfejk reset --hard origin/prod`.

## 5. Deploy

`prod` only ever receives commits that are already on `main`. Promote from a clean, up-to-date
checkout of `main`. The pre-push hook treats this like any other push: it runs ruff and pytest on
the working tree, asks for a judge PASS for that commit when `prod` moves, and, if this clone has
eval results for another commit while product code changed, a fresh
`uv run python -m evals.run --quick` on it.

```bash
git switch main && git pull
git push origin main:prod
```

The server picks the new commit up within about a minute, then builds it and waits up to 5 minutes
for every service to be healthy and for `https://DOMAIN/health` to answer. On the server:

```bash
journalctl -u faktczyfejk-deploy -n 30 --no-pager   # "deploying ...", "deployed ..." or the error
cat /opt/faktczyfejk/.git/deployed-commit           # the last commit that deployed successfully
sudo systemctl start faktczyfejk-deploy             # run a check now instead of waiting
```

A failed build changes nothing, the previous containers keep serving. A deploy that fails later,
at the health wait or the HTTPS check, has already replaced the containers, so the demo may answer
with errors until a fix reaches `prod`; the checked-out commit is then ahead of `deployed-commit`.
After editing `.env`, apply it with `docker compose up -d` in `/opt/faktczyfejk`. To roll back,
revert the bad commit on `main` and push `main:prod` again.

## 6. Check it

```bash
curl -fsS https://faktczyfejk.pl/health
curl -fsS https://faktczyfejk.pl/api/checks -H 'Content-Type: application/json' \
  -d '{"input": "Warszawa jest stolicą Polski."}'
```

The second answer must contain `"status":"ok"`. Without a valid Anthropic key it is HTTP 200 with
`"status":"technical_error"`, so `curl -f` alone does not catch it. Then open the site in a browser
and run one check. On the server,
`docker compose logs frontend | grep 'POST /api/checks' | tail -n 3` must show your public IPv4
address, not a `172.x` one: that is the address the backend rate limit counts.

## 7. Discord bot (optional second channel)

The `discord` service in `compose.yaml` runs `python -m prawdowid.discord_bot` from the same image
as the backend and calls `http://backend:8000/api/checks` with `X-Channel: discord`. It needs only
two lines in the server's `.env`: `COMPOSE_PROFILES=discord` and `DISCORD_BOT_TOKEN`. No compose
change, no extra key (it never talks to Anthropic itself), no open port. Nobody has run it against
real Discord yet (UNCONFIRMED until step E below passes), and the token is created by a person,
never by an agent or a script.

**A. Create the application and the bot** (Discord account, the account that owns the bot):

1. Open https://discord.com/developers/applications, **New Application**, name it (for example
   "Prawdowid"), accept the terms.
2. **General Information**: copy the **Application ID**. It is the `client_id` of the invite link.
3. **Bot** tab: **Reset Token**, copy it once. Treat it like a password: it goes only into the
   server's `.env`, never into the repository, a chat or a ticket. Leave all three **Privileged
   Gateway Intents** off: the bot only answers slash commands and reads no messages. Switch
   **Public Bot** on if people outside your own account are to add it.

**B. Invite link.** Replace `APPLICATION_ID` with the number from step A.2:

```
https://discord.com/oauth2/authorize?client_id=APPLICATION_ID&scope=bot%20applications.commands&permissions=34816
```

Scopes: `bot` and `applications.commands` (the slash command). Permissions `34816` = Send Messages
(2048) + Attach Files (32768); the bot attaches `odpowiedz.md` when an answer is too long for five
messages. Open the link while signed in to Discord, choose a server where you have **Manage
Server**, authorise. Use a test server first.

**C. Server `.env`.** On the server, in `/opt/faktczyfejk`:

```bash
nano .env      # add the two lines below, keep the rest
```

```
COMPOSE_PROFILES=discord
DISCORD_BOT_TOKEN=paste-the-token-here
```

`.env` stays `chmod 600` and is never committed; deploys leave it alone.

**D. Start it and read the log.** Do this by hand before the next promotion to `prod` (see the
warning below):

```bash
cd /opt/faktczyfejk
docker compose up -d --build discord
docker compose logs --tail 30 discord
```

The log must show the bot logging in and connecting to the gateway, and no `LoginFailure` or
traceback. `docker compose ps` must list `discord` as `running`. A wrong token ends the process
with `LoginFailure: Improper token`; Docker then restarts the container three times (`restart: on-failure:3`) and gives up.

**E. Test in Discord.** In the test server run `/sprawdz tekst:Warszawa jest stolicą Polski.` The
first answer can take up to a minute. A new slash command can need a minute, or a restart of the
Discord client (Ctrl+R), before it shows up. Check `docker compose logs backend | tail` for a
line with `channel=discord`. Then run the same sentence in the web form: the verdict and sources
must be identical when you ask within 30 minutes (the result cache returns the stored answer for the same text; it is empty after a restart or deploy, and an answer with a claim marked `nie sprawdzono` is not stored, so then a second run may differ).
Only after that may the README and `docs/submission/description.md` say the bot was tested, and
the invite link go into both.

**Apply a change to the token or the profile:** edit `.env`, then `docker compose up -d` in
`/opt/faktczyfejk` (a changed token recreates `discord`). **Switch the bot off:** remove the two
lines and run `docker compose --profile discord rm -sf discord`.

Warning: `deploy/pull-deploy.sh` runs `docker compose up -d --wait`. With `COMPOSE_PROFILES=discord`
a bot that exits (missing or wrong token) makes that command fail, so a promotion to `prod` stops
before the Caddy reload and the HTTPS check, is not recorded as deployed, and is retried every
minute. The web channel keeps serving the new containers meanwhile. So put a verified token in
`.env` first (D), and remove the profile line if the bot is not wanted any more.

Limits of this channel: the bot calls the backend from its container, so all Discord users share
one rate limit of 10 checks per minute (the backend counts per IP address); the 11th request in
a minute is answered with the rate-limit notice in Discord. The bot sends no `X-Session-Id`, so a
Discord user cannot delete their checks through the web form's "delete my data" (`docs/privacy.md`).

## Logs and status

On the server, in `/opt/faktczyfejk`:

```bash
docker compose ps
docker compose logs -f --tail 100       # all services
docker compose logs -f backend          # one line per check: status, latency, input length
docker compose logs caddy | grep -i certificate
journalctl -u faktczyfejk-deploy -n 50 --no-pager
```

## Database

`db` runs Postgres 18 with pgvector (`pgvector/pgvector:0.8.7-pg18`). Its data lives in the Docker
volume `db_data`, its port is not published, and the backend gets
`DATABASE_URL=postgresql://USER:PASSWORD@db:5432/DB` from `compose.prod.yaml`. On the first start
with an empty volume Postgres creates the `vector` and `pg_trgm` extensions.

### Search index

The corpus search (`prawdowid/corpus_search.py`) reads the tables `corpus_documents` and `corpus_chunks` (an
embedding per chunk with an HNSW index, a full-text vector with a GIN index). They are built from
`corpus/evidence.jsonl`, which is part of the backend image. After a deploy that changes the corpus,
load it once:

```bash
docker compose exec backend python -m prawdowid.index corpus/evidence.jsonl
```

The first run downloads the embedding model (`intfloat/multilingual-e5-large`, about 2.2 GB) into
the `models` volume and embeds every chunk; later runs embed only documents that changed and
delete the ones that left the corpus. The model needs about 3 GB of memory while it runs, in the
indexer, and in the backend once the first corpus search has loaded it (the backend loads it
only when corpus search is first called, not at startup).

On the server, in `/opt/faktczyfejk`. Backups go to `~/backups`, outside the checkout:

```bash
# SQL shell
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
# backup (custom format, compressed)
mkdir -p ~/backups
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > ~/backups/prawdowid-$(date +%F).dump
# restore a backup into the running database
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < ~/backups/prawdowid-YYYY-MM-DD.dump
```

## Other projects on this server

Caddy here is the server's only reverse proxy, so it also serves doc2json.pl (repository
HackNation2026-2). That project runs from `/opt/doc2json` with its own Compose file; its web
container `doc2json-web` joins the external Docker network `edge` and publishes no ports, and Caddy
reaches it as `doc2json-web:80`. Its site blocks live in `caddy/Caddyfile` in this repository, so
changing them is a PR here and a push to `prod`, like any other change. DNS: `A` records for
`doc2json.pl` and `www.doc2json.pl` pointing at the server, and no other `A` or `AAAA` records for
those names. Caddy gets each domain's certificate on its own; until doc2json.pl resolves to the
server, its certificate requests fail without affecting faktczyfejk.pl.

Caddy reaches this stack's nginx as `faktczyfejk-frontend`, an alias on this project's own network,
so a container called `frontend` on `edge` cannot take its traffic. Still, give containers on `edge`
unique names and never `frontend` or `caddy`. Caddy's admin API listens only on its own loopback
(127.0.0.1:2019), so other containers on `edge` cannot reconfigure it.

To add another project the same way: put its web container on `edge` under a unique name, add a
site block to `caddy/Caddyfile`, and point the domain's `A` records at the server.

## Known limits

- The rate limit counts per IP address (10 checks per minute), so people behind one NAT, such as
  a mobile carrier or a venue network, share a limit.
- No IPv6 (see "DNS").
- One server, no failover. `restart: unless-stopped` brings the containers back after a crash or
  a reboot, but if the server is down, so is the demo.
- A deploy that keeps failing is retried every minute until `prod` gets a fix; the journal shows
  why. Compose has no automatic rollback (see "Deploy").
- Container logs live in Docker's json-file logs without rotation and disappear when a container
  is recreated, which every deploy that rebuilds an image does.
- The database has no automatic backups and lives on the same server as everything else. Take a
  `pg_dump` (see "Database") before risky changes.

## Where data is processed

- Web server, API, database and logs: OVHcloud VPS in Limburg, Germany.
- Corpus search embeddings: computed on the same server with a local model; no external service.
- The text of each check goes to the Anthropic API for claim extraction.

## Try the production setup locally

With Docker Desktop and ports 80 and 443 free on your machine:

```bash
docker network create edge      # once; the overlay expects it
DOMAIN=localhost POSTGRES_DB=prawdowid POSTGRES_USER=prawdowid POSTGRES_PASSWORD=local \
  docker compose -f compose.yaml -f compose.prod.yaml up --build
curl -k https://localhost/health
```

For `localhost` Caddy uses its own local certificate authority, hence `-k`. It also tries to get
public certificates for doc2json.pl from your laptop; those requests fail, which is harmless.

## After the event

This also takes doc2json.pl offline: its proxy and certificate live in this stack. On the server,
take a final `pg_dump` if the data should be kept (see "Database"), then:

```bash
sudo systemctl disable --now faktczyfejk-deploy.timer
cd /opt/faktczyfejk && docker compose down -v      # also deletes the database and certificate volumes
```

Then:

1. Cancel the server in the provider's panel. An OVHcloud VPS renews every month until you switch
   renewal off or cancel it. (Hetzner bills a server until it is deleted, even when it is
   switched off: [Hetzner billing FAQ](https://docs.hetzner.com/cloud/billing/faq/).)
2. In GitHub, remove the `faktczyfejk-vps` deploy key (`gh repo deploy-key list -R 00200200/HackNation2026`,
   then `gh repo deploy-key delete <id> -R 00200200/HackNation2026`). Revoke the Anthropic API key that
   was on the server.
3. Remove the DNS records, and switch off the domain's automatic renewal if you do not keep it.
