#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
test "$(git branch --show-current)" = 'feature/october-2026-next-olefy'
MODE=${1:-check}
test "$MODE" = check || test "$MODE" = apply
docker compose config --quiet
TARGET=$(docker compose config --images olefy-mailcow | awk '/^ghcr[.]io\/mailcow\/olefy[:@]/')
test "$TARGET" = 'ghcr.io/mailcow/olefy:1.15@sha256:cec980cddf162594f5f1a7b575ae95c0f17f0c42febcfac94a478eca2d2bfd9e'
CONTAINER=$(docker compose ps -q olefy-mailcow)
test -n "$CONTAINER"
mkdir -p backups
RECOVERY_DIR=$(mktemp -d "backups/olefy-pre-october-2026-$(date +%Y%m%d-%H%M%S)-XXXXXX")
ROLLBACK="mailcow-olefy-rollback:pre-october-2026-$(date +%Y%m%d%H%M%S)"
docker image tag "$(docker inspect --format '{{.Image}}' "$CONTAINER")" "$ROLLBACK"
printf '%s\n' "$ROLLBACK" > "$RECOVERY_DIR/rollback-image.txt"
cp -a docker-compose.yml "$RECOVERY_DIR/"
printf '\nRecovery: %s\nRollback: %s\n' "$RECOVERY_DIR" "$ROLLBACK"
trap 'STATUS=$?; if [ "$STATUS" -ne 0 ]; then printf "\nStopped. Image rollback: OLEFY_IMAGE=%q docker compose up -d --no-deps --force-recreate olefy-mailcow\n" "$ROLLBACK"; fi' EXIT
docker pull "$TARGET"
docker run --rm --pull=never --network=none \
  --mount "type=bind,src=$PWD/helper-scripts/tests/olefy_fixture.py,dst=/fixture.py,readonly" \
  --entrypoint /usr/bin/python3 "$TARGET" /fixture.py
if [ "$MODE" = check ]; then
  echo 'Offline scanner preflight passed; no production service replaced.'
  exit 0
fi
docker compose up -d --no-deps --force-recreate olefy-mailcow
docker compose exec -T -e OLEFY_FIXTURE_EXISTING=1 olefy-mailcow /usr/bin/python3 - < helper-scripts/tests/olefy_fixture.py
docker compose exec -T rspamd-mailcow bash -ec 'printf "PING\n\n" | nc -q 1 -w 5 olefy 10055 | grep -qx PONG; echo "Rspamd to Olefy: PONG"'
docker compose logs --since=3m --tail=70 olefy-mailcow rspamd-mailcow
docker compose ps olefy-mailcow rspamd-mailcow clamd-mailcow dovecot-mailcow postfix-mailcow
printf '\nRecovery: %s\nRollback: %s\n' "$RECOVERY_DIR" "$ROLLBACK"
echo 'Send and receive a normal Office attachment and inspect Rspamd for scanner errors. Existing Outlook must continue working.'
