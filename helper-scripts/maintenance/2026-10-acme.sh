#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
test "$(git branch --show-current)" = feature/october-2026-acme-legacy-compat
MODE=${1:-check}
test "$MODE" = check || test "$MODE" = apply
docker compose config --quiet
TARGET=$(docker compose config --images acme-mailcow | awk '/^ghcr[.]io\/mailcow\/acme[:@]/')
test "$TARGET" = 'ghcr.io/mailcow/acme:1.98@sha256:ebbd0e6a7d5313189f847d0d6219507a693f6d77d257c1671ebab9656680a5ba'
CONTAINER=$(docker compose ps -q acme-mailcow)
test -n "$CONTAINER"
docker pull "$TARGET"
MOUNTS=()
for NAME in acme.sh functions.sh obtain-certificate.sh; do
  MOUNTS+=(--mount "type=bind,src=$PWD/data/Dockerfiles/acme/$NAME,dst=/srv/$NAME,readonly")
done
docker run --rm --pull=never --network=none "${MOUNTS[@]}" \
  --mount "type=bind,src=$PWD/helper-scripts/tests/acme_legacy_fixture.sh,dst=/fixture.sh,readonly" \
  --entrypoint bash "$TARGET" /fixture.sh

# Do not turn an image update into an unplanned renewal or key regeneration.
test ! -e data/assets/ssl/force_renew
test -s data/assets/ssl/acme/account.pem
test -s data/assets/ssl/acme/key.pem
test -s data/assets/ssl/cert.pem
test -s data/assets/ssl/key.pem
openssl x509 -checkend 2592000 -noout -in data/assets/ssl/cert.pem
cmp <(openssl x509 -in data/assets/ssl/cert.pem -pubkey -noout) \
    <(openssl pkey -in data/assets/ssl/key.pem -pubout)
COUNT=0
for DOMAINS in data/assets/ssl/*/domains; do
  test -f "$DOMAINS" || continue
  DIR=${DOMAINS%/domains}
  test -s "$DIR/cert.pem" && test -s "$DIR/key.pem" && test -s "$DOMAINS"
  openssl x509 -checkend 2592000 -noout -in "$DIR/cert.pem"
  cmp <(openssl x509 -in "$DIR/cert.pem" -pubkey -noout) \
      <(openssl pkey -in "$DIR/key.pem" -pubout)
  COUNT=$((COUNT + 1))
done
test "$COUNT" -gt 0
printf 'Existing managed certificates checked: %s; no force-renew marker.\n' "$COUNT"
openssl x509 -in data/assets/ssl/cert.pem -noout -enddate -fingerprint -sha256
if [ "$MODE" = check ]; then
  echo 'Offline ACME preflight passed; production ACME and certificates unchanged.'
  exit 0
fi
mkdir -p backups
RECOVERY_DIR=$(mktemp -d "backups/acme-pre-october-2026-$(date +%Y%m%d-%H%M%S)-XXXXXX")
ROLLBACK="mailcow-acme-rollback:pre-october-2026-$(date +%Y%m%d%H%M%S)"
docker image tag "$(docker inspect --format '{{.Image}}' "$CONTAINER")" "$ROLLBACK"
printf '%s\n' "$ROLLBACK" > "$RECOVERY_DIR/rollback-image.txt"
cp -a docker-compose.yml "$RECOVERY_DIR/"
printf '\nRecovery: %s\nRollback: %s\n' "$RECOVERY_DIR" "$ROLLBACK"
trap 'STATUS=$?; if [ "$STATUS" -ne 0 ]; then printf "\nStopped. Restore only the ACME image with:\nACME_IMAGE=%q docker compose up -d --no-deps --force-recreate acme-mailcow\nDo not restore certificates over newer renewals without review.\n" "$ROLLBACK"; fi' EXIT
docker compose stop acme-mailcow
cp -a data/assets/ssl "$RECOVERY_DIR/ssl"
test ! -e data/assets/ssl/force_renew
openssl x509 -checkend 2592000 -noout -in data/assets/ssl/cert.pem
docker compose up -d --no-deps --force-recreate acme-mailcow
sleep 5
test "$(docker inspect --format '{{.State.Running}}' "$(docker compose ps -q acme-mailcow)")" = true
for NAME in acme.sh functions.sh obtain-certificate.sh; do
  EXPECTED=$(sha256sum "data/Dockerfiles/acme/$NAME" | awk '{print $1}')
  ACTUAL=$(docker compose exec -T acme-mailcow sha256sum "/srv/$NAME" | awk '{print $1}')
  test "$EXPECTED" = "$ACTUAL"
done
docker compose ps acme-mailcow nginx-mailcow dovecot-mailcow postfix-mailcow
printf '\nRecovery: %s\nRollback: %s\n' "$RECOVERY_DIR" "$ROLLBACK"
echo 'Inspect ACME logs and certificate expiry; normal renewal can reload mail services. No renewal was forced.'
