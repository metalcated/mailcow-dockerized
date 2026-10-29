#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
test "$(git branch --show-current)" = 'feature/october-2026-next-unbound'
MODE=${1:-check}
case "$MODE" in check|apply|verify) ;; *) echo 'Usage: 2026-10-unbound.sh [check|apply|verify]' >&2; exit 2 ;; esac
docker compose config --quiet
EXPECTED='ghcr.io/mailcow/unbound:1.26.2-1@sha256:016bd7056ac86ef3f43ae05d38b7bfa0c59afed69ffac1eab30ea00e0850cb8b'
TARGET=$(docker compose config --images unbound-mailcow | awk '/^ghcr[.]io\/mailcow\/unbound[:@]/')
test "$TARGET" = "$EXPECTED"
CONTAINER=$(docker compose ps -q unbound-mailcow)
test -n "$CONTAINER"
RUNNING_ID=$(docker inspect --format '{{.Image}}' "$CONTAINER")
TARGET_ID=$(docker image inspect --format '{{.Id}}' "$TARGET" 2>/dev/null || true)
if [ "$MODE" = verify ]; then
  if [ -z "$TARGET_ID" ] || [ "$RUNNING_ID" != "$TARGET_ID" ]; then
    echo 'Verify requires the selected Unbound image to be running; nothing was replaced.' >&2
    exit 1
  fi
  exec bash helper-scripts/maintenance/2026-10-unbound-verify.sh
fi
if [ -n "$TARGET_ID" ] && [ "$RUNNING_ID" = "$TARGET_ID" ]; then
  echo 'Selected image is already running. Use verify, not apply/check; preserve the ORIGINAL recovery record.' >&2
  exit 1
fi
mkdir -p backups
RECOVERY_DIR=$(mktemp -d "backups/unbound-pre-october-2026-$(date +%Y%m%d-%H%M%S)-XXXXXX")
chmod 700 "$RECOVERY_DIR"
ROLLBACK="mailcow-unbound-rollback:pre-october-2026-$(date +%Y%m%d%H%M%S)"
docker image tag "$RUNNING_ID" "$ROLLBACK"
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
bash helper-scripts/maintenance/2026-10-unbound-verify.sh
printf '\nRecovery: %s\nRollback: %s\n' "$RECOVERY_DIR" "$ROLLBACK"
echo 'Verify normal mail send/receive and existing Outlook sync before the web stage.'
