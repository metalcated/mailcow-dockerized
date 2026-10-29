#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
test "$(git branch --show-current)" = 'feature/october-2026-next-dockerapi'
MODE=${1:-check}
test "$MODE" = check || test "$MODE" = apply
docker compose config --quiet
TARGET=$(docker compose config --images dockerapi-mailcow | awk '/^ghcr[.]io\/mailcow\/dockerapi[:@]/')
test "$TARGET" = 'ghcr.io/mailcow/dockerapi:2.12@sha256:90d6f26eb3fb8a47696d8719b71e9159849d5b49e4ce3e48967f2dfb5a8df55a'
CONTAINER=$(docker compose ps -q dockerapi-mailcow)
test -n "$CONTAINER"
mkdir -p backups
RECOVERY_DIR=$(mktemp -d "backups/dockerapi-pre-october-2026-$(date +%Y%m%d-%H%M%S)-XXXXXX")
ROLLBACK="mailcow-dockerapi-rollback:pre-october-2026-$(date +%Y%m%d%H%M%S)"
docker image tag "$(docker inspect --format '{{.Image}}' "$CONTAINER")" "$ROLLBACK"
printf '%s\n' "$ROLLBACK" > "$RECOVERY_DIR/rollback-image.txt"
cp -a docker-compose.yml "$RECOVERY_DIR/"
subscriptions() {
  docker compose exec -T redis-mailcow sh -ec 'export REDISCLI_AUTH="$REDISPASS"; redis-cli -e --raw PUBSUB NUMSUB MC_CHANNEL' | tail -n 1 | tr -d '\r'
}
BEFORE=$(subscriptions)
test "$BEFORE" -ge 1
printf '\nRecovery: %s\nRollback: %s\nMC_CHANNEL subscriptions before: %s\n' "$RECOVERY_DIR" "$ROLLBACK" "$BEFORE"
trap 'STATUS=$?; if [ "$STATUS" -ne 0 ]; then printf "\nStopped. Image rollback: DOCKERAPI_IMAGE=%q docker compose up -d --no-deps --force-recreate dockerapi-mailcow\n" "$ROLLBACK"; fi' EXIT
docker pull "$TARGET"
docker run --rm --pull=never --network=none \
  --mount "type=bind,src=$PWD/helper-scripts/tests/dockerapi_fixture.py,dst=/fixture.py,readonly" \
  --entrypoint python "$TARGET" /fixture.py
if [ "$MODE" = check ]; then
  echo 'Offline preflight passed. No host Docker socket mounted and no service replaced.'
  exit 0
fi
docker compose up -d --no-deps --force-recreate dockerapi-mailcow
READY=0
for ATTEMPT in $(seq 1 40); do
  if [ "$(subscriptions)" -ge "$BEFORE" ]; then READY=1; break; fi
  sleep 2
done
test "$READY" -eq 1
docker compose exec -T php-fpm-mailcow php -r '
  $c=curl_init("https://dockerapi:443/containers/json");
  curl_setopt_array($c,[CURLOPT_RETURNTRANSFER=>true,CURLOPT_SSL_VERIFYPEER=>false,CURLOPT_SSL_VERIFYHOST=>false,CURLOPT_TIMEOUT=>15]);
  $body=curl_exec($c); $code=curl_getinfo($c,CURLINFO_HTTP_CODE); $items=json_decode($body,true);
  if ($code!==200 || !is_array($items) || isset($items["type"]) || count($items)<1) {fwrite(STDERR,"Docker API read-only query failed\n");exit(1);}
  foreach ($items as $id=>$item) {if (!isset($item["Id"],$item["Config"]["Labels"],$item["State"])) exit(1);}
  echo "PHP to Docker API: ".count($items)." container records; no actions requested\n";
'
docker compose logs --since=3m --tail=70 dockerapi-mailcow watchdog-mailcow
docker compose ps dockerapi-mailcow php-fpm-mailcow watchdog-mailcow dovecot-mailcow postfix-mailcow
printf '\nRecovery: %s\nRollback: %s\n' "$RECOVERY_DIR" "$ROLLBACK"
echo 'Check admin container/status views and existing mail. Do not restart mail services just to test this API.'
