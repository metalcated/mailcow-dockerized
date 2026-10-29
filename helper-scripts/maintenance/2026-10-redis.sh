#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
test "$(git branch --show-current)" = 'feature/october-2026-security-backports'
docker compose config --quiet

EXPECTED='redis:7.4.12-alpine@sha256:338fbfc036dc5517ac0b04d6de21521085935336e565f223406180e9d84166e2'
TARGET=$(docker compose config --images redis-mailcow | awk '/^redis[:@]/')
test "$TARGET" = "$EXPECTED"
CONTAINER=$(docker compose ps -q redis-mailcow)
test -n "$CONTAINER"

redis_command() {
  docker compose exec -T redis-mailcow sh -ec \
    'export REDISCLI_AUTH="$REDISPASS"; exec redis-cli -e --raw "$@"' sh "$@"
}

# Do not apply a standalone/RDB procedure to a replica, cluster, or AOF setup.
test "$(redis_command PING)" = PONG
VERSION=$(redis_command INFO server | tr -d '\r' | awk -F: '$1 == "redis_version" {print $2}')
case "$VERSION" in 7.4.*) ;; *) echo 'Unexpected Redis series; stop for review'; exit 1;; esac
redis_command INFO replication | tr -d '\r' | grep -qx 'role:master'
redis_command INFO cluster | tr -d '\r' | grep -qx 'cluster_enabled:0'
test "$(redis_command CONFIG GET appendonly | tail -n 1)" = no
test "$(redis_command CONFIG GET dir | tail -n 1)" = /data
test "$(redis_command CONFIG GET dbfilename | tail -n 1)" = dump.rdb
docker compose exec -T php-fpm-mailcow sh -ec 'test -z "${REDIS_SLAVEOF_IP:-}"'
SUBSCRIBERS=$(redis_command PUBSUB NUMSUB F2B_CHANNEL | tail -n 1)
test "$SUBSCRIBERS" -ge 1

mkdir -p backups
RECOVERY_DIR=$(mktemp -d "backups/redis-pre-october-2026-$(date +%Y%m%d-%H%M%S)-XXXXXX")
chmod 700 "$RECOVERY_DIR"
ROLLBACK="mailcow-redis-rollback:pre-october-2026-$(date +%Y%m%d%H%M%S)"
docker image tag "$(docker inspect --format '{{.Image}}' "$CONTAINER")" "$ROLLBACK"
printf '%s\n' "$ROLLBACK" > "$RECOVERY_DIR/rollback-image.txt"
cp -a data/conf/redis "$RECOVERY_DIR/redis-conf"
redis_command INFO keyspace > "$RECOVERY_DIR/keyspace-before.txt"
printf '\nRecovery: %s\nRollback: %s\n' "$RECOVERY_DIR" "$ROLLBACK"
trap 'STATUS=$?; if [ "$STATUS" -ne 0 ]; then printf "\nStopped. Preserve %s; do not flush Redis or restore a snapshot automatically.\n" "$RECOVERY_DIR"; printf "Image-only rollback: REDIS_IMAGE=%q docker compose up -d --no-deps --force-recreate --timeout 120 redis-mailcow\n" "$ROLLBACK"; fi' EXIT

docker pull "$TARGET"
# Export a consistent online snapshot without printing passwords or key contents.
docker compose exec -T redis-mailcow sh -ec \
  'export REDISCLI_AUTH="$REDISPASS"; exec timeout 180 redis-cli --rdb -' > "$RECOVERY_DIR/dump.rdb"
test -s "$RECOVERY_DIR/dump.rdb"
docker run --rm --pull=never --network=none \
  --mount "type=bind,src=$PWD/$RECOVERY_DIR,dst=/backup,readonly" \
  --entrypoint redis-check-rdb "$TARGET" /backup/dump.rdb > "$RECOVERY_DIR/rdb-check.txt"
docker run --rm --pull=never --network=none --entrypoint redis-server "$TARGET" --version

docker compose up -d --no-deps --force-recreate --timeout 120 redis-mailcow
READY=0
for ATTEMPT in $(seq 1 60); do
  if [ "$(redis_command PING 2>/dev/null || true)" = PONG ]; then READY=1; break; fi
  sleep 1
done
docker compose logs --since=3m --tail=55 redis-mailcow
test "$READY" -eq 1
redis_command INFO server | tr -d '\r' | grep -qx 'redis_version:7.4.12'
redis_command INFO persistence | tr -d '\r' | grep -qx 'rdb_last_bgsave_status:ok'
redis_command INFO keyspace > "$RECOVERY_DIR/keyspace-after.txt"

docker compose exec -T php-fpm-mailcow php -r '$r=new Redis(); $r->connect("redis-mailcow",6379,3); if (!$r->auth(getenv("REDISPASS")) || !$r->ping()) {exit(1);} echo "PHP to Redis: PONG\n";'
docker compose exec -T rspamd-mailcow sh -ec 'export REDISCLI_AUTH="$REDISPASS"; test "$(redis-cli -e --raw -h redis-mailcow PING)" = PONG; echo "Rspamd to Redis: PONG"'

# Netfilter can reconnect or restart automatically after its pub/sub socket drops.
SUBSCRIPTIONS_READY=0
for ATTEMPT in $(seq 1 60); do
  CURRENT=$(redis_command PUBSUB NUMSUB F2B_CHANNEL | tail -n 1)
  if [ "$CURRENT" -ge "$SUBSCRIBERS" ]; then SUBSCRIPTIONS_READY=1; break; fi
  sleep 1
done
test "$SUBSCRIPTIONS_READY" -eq 1
printf 'F2B_CHANNEL subscribers: %s (before: %s)\n' "$CURRENT" "$SUBSCRIBERS"
docker compose ps redis-mailcow netfilter-mailcow rspamd-mailcow php-fpm-mailcow dovecot-mailcow postfix-mailcow
printf '\nRecovery: %s\nRollback: %s\n' "$RECOVERY_DIR" "$ROLLBACK"
echo 'Now verify fresh Mailcow/SOGo access and normal mail send/receive.'
