#!/usr/bin/env bash
set -euo pipefail
umask 077
export REDIS_CMDLINE=true MAILCOW_HOSTNAME=mail.example.test
export PATH=/tmp/fixture-bin:$PATH
mkdir -p /tmp/fixture-bin /var/www/acme /var/lib/acme/acme
openssl genrsa -out /var/lib/acme/acme/key.pem 2048 2>/dev/null
openssl genrsa -out /var/lib/acme/acme/account.pem 2048 2>/dev/null
KEY_HASH=$(sha256sum /var/lib/acme/acme/key.pem)

# These stand-ins cannot contact a CA, Redis, or DNS even if the fixture regresses.
printf '#!/bin/sh\nexit 0\n' > /tmp/fixture-bin/dig
printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> /tmp/redis-calls\n' > /tmp/fixture-bin/redis-cli
cat > /tmp/fixture-bin/acme-tiny <<'STUB'
#!/bin/bash
echo called >> /tmp/ca-calls
[[ ${FIXTURE_FAIL:-n} == y ]] && exit 7
while [[ $# -gt 0 ]]; do
  case "$1" in --csr) CSR=$2; shift;; esac
  shift
done
KEY=/var/lib/acme/acme/key.pem
if [[ ${FIXTURE_MISMATCH:-n} == y ]]; then
  openssl genrsa -out /tmp/wrong-key.pem 2048 2>/dev/null
  KEY=/tmp/wrong-key.pem
fi
openssl x509 -req -in "$CSR" -signkey "$KEY" -days 90 2>/dev/null
STUB
chmod 700 /tmp/fixture-bin/*

obtain() {
  local status=0
  DOMAINS="$1" bash /srv/obtain-certificate.sh "${3:-rsa}" 5>/dev/null > /tmp/acme-output 2>&1 || status=$?
  if [[ $status != "$2" ]]; then
    cat /tmp/acme-output
    echo "Unexpected obtain status: $status, expected $2" >&2
    exit 1
  fi
}

obtain 'mail.example.test autodiscover.example.test' 0
CERT=/var/lib/acme/mail.example.test/cert.pem
FIRST=$(sha256sum "$CERT")
test "$(cat /var/lib/acme/mail.example.test/domains)" = 'mail.example.test autodiscover.example.test'
openssl req -in /var/lib/acme/mail.example.test/acme.csr -noout -text | grep -q 'DNS:autodiscover.example.test'
obtain 'mail.example.test autodiscover.example.test' 2
test "$(wc -l < /tmp/ca-calls)" -eq 1
test "$FIRST" = "$(sha256sum "$CERT")"
touch /var/lib/acme/force_renew
obtain 'mail.example.test autodiscover.example.test' 1
test -s /var/lib/acme/backups/mail.example.test/*/cert.pem
rm /var/lib/acme/force_renew
openssl x509 -req -in /var/lib/acme/mail.example.test/acme.csr \
  -signkey /var/lib/acme/mail.example.test/key.pem -days 1 -out "$CERT" 2>/dev/null
obtain 'mail.example.test autodiscover.example.test' 1
obtain 'mail.example.test autoconfig.example.test' 1
test "$(cat /var/lib/acme/mail.example.test/domains)" = 'mail.example.test autoconfig.example.test'

LAST=$(sha256sum "$CERT")
export FIXTURE_MISMATCH=y
obtain 'mail.example.test changed.example.test' 4
test "$LAST" = "$(sha256sum "$CERT")"
test "$(cat /var/lib/acme/mail.example.test/domains)" = 'mail.example.test autoconfig.example.test'
export FIXTURE_MISMATCH=n FIXTURE_FAIL=y
obtain 'mail.example.test changed.example.test' 239
grep -q 'SET ACME_FAIL_TIME' /tmp/redis-calls
test "$LAST" = "$(sha256sum "$CERT")"
export FIXTURE_FAIL=n
obtain 'mail.example.test' 5 ecdsa
test "$KEY_HASH" = "$(sha256sum /var/lib/acme/acme/key.pem)"
acme_help=$(/usr/bin/acme-tiny --help)
grep -q -- '--contact' <<< "$acme_help"
echo 'ACME legacy creation, retry, renewal, SAN change, key mismatch, CA failure, and key preservation passed (offline CA stand-in).'
