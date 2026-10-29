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
| 4 | feature/october-2026-next-acme | ACME 1.98 |
| 5 | feature/october-2026-next-watchdog | Watchdog 2.11 |
| 6 | feature/october-2026-next-dockerapi | Docker API 2.12 |
| 7 | feature/october-2026-next-olefy | Olefy 1.15 |

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

## Held work

Do not update Postfix, introduce postfix-tlspol, migrate spamalias schema, replace
the direct-SQL Dovecot authentication path, switch UFW/iptables backends, merge
upstream master, or merge into legacy automatically. Those need separate
approval and live validation. Fresh New Outlook onboarding remains unverified.
Floating-tag package/digest and host OS support audits remain separate; this
handoff is not an assertion that every CVE has been closed.
