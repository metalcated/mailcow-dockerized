# October 29 maintenance handoff

## Verified production checkpoint

The user deployed and checked PHP 8.2.35, Nginx 1.30.6, SOGo 5.12.12,
ClamAV 1.4.6, and Redis 7.4.12 on October 28. Mail/UI and normal attachment
delivery passed. Redis loaded 7,562 keys and PHP/Rspamd connectivity plus the
F2B_CHANNEL subscription recovered. Host vm.overcommit_memory=1 was applied and
persisted separately; no container restart is needed for it.

Production baseline branch: `feature/october-2026-security-backports`,
commit `72055a93`. Do not blindly pull/switch to the last preparation branch.
Each cumulative branch below introduces one stage. Fetch first, advance in
order, and stop for real client/mail validation between stages. No production
SSH, restart, migration, certificate renewal, or firewall changes were made
while preparing these branches.

| Stage | Branch | Scope |
| --- | --- | --- |
| 1 | feature/october-2026-next-unbound | Unbound 1.26.2 image only |
| 2 | feature/october-2026-next-web | Encoding/OAuth hardening; no proxy-header changes |
| 3 | feature/october-2026-next-rspamd | Rspamd 4.2.1 and reviewed compatibility changes |
| 4 | feature/october-2026-next-dockerapi | Docker API 2.12 |
| 5 | feature/october-2026-next-olefy | Olefy 1.15 |
| Hold | no deployment branch | ACME 1.98: new MTA-STS schema dependency |
| Hold | no deployment branch | Watchdog 2.11: assumes absent postfix-tlspol service |

Later branches are not automatically approved for deployment merely because
they are listed here. Read their stage notes for local evidence and blockers.

## Stage 1: Unbound

Pin: `ghcr.io/mailcow/unbound:1.26.2-1@sha256:016bd7056ac86ef3f43ae05d38b7bfa0c59afed69ffac1eab30ea00e0850cb8b`.
This covers the newer [Unbound security releases](https://nlnetlabs.nl/projects/unbound/security-advisories/).
It preserves resolver settings, DNSSEC validation, trust anchors, static IP,
firewall backend, and every other service image. The helper backs up both source
and runtime resolver files before a disconnected candidate configuration check.
No second resolver is started on the production network during preflight.

Tomorrow, start with this one box. It refuses an unexpected checkout, preserves
the generated Postfix/Redis settings by leaving those paths unchanged, and
does not delete untracked backups or customization files. If switching branches
is blocked by local changes, stop and inspect; do not reset or force checkout.

```sh
(
  set -eu
  set -o pipefail
  cd /opt/mailcow-dockerized
  test "$(git branch --show-current)" = 'feature/october-2026-security-backports'
  git status --short --branch
  git fetch origin
  git switch --track origin/feature/october-2026-next-unbound
  bash helper-scripts/maintenance/2026-10-unbound.sh apply
)
```

The helper defaults to `check` without replacement if invoked without `apply`.
After replacement it requires a validated signed answer, expected rejection of
an intentionally broken DNSSEC test domain, and resolution from Postfix and
Rspamd. Public test domains and Internet reachability can themselves fail; a
failed probe needs diagnosis, not disabling DNSSEC. Check normal delivery and
existing Outlook without removing/re-adding working accounts before stage 2.
Docker health may lag direct DNS readiness. Keep the snapshot and recovery tags.

If the image already started but the old short DNSSEC check timed out, update
this SAME branch and use `bash helper-scripts/maintenance/2026-10-unbound.sh verify`.
This mode performs queries/status reads only: no pull, recreation, backup, or
new rollback tag. Do not repeat `apply` after replacement. The helper now refuses
to label the running candidate as a fresh rollback image.

Verification prints complete DNS replies and exit codes. Positive validation
requires NOERROR plus AD. The negative gate allows 15 seconds per query and a
bounded retry, trying the documented test domains `dnssec-failed.org` and
`brokendnssec.net`. It requires a control A answer with checking disabled for
that request only, followed by SERVFAIL with validation enabled. If neither
domain completes that pair, the result stays NOT PASSED, not a silent skip or
an automatic rollback. No DNSSEC setting, firewall rule, or host sysctl changes.
This follows [Cloudflare's DNSSEC diagnosis](https://developers.cloudflare.com/dns/dnssec/troubleshooting/)
and [Ubuntu's guidance](https://ubuntu.com/server/docs/how-to/networking/dnssec-troubleshooting/).

## Stage 2: web hardening

Based on [upstream PR 7426](https://github.com/mailcow/mailcow-dockerized/pull/7426),
adapted to this fork's `debug.js`, not upstream's renamed dashboard. Changes
are limited to log/DNS output encoding, logger JSON flags, and OAuth redirect
termination/missing-user guards. Zonefile exports decode presentation entities
back to their original DNS text. The Nginx client-IP/header change is omitted
because of [DAV/EAS logging regression 7470](https://github.com/mailcow/mailcow-dockerized/issues/7470).
No images, schema, SOGo theme, or mail authentication paths change in this stage.

Switching branches changes bind-mounted web files immediately, so back up the
four files before switching. Run only after the Unbound mail/client checks pass:

```sh
(
  set -eu
  set -o pipefail
  umask 077
  cd /opt/mailcow-dockerized
  test "$(git branch --show-current)" = 'feature/october-2026-next-unbound'
  RECOVERY_DIR=$(mktemp -d backups/web-pre-october-2026-XXXXXX)
  tar -czf "$RECOVERY_DIR/web.tar.gz" data/web/js/site/debug.js data/web/inc/functions.inc.php data/web/inc/ajax/dns_diagnostics.php data/web/oauth/authorize.php
  printf 'Web recovery: %s\n' "$RECOVERY_DIR"
  git switch --track origin/feature/october-2026-next-web
  for FILE in inc/functions.inc.php inc/ajax/dns_diagnostics.php oauth/authorize.php; do
    docker compose exec -T php-fpm-mailcow php -l "/web/$FILE"
  done
  docker compose restart php-fpm-mailcow
  docker compose logs --since=2m --tail=70 php-fpm-mailcow
)
```

Verify admin log tables, DNS diagnostics and zonefile download, OAuth login /
approve / deny / retry / expired-session behavior when configured, quarantine,
fresh SOGo SSO, and normal mail. Hard-refresh the browser for the JS change.
Rollback is switching to the preceding Unbound branch and restarting PHP only;
do not restore SQL or overwrite local Postfix/Redis settings.

## Stage 3: Rspamd

Pin: `ghcr.io/mailcow/rspamd:4.2.1-1@sha256:6e7375761b6234cf6db6d462dc3f68f121401e9e6b75d7889ec0b22a62f64b4c`.
This is a major-version step, not just an operating-system refresh. Includes the
upstream footer fix `ff6329d0`: honor the MIME helper's returned transfer encoding
and tolerate either generated Content header order. Both 3.14.3 and 4.2.1 passed
actual daemon fixtures for plain/UTF-8/quoted-printable footer messages and GTUBE
rejection with disposable Redis/HTTP peers. No production network, data, signing
keys, Docker socket, or host ports were used. DKIM, ClamAV, production policy,
replication, hooks, and Outlook are live gates, not claimed fixture coverage.

```sh
(
  set -eu
  set -o pipefail
  umask 077
  cd /opt/mailcow-dockerized
  test "$(git branch --show-current)" = 'feature/october-2026-next-web'
  RECOVERY_DIR=$(mktemp -d backups/rspamd-source-pre-october-2026-XXXXXX)
  cp -a data/conf/rspamd/lua/rspamd.local.lua "$RECOVERY_DIR/rspamd.local.lua"
  printf 'Pre-switch Lua recovery: %s\n' "$RECOVERY_DIR"
  git switch --track origin/feature/october-2026-next-rspamd
  bash helper-scripts/maintenance/2026-10-rspamd.sh apply
)
```

The helper saves the previous image, Rspamd files/state, and a consistent Redis
RDB before replacement. Rspamd state is an online best-effort archive; the server
snapshot remains the consistent whole-system recovery point. It never flushes
Redis, converts a schema, or automatically restores older data. Disconnected
configtest cannot resolve public fuzzy maps; existing missing custom-map and
timeout-budget warnings must be compared with the baseline, not ignored as new
errors. Stop if `syntax OK` fails. Image rollback uses the saved `RSPAMD_IMAGE`
override; the updated footer Lua was also tested with the older image.

Before advancing: send/receive externally in both directions, include an
attachment and configured footer, inspect the delivered MIME text and DKIM
result, verify quarantine/release and normal policy, and reconnect a working
Outlook account without deleting it. Do not bypass antivirus or weaken spam
policy to get a green result. A failed test stops this stage.

## Stage 4: Docker API

Pin: `ghcr.io/mailcow/dockerapi:2.12@sha256:90d6f26eb3fb8a47696d8719b71e9159849d5b49e4ce3e48967f2dfb5a8df55a`.
Actual 2.11/2.12 `modules/DockerApi.py` and certificate-generation entrypoint
hashes match. The newer list endpoint supports optional `all=true`; its default
still returns running containers. Offline fixtures on both images verified
list/detail/error responses, existing reload-method names, stubbed HTTP and
MC_CHANNEL dispatch, and the packaged event-loop setting. They do not execute
actions or open a real Docker socket. No new host ports or access controls are
introduced. The production control plane can restart/reload containers, so it
still requires its own live check even though mail images remain unchanged.

```sh
(
  set -eu
  set -o pipefail
  cd /opt/mailcow-dockerized
  test "$(git branch --show-current)" = 'feature/october-2026-next-rspamd'
  git switch --track origin/feature/october-2026-next-dockerapi
  bash helper-scripts/maintenance/2026-10-dockerapi.sh apply
)
```

The helper keeps an old-image tag, runs the offline fixture first, replaces only
Docker API, requires the previous MC_CHANNEL subscription count to recover, and
checks the actual PHP-to-API container-list path without printing container
environment variables or issuing actions. Check the admin status/container
views and watchdog recovery. Do not restart working Dovecot/Postfix to prove an
API command. Rollback uses the saved `DOCKERAPI_IMAGE` override. Certificate
reload actions were stubbed locally, not run against production.

## Held work

ACME 1.98 is downloaded/reviewed but NOT enabled: its actual `/srv/acme.sh`
queries `mta_sts` and joins it with `alias_domain`, while this fork's schema does
not provide that table. Query failure is nonfatal in the image, but changes SAN
discovery and logs SQL errors. Certificate acquisition can also reload Nginx,
Dovecot, and Postfix. Keep ACME 1.92 until we agree on a narrowly tested legacy
schema adaptation and back up certificate/account keys. Do not force renewal,
add schema, or replace working certificate names as part of these commands.

Watchdog 2.11 is downloaded/reviewed but NOT enabled: it unconditionally starts
`postfix-tlspol_checks` for a service absent from this deployment. Keep 2.07 until
an explicit compatibility gate is reviewed and tested. Do not add postfix-tlspol
or migrate the mail stack to satisfy a monitoring image.

Do not update Postfix, introduce postfix-tlspol, migrate spamalias schema, replace
the direct-SQL Dovecot authentication path, switch UFW/iptables backends, merge
upstream master, or merge into legacy automatically. Those need separate
approval and live validation. Fresh New Outlook onboarding remains unverified.
Floating-tag package/digest and host OS support audits remain separate; this
handoff is not an assertion that every CVE has been closed.
