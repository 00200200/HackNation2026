#!/bin/sh
# Deploys origin/prod to this server when it moves. faktczyfejk-deploy.timer runs it every minute;
# setup and logs are in docs/deploy.md. A deploy that fails, including the final HTTPS check, is
# retried on the next run.
set -eu
cd /opt/faktczyfejk
exec 9>.git/deploy.lock
flock -n 9 || exit 0 # another run is still going
deployed=.git/deployed-commit

git fetch --quiet origin prod
target=$(git rev-parse origin/prod)
[ "$target" = "$(cat "$deployed" 2>/dev/null || true)" ] && exit 0

echo "deploying $(git log -1 --format='%h %s' "$target")"
git reset --quiet --hard "$target"
docker compose up -d --build --remove-orphans --wait --wait-timeout 300
docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
domain=$(docker compose exec -T caddy printenv DOMAIN) # the name Caddy actually serves
curl -fsS -o /dev/null --connect-timeout 10 --max-time 20 --retry 10 --retry-delay 3 --retry-all-errors "https://$domain/health"
echo "$target" > "$deployed"
echo "deployed $(git rev-parse --short HEAD)"
