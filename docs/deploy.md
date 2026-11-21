# Deploy

The public demo runs on one Linux server in the EU with Docker Compose. Caddy gets and renews
the HTTPS certificate and proxies every request to the nginx frontend, which serves the static UI
and forwards `/api/` and `/health` to the backend. Only Caddy publishes ports (80 and 443).

```
browser --HTTPS--> caddy :443 --> frontend (nginx) :80 --> backend (FastAPI) :8000 --> db (Postgres + pgvector) :5432
```

A push to the `prod` branch deploys: GitHub Actions copies the checked-out code to
`/opt/faktczyfejk` on the server over SSH and runs `docker compose up -d --build` there.

| File | Role |
|---|---|
| `compose.yaml` | backend and frontend, also used for local runs |
| `compose.prod.yaml` | production overlay: Caddy, Postgres with pgvector, no host port on nginx, real client IP for the rate limit |
| `caddy/Caddyfile` | HTTPS site for `DOMAIN` |
| `.github/workflows/deploy.yml` | deploy on push to `prod`, or by hand from the Actions tab |
| `.env` on the server | `DOMAIN`, `COMPOSE_FILE`, `ANTHROPIC_API_KEY`, `POSTGRES_*` (never committed, never copied by deploys) |

## What you need

- A server in the EU with Ubuntu 24.04, at least 2 vCPU and 4 GB RAM, and a public IPv4 address.
- The domain, with a DNS zone you can edit.
- Two SSH keys on your laptop, one for you and one for GitHub Actions:
  ```bash
  ssh-keygen -t ed25519 -N "" -f ~/.ssh/faktczyfejk
  ssh-keygen -t ed25519 -N "" -f ~/.ssh/faktczyfejk_ci
  ```
- An Anthropic API key, and admin rights on the GitHub repository.

## 1. Server access

The provider sends the login user and a password (OVHcloud: user `ubuntu`, password from a link
in the delivery email). OVHcloud makes you change that password at the first login, which
`ssh-copy-id` cannot do, so log in once by hand first, then install both public keys with the new
password and log in with your key:

```bash
ssh ubuntu@SERVER_IPV4          # set the new password when asked; the session may close
ssh-copy-id -i ~/.ssh/faktczyfejk.pub ubuntu@SERVER_IPV4
ssh-copy-id -i ~/.ssh/faktczyfejk_ci.pub ubuntu@SERVER_IPV4
ssh -i ~/.ssh/faktczyfejk ubuntu@SERVER_IPV4
```

## 2. Server setup (once)

On the server:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo apt-get install -y rsync
sudo usermod -aG docker ubuntu
sudo install -d -o ubuntu -g ubuntu /opt/faktczyfejk
cd /opt/faktczyfejk
printf 'DOMAIN=faktczyfejk.pl\nCOMPOSE_FILE=compose.yaml:compose.prod.yaml\nANTHROPIC_API_KEY=\nPRAWDOWID_MODEL=\nPOSTGRES_DB=prawdowid\nPOSTGRES_USER=prawdowid\nPOSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 24)" > .env
chmod 600 .env
nano .env      # paste the Anthropic key after ANTHROPIC_API_KEY=
```

The database password is generated on the server and never leaves it; hex keeps it safe inside
the `DATABASE_URL` that Compose builds for the backend.

Log out and in again so the `docker` group applies. `get.docker.com` is Docker's install script;
Docker recommends its apt repository for long-lived production hosts:
https://docs.docker.com/engine/install/ubuntu/. `COMPOSE_FILE` makes every `docker compose`
command in `/opt/faktczyfejk` load both Compose files. Empty `PRAWDOWID_MODEL` means the default
model. If you turn on the provider's firewall, allow 22/tcp, 80/tcp, 443/tcp and 443/udp, and on a
stateless one (OVHcloud Edge Network Firewall) also "TCP established", or the server's own outgoing
connections (image pulls, Let's Encrypt, the Anthropic API) stop working.

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

## 4. GitHub variables and secret (once)

On your laptop, with `gh` logged in as a repository admin:

```bash
gh variable set DEPLOY_DOMAIN --body faktczyfejk.pl
gh variable set DEPLOY_HOST --body SERVER_IPV4
gh variable set DEPLOY_USER --body ubuntu
gh variable set DEPLOY_KNOWN_HOSTS --body "$(ssh-keyscan -t ed25519 SERVER_IPV4 2>/dev/null)"
gh secret set DEPLOY_SSH_KEY < ~/.ssh/faktczyfejk_ci
```

`DEPLOY_KNOWN_HOSTS` pins the server's host key, so a deploy stops if the key changes. Compare
`ssh-keygen -lf <(gh variable get DEPLOY_KNOWN_HOSTS)` with the fingerprint you accepted at your
first login.

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

The push starts the "Deploy" workflow (Actions tab). It fails if a service does not become running
or healthy within 5 minutes, or if `https://DEPLOY_DOMAIN/health` does not answer afterwards. To
redeploy without a new commit, for example after editing `.env` on the server, run it by hand with
`gh workflow run Deploy --ref prod`, or Actions → Deploy → Run workflow with `prod` selected. The
job only runs for `prod`; started from any other branch it is skipped.

To roll back, revert the bad commit on `main` and push `main:prod` again.

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

## Logs and status

On the server, in `/opt/faktczyfejk`:

```bash
docker compose ps
docker compose logs -f --tail 100       # all services
docker compose logs -f backend          # one line per check: status, latency, input length
docker compose logs caddy | grep -i certificate
```

## Database

`db` runs Postgres 18 with pgvector (`pgvector/pgvector:0.8.7-pg18`). Its data lives in the Docker
volume `db_data`, its port is not published, and the backend gets
`DATABASE_URL=postgresql://USER:PASSWORD@db:5432/DB` from `compose.prod.yaml`. On the first start
with an empty volume Postgres creates the `vector` and `pg_trgm` extensions. The application does
not use the database yet: tables and loading the corpus come with the search work.

On the server, in `/opt/faktczyfejk`. Backups go to `~/backups`, never into `/opt/faktczyfejk`:
every deploy deletes files there that are not in git.

```bash
# SQL shell
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
# backup (custom format, compressed)
mkdir -p ~/backups
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > ~/backups/prawdowid-$(date +%F).dump
# restore a backup into the running database
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < ~/backups/prawdowid-YYYY-MM-DD.dump
```

## Known limits

- The rate limit counts per IP address (10 checks per minute), so people behind one NAT, such as
  a mobile carrier or a venue network, share a limit.
- No IPv6 (see "DNS").
- One server, no failover. `restart: unless-stopped` brings the containers back after a crash or
  a reboot, but if the server is down, so is the demo.
- Container logs live in Docker's json-file logs without rotation and disappear when a container
  is recreated, which every deploy that rebuilds an image does.
- The database has no automatic backups and lives on the same server as everything else. Take a
  `pg_dump` (see "Database") before risky changes.

## Where data is processed

- Web server, API, database and logs: OVHcloud VPS in Limburg, Germany.
- The text of each check goes to the Anthropic API for claim extraction.

## Try the production setup locally

With Docker Desktop and ports 80 and 443 free on your machine:

```bash
DOMAIN=localhost POSTGRES_DB=prawdowid POSTGRES_USER=prawdowid POSTGRES_PASSWORD=local \
  docker compose -f compose.yaml -f compose.prod.yaml up --build
curl -k https://localhost/health
```

For `localhost` Caddy uses its own local certificate authority, hence `-k`.

## After the event

On the server, take a final `pg_dump` if the data should be kept (see "Database"), then
`cd /opt/faktczyfejk && docker compose down -v`, which also deletes the database and certificate
volumes. Then:

1. Cancel the server in the provider's panel. An OVHcloud VPS renews every month until you switch
   renewal off or cancel it. (Hetzner bills a server until it is deleted, even when it is
   switched off: [Hetzner billing FAQ](https://docs.hetzner.com/cloud/billing/faq/).)
2. In GitHub: `gh secret delete DEPLOY_SSH_KEY` and delete the four `DEPLOY_*` variables. Revoke
   the Anthropic API key that was on the server.
3. Remove the DNS records, and switch off the domain's automatic renewal if you do not keep it.
