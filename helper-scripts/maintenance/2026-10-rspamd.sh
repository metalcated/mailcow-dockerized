#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
test "$(git branch --show-current)" = 'feature/october-2026-next-rspamd'
MODE=${1:-check}
test "$MODE" = check || test "$MODE" = apply
docker compose config --quiet
TARGET=$(docker compose config --images rspamd-mailcow | awk '/^ghcr[.]io\/mailcow\/rspamd[:@]/')
test "$TARGET" = 'ghcr.io/mailcow/rspamd:4.2.1-1@sha256:6e7375761b6234cf6db6d462dc3f68f121401e9e6b75d7889ec0b22a62f64b4c'
CONTAINER=$(docker compose ps -q rspamd-mailcow)
test -n "$CONTAINER"
mkdir -p backups
RECOVERY_DIR=$(mktemp -d "backups/rspamd-pre-october-2026-$(date +%Y%m%d-%H%M%S)-XXXXXX")
ROLLBACK="mailcow-rspamd-rollback:pre-october-2026-$(date +%Y%m%d%H%M%S)"
docker image tag "$(docker inspect --format '{{.Image}}' "$CONTAINER")" "$ROLLBACK"
printf '%s\n' "$ROLLBACK" > "$RECOVERY_DIR/rollback-image.txt"
cp -a data/conf/rspamd "$RECOVERY_DIR/config"
docker compose exec -T rspamd-mailcow tar -C /var/lib/rspamd -czf - . > "$RECOVERY_DIR/rspamd-state.tar.gz"
gzip -t "$RECOVERY_DIR/rspamd-state.tar.gz"
docker compose exec -T redis-mailcow sh -ec 'export REDISCLI_AUTH="$REDISPASS"; exec timeout 180 redis-cli --rdb -' > "$RECOVERY_DIR/dump.rdb"
test -s "$RECOVERY_DIR/dump.rdb"
printf '\nRecovery: %s\nRollback: %s\n' "$RECOVERY_DIR" "$ROLLBACK"
trap 'STATUS=$?; if [ "$STATUS" -ne 0 ]; then printf "\nStopped. Keep %s. Image rollback: RSPAMD_IMAGE=%q docker compose up -d --no-deps --force-recreate rspamd-mailcow\nRestore the previous footer Lua from the pre-switch backup if needed. Do not restore Redis automatically.\n" "$RECOVERY_DIR" "$ROLLBACK"; fi' EXIT
docker pull "$TARGET"
# Never execute the candidate entrypoint against production Redis during preflight.
docker run --rm --pull=never --network=none \
  --add-host redis:127.0.0.1 --add-host rspamd:127.0.0.1 --add-host dovecot:127.0.0.1 \
  --add-host nginx:127.0.0.1 --add-host clamd:127.0.0.1 --add-host olefy:127.0.0.1 \
  --mount "type=bind,src=$PWD/data/conf/rspamd,dst=/fixture,readonly" \
  --entrypoint bash "$TARGET" -ec '
    for item in custom override.d local.d plugins.d lua rspamd.conf.local rspamd.conf.override; do cp -a /fixture/$item /etc/rspamd/; done
    ln -sf /usr/lib/$(uname -m)-linux-gnu/liblua5.1-cjson.so.0.0.0 /usr/lib/rspamd/cjson.so
    rspamadm configtest
    rspamd --version
  '
if [ "$MODE" = check ]; then
  echo 'Preflight passed. No service replaced; apply requires the Rspamd mail-test window.'
  exit 0
fi
docker compose up -d --no-deps --force-recreate rspamd-mailcow
sleep 10
docker compose exec -T rspamd-mailcow rspamadm configtest
docker compose exec -T rspamd-mailcow sh -ec 'export REDISCLI_AUTH="$REDISPASS"; test "$(redis-cli -e --raw -h redis PING)" = PONG; echo "Redis: PONG"'
docker compose exec -T rspamd-mailcow rspamd --version
docker compose logs --since=3m --tail=100 rspamd-mailcow
docker compose ps rspamd-mailcow postfix-mailcow dovecot-mailcow clamd-mailcow
printf '\nRecovery: %s\nRollback: %s\n' "$RECOVERY_DIR" "$ROLLBACK"
echo 'Now test inbound/outbound and attachment mail, footer, DKIM, quarantine/spam handling, and existing Outlook. Do not advance on a delivery or policy failure.'
