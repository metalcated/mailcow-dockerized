#!/usr/bin/env bash
set -euo pipefail
umask 077
EXPECTED=6330df1749a112aa9f510e500d3e717b3d089fc30818eaa1e2a275084d69dcf7
ACTUAL=$(sha256sum /watchdog.sh | awk '{print $1}')
if [[ $ACTUAL != "$EXPECTED" ]]; then
  echo 'Unsupported watchdog script; refusing to adapt an unreviewed image.' >&2
  exit 1
fi
BLOCK=$(cat <<'WORKER'
(
while true; do
  if ! postfix-tlspol_checks; then
    log_msg "Postfix TLS Policy hit error limit"
    echo postfix-tlspol-mailcow > /tmp/com_pipe
  fi
done
) &
PID=$!
echo "Spawned postfix-tlspol_checks with PID ${PID}"
BACKGROUND_TASKS+=(${PID})
WORKER
)
SOURCE=$(</watchdog.sh)
test "$SOURCE" != "${SOURCE/"$BLOCK"/}"
REST=${SOURCE#*"$BLOCK"}
test "$REST" = "${REST/"$BLOCK"/}"
REPLACEMENT=$(printf 'if [[ ${WATCHDOG_POSTFIX_TLSPOL:-n} == y ]]; then\n%s\nfi' "$BLOCK")
printf '%s\n\n' "${SOURCE/"$BLOCK"/"$REPLACEMENT"}" > /tmp/watchdog-legacy.sh
chmod 700 /tmp/watchdog-legacy.sh
bash -n /tmp/watchdog-legacy.sh
case "${1:-run}" in
  --check) echo 'Watchdog adapter verified; no health workers or restart actions started.' ;;
  --print) cat /tmp/watchdog-legacy.sh ;;
  run) export DEV_MODE=n; exec bash /tmp/watchdog-legacy.sh ;;
  *) echo 'Expected run, --check, or --print.' >&2; exit 2 ;;
esac
