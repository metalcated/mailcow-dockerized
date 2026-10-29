#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
test "$(git branch --show-current)" = feature/october-2026-watchdog-legacy-compat
MODE=${1:-check}
test "$MODE" = check || test "$MODE" = apply
docker compose config --quiet
TARGET=$(docker compose config --images watchdog-mailcow | awk '/^ghcr[.]io\/mailcow\/watchdog[:@]/')
test "$TARGET" = 'ghcr.io/mailcow/watchdog:2.11@sha256:5436050d566d972cb157225f8a2b5c828c6bb188118f3bcab94dd8db065892c7'
CONTAINER=$(docker compose ps -q watchdog-mailcow)
test -n "$CONTAINER"
# Fail closed if an override would restore verbose secret logging or the absent monitor.
docker compose config --format json | python3 -c '
import json, sys
s = json.load(sys.stdin)["services"]["watchdog-mailcow"]
assert s["environment"]["DEV_MODE"] == "n"
assert s["environment"]["WATCHDOG_VERBOSE"].lower() in ("n", "no")
assert s["environment"]["WATCHDOG_POSTFIX_TLSPOL"] == "n"
assert s["command"] == ["/bin/bash", "/watchdog-legacy-entrypoint.sh"]
'
docker pull "$TARGET"
docker run --rm --pull=never --network=none \
  --mount "type=bind,src=$PWD/data/Dockerfiles/watchdog/legacy-entrypoint.sh,dst=/adapter.sh,readonly" \
  --entrypoint bash "$TARGET" /adapter.sh --check
if [ "$MODE" = check ]; then
  echo 'Watchdog offline preflight passed; production monitoring unchanged.'
  exit 0
fi
mkdir -p backups
RECOVERY_DIR=$(mktemp -d "backups/watchdog-pre-october-2026-$(date +%Y%m%d-%H%M%S)-XXXXXX")
ROLLBACK="mailcow-watchdog-rollback:pre-october-2026-$(date +%Y%m%d%H%M%S)"
docker image tag "$(docker inspect --format '{{.Image}}' "$CONTAINER")" "$ROLLBACK"
printf '%s\n' "$ROLLBACK" > "$RECOVERY_DIR/rollback-image.txt"
cp -a docker-compose.yml "$RECOVERY_DIR/"
printf '\nRecovery: %s\nRollback: %s\n' "$RECOVERY_DIR" "$ROLLBACK"
trap 'STATUS=$?; if [ "$STATUS" -ne 0 ]; then printf "\nStopped. Watchdog rollback:\nWATCHDOG_IMAGE=%q WATCHDOG_SCRIPT=/watchdog.sh docker compose up -d --no-deps --force-recreate watchdog-mailcow\n" "$ROLLBACK"; fi' EXIT
docker compose up -d --no-deps --force-recreate watchdog-mailcow
sleep 45
test "$(docker inspect --format '{{.State.Running}}' "$(docker compose ps -q watchdog-mailcow)")" = true
docker compose logs --since=2m --tail=120 watchdog-mailcow
docker compose ps watchdog-mailcow dockerapi-mailcow acme-mailcow dovecot-mailcow postfix-mailcow
printf '\nRecovery: %s\nRollback: %s\n' "$RECOVERY_DIR" "$ROLLBACK"
echo 'Require applicable worker health messages and no postfix-tlspol monitor. Monitoring can restart genuinely unhealthy services; do not advance on repeated failures.'
