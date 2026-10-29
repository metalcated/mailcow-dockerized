#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
test "$(git branch --show-current)" = 'feature/october-2026-next-unbound'
test "${1:-check}" = check || test "${1:-check}" = apply
MODE=${1:-check}
docker compose config --quiet
EXPECTED='ghcr.io/mailcow/unbound:1.26.2-1@sha256:016bd7056ac86ef3f43ae05d38b7bfa0c59afed69ffac1eab30ea00e0850cb8b'
TARGET=$(docker compose config --images unbound-mailcow | awk '/^ghcr[.]io\/mailcow\/unbound[:@]/')
test "$TARGET" = "$EXPECTED"
CONTAINER=$(docker compose ps -q unbound-mailcow)
test -n "$CONTAINER"
mkdir -p backups
RECOVERY_DIR=$(mktemp -d "backups/unbound-pre-october-2026-$(date +%Y%m%d-%H%M%S)-XXXXXX")
chmod 700 "$RECOVERY_DIR"
ROLLBACK="mailcow-unbound-rollback:pre-october-2026-$(date +%Y%m%d%H%M%S)"
docker image tag "$(docker inspect --format '{{.Image}}' "$CONTAINER")" "$ROLLBACK"
printf '%s\n' "$ROLLBACK" > "$RECOVERY_DIR/rollback-image.txt"
cp -a data/conf/unbound "$RECOVERY_DIR/config"
docker compose exec -T unbound-mailcow tar -C /etc/unbound -czf - . > "$RECOVERY_DIR/runtime.tar.gz"
gzip -t "$RECOVERY_DIR/runtime.tar.gz"
printf '\nRecovery: %s\nRollback: %s\n' "$RECOVERY_DIR" "$ROLLBACK"
trap 'STATUS=$?; if [ "$STATUS" -ne 0 ]; then printf "\nStopped. Keep %s. Image-only rollback: UNBOUND_IMAGE=%q docker compose up -d --no-deps --force-recreate unbound-mailcow\n" "$RECOVERY_DIR" "$ROLLBACK"; fi' EXIT
docker pull "$TARGET"
docker run --rm --pull=never --network=none \
  --mount "type=bind,src=$PWD/$RECOVERY_DIR,dst=/backup,readonly" \
  --entrypoint sh "$TARGET" -ec 'tar -xzf /backup/runtime.tar.gz -C /etc/unbound; unbound-checkconf /etc/unbound/unbound.conf; unbound -V; test -s /etc/unbound/trusted-key.key'
if [ "$MODE" = check ]; then
  echo 'Preflight passed; no service was replaced. Run again with apply when ready.'
  exit 0
fi
docker compose up -d --no-deps --force-recreate unbound-mailcow
READY=0
for ATTEMPT in $(seq 1 60); do
  if docker compose exec -T unbound-mailcow dig @127.0.0.1 cloudflare.com A +dnssec +time=2 +tries=1 2>/dev/null | grep -q 'flags:.* ad[; ]'; then
    READY=1
    break
  fi
  sleep 2
done
docker compose logs --since=4m --tail=70 unbound-mailcow
test "$READY" -eq 1
docker compose exec -T unbound-mailcow sh -ec 'dig @127.0.0.1 dnssec-failed.org A +dnssec +time=3 +tries=1 | grep -q "status: SERVFAIL"'
docker compose exec -T postfix-mailcow getent ahostsv4 gmail.com
docker compose exec -T rspamd-mailcow getent ahostsv4 gmail.com
docker compose exec -T unbound-mailcow unbound -V
docker compose ps unbound-mailcow postfix-mailcow rspamd-mailcow dovecot-mailcow
printf '\nRecovery: %s\nRollback: %s\n' "$RECOVERY_DIR" "$ROLLBACK"
echo 'Verify normal mail send/receive and existing Outlook sync before the web stage.'
