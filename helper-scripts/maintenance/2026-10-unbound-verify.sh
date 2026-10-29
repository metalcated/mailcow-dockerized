#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

query() {
  printf '\n=== DNS query: %s ===\n' "$*"
  if DNS_REPLY=$(docker compose exec -T unbound-mailcow dig @127.0.0.1 "$@" 2>&1); then
    DNS_RC=0
  else
    DNS_RC=$?
  fi
  printf '%s\nExit code: %s\n' "$DNS_REPLY" "$DNS_RC"
}

status_is() {
  [ "$DNS_RC" -eq 0 ] && grep -Eq "^;; ->>HEADER<<-.* status: $1," <<< "$DNS_REPLY"
}

PASS=1
SIGNED_OK=0
for ATTEMPT in 1 2 3; do
  query cloudflare.com A +dnssec +time=5 +tries=1
  if status_is NOERROR && grep -Eq '^;; flags:.*[[:space:]]ad[;[:space:]]' <<< "$DNS_REPLY"; then
    SIGNED_OK=1
    echo 'PASS: signed answer validated (AD flag).'
    break
  fi
  if [ "$ATTEMPT" -lt 3 ]; then sleep 2; fi
done
if [ "$SIGNED_OK" -ne 1 ]; then
  echo 'NOT PASSED: a validated positive answer was not obtained.' >&2
  PASS=0
fi

# A timeout alone is not evidence of rejecting bogus signatures. Require an A
# answer with checking disabled, followed by SERVFAIL with validation enabled.
REJECT_OK=0
for DOMAIN in dnssec-failed.org brokendnssec.net; do
  query "$DOMAIN" A +dnssec +cdflag +time=15 +tries=1
  if ! status_is NOERROR || ! grep -Eq '^[^;[:space:]]+[[:space:]]+[0-9]+[[:space:]]+IN[[:space:]]+A[[:space:]]+' <<< "$DNS_REPLY"; then
    printf 'INCONCLUSIVE: %s did not provide the control A answer; trying the other documented test domain.\n' "$DOMAIN" >&2
    continue
  fi
  for ATTEMPT in 1 2; do
    query "$DOMAIN" A +dnssec +time=15 +tries=1
    if status_is SERVFAIL; then
      REJECT_OK=1
      printf 'PASS: %s resolves with checking disabled and is rejected with validation enabled.\n' "$DOMAIN"
      break
    fi
    if [ "$DNS_RC" -eq 0 ]; then break; fi
    echo 'No completed response; retrying this query once without changing resolver settings.' >&2
  done
  if [ "$REJECT_OK" -eq 1 ]; then break; fi
done
if [ "$REJECT_OK" -ne 1 ]; then
  echo 'NOT PASSED: negative DNSSEC verification remains inconclusive or failed. A timeout does not count as rejection; keep the current service/recovery record and inspect the responses above.' >&2
  PASS=0
fi

for SERVICE in postfix-mailcow rspamd-mailcow; do
  printf '\n=== DNS lookup from %s ===\n' "$SERVICE"
  if docker compose exec -T "$SERVICE" getent ahostsv4 gmail.com; then
    printf 'PASS: %s resolved gmail.com.\n' "$SERVICE"
  else
    printf 'NOT PASSED: %s DNS lookup failed.\n' "$SERVICE" >&2
    PASS=0
  fi
done
docker compose ps unbound-mailcow postfix-mailcow rspamd-mailcow dovecot-mailcow
docker compose logs --since=4m --tail=70 unbound-mailcow
if [ "$PASS" -ne 1 ]; then exit 1; fi
echo 'Unbound DNS verification passed. Verify real mail and existing Outlook before advancing.'
