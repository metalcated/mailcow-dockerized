# October 29 maintenance handoff

## October 29 deployed checkpoint

The user completed the staged deployment and reported "Looks good." The final
server output confirms `feature/october-2026-next-olefy`, Rspamd 4.2.1, Docker API
2.12, and Olefy 1.15. The earlier accepted PHP/Nginx/SOGo/ClamAV/Redis/Unbound
stages remain the recorded baseline. Do not replay the deployment boxes below
or create fresh rollback tags from the now-updated services.

| Component | Recorded deployed version |
| --- | --- |
| PHP-FPM | 8.2.35-1 |
| Nginx | 1.30.6-1 |
| SOGo | 5.12.12-1 |
| ClamAV | 1.4.6-1 |
| Redis | 7.4.12-alpine |
| Unbound | 1.26.2-1 |
| Rspamd | 4.2.1-1 |
| Docker API | 2.12 |
| Olefy | 1.15 |

Live evidence from the user's output:

- Rspamd was running 4.2.1 and the user passed the attachment mail gate. It was
  still running two hours later in the final status output.
- Before Docker API replacement, MC_CHANNEL had zero subscribers. Restarting
  only the existing 2.11 service restored one subscriber. The 2.12 helper then
  passed its subscription gate and PHP read-only API query (22 container
  records). The user passed the admin status/container-view gate.
- Olefy 1.15 passed PING, intentional minimum-size rejection, and a harmless
  synthetic OpenXML scan in the live service. Rspamd-to-Olefy returned PONG.
  These fixture results do not establish malicious-macro detection or replace
  real client acceptance; no independent browser/Outlook inspection was made.
- Postfix 1.80 and Dovecot 2.3.21.1-2 still reported two months of uptime in the
  final output. No schema/authentication/proxy/firewall migration was included.

Retain these original recovery records and the corresponding rollback images:

| Service | Recovery directory under /opt/mailcow-dockerized | Rollback image |
| --- | --- | --- |
| Rspamd | backups/rspamd-pre-october-2026-20261029-143935-AtQ2FK | mailcow-rspamd-rollback:pre-october-2026-20261029143935 |
| Docker API | backups/dockerapi-pre-october-2026-20261029-163042-miVJFn | mailcow-dockerapi-rollback:pre-october-2026-20261029163042 |
| Olefy | backups/olefy-pre-october-2026-20261029-163122-1EW5Gi | mailcow-olefy-rollback:pre-october-2026-20261029163122 |

The attachment's five-byte Olefy error is the expected negative fixture. The
single watchdog "Cannot find dockerapi-mailcow" message coincides with service
replacement; the subsequent successful API read confirms API availability.
Olefy's Python syntax/deprecation warnings did not prevent the live probes.
Rspamd fuzzy-server timeouts, an IPv6 "Network is unreachable" map fetch, and
slow external DNS rules remain follow-up items, not silently passed checks.
Mail was processed in that same log; external-check coverage is not fully
verified by successful delivery alone.

Docker API's background listener can exit on a Redis connection error in both
2.11 and 2.12; this was reproduced offline with a synthetic exception and no
Docker actions. A stale subscription following Redis maintenance is a plausible
cause of the zero baseline, not proven historical causation. After future Redis
maintenance, verify MC_CHANNEL recovery; do not assume HTTP readiness proves
the listener is alive. No automatic restart or reconnect-code change is added.

The server remains on the deployed Olefy branch. This documentation/permissions
follow-up is on `feature/october-2026-checkout-permissions`; it changes no image
pins or runtime source. Nothing was merged into legacy/master. ACME/watchdog,
Postfix/schema changes, fresh New Outlook onboarding, and the broader component
and host vulnerability audit remain outside this completed deployment sequence.

## October 28 baseline

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

## Preparation evidence

Compared against upstream master `55982ac7` and the accepted fork checkpoint
`72055a93`. Original stage commits: Unbound `29286ab5`, web `be4417db`, Rspamd
`cb14bf54`, and Docker API `ef6bb1c2`; the final Olefy branch contains this full
handoff. These are cumulative preparation branches, not merges into production.

Local validation uses the workstation's ARM64 Docker runtime and downloaded
multi-architecture image pins. The morning helpers rerun candidate checks on the
actual server before replacement. Seventy-four automated checks cover image-only
Compose parity, explicit rollback overrides, preserved SQL/auth/proxy/theme/
firewall files, shell/PHP syntax, real service fixtures, web/OAuth failure paths,
and the reasons for holding ACME/watchdog. Public DNSSEC resolution, existing
Outlook behavior, production hooks, real signing keys, certificate renewal,
and host Docker API negotiation require server/client validation. Passing a
local fixture does not establish those live outcomes.

October 29 server evidence: Unbound 1.26.2 reported healthy/running and validated
Cloudflare A and root DNSKEY answers (AD). The first short negative probe timed
out. After pulling fix `e81233ff`, verification passed at 12:50 EDT: the same
`dnssec-failed.org` A query returned NOERROR with checking disabled and SERVFAIL
with validation enabled; gmail.com resolved from Postfix and Rspamd; and
fuzzy.mailcow.email returned NOERROR with AD. The resolver was healthy after
11 minutes of uptime. No further recreation was needed for verification.
Real mail and existing Outlook acceptance after this DNS stage still require
the user's confirmation before the web stage. Fix `e81233ff` is merged through
all five preparation branches without changing any image/configuration pin.

October 29 web recovery: the user confirmed the admin UI works after restoring
mode 0644 on the four checked-out web source files. The deployment block left
umask 077 active during Git checkout, creating owner-only files that the PHP
www-data worker could not read. This was reproduced locally with real Git.
All Git updates below now use a scoped umask 022; private backup creation keeps
umask 077. Syntax/readability checks run as www-data, not container root.
Do not apply recursive chmod/chown to the checkout: local configuration,
credentials, and recovery archives must retain their restricted permissions.

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
  git merge-base --is-ancestor HEAD origin/feature/october-2026-next-unbound
  (umask 022; git switch --track origin/feature/october-2026-next-unbound)
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
  git fetch origin
  git merge-base --is-ancestor HEAD origin/feature/october-2026-next-web
  (umask 022; git switch --track origin/feature/october-2026-next-web)
  for FILE in inc/functions.inc.php inc/ajax/dns_diagnostics.php oauth/authorize.php; do
    docker compose exec -T --user www-data php-fpm-mailcow php -l "/web/$FILE"
  done
  docker compose exec -T --user www-data php-fpm-mailcow php -r 'exit(is_readable("/web/js/site/debug.js") ? 0 : 1);'
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
This is a [major-version step](https://docs.rspamd.com/changelog/4.2.1/), not just an operating-system refresh. Includes the
upstream footer fix `ff6329d0`: honor the MIME helper's returned transfer encoding
and tolerate either generated Content header order. Both 3.14.3 and 4.2.1 passed
actual daemon fixtures for plain/UTF-8/quoted-printable footer messages and GTUBE
rejection with disposable Redis/HTTP peers. The final cumulative test also
confirmed both engines detect a harmless custom signature through real ClamAV
and can run the exact Olefy connectivity probe. No production network, data, signing
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
  git fetch origin
  git merge-base --is-ancestor HEAD origin/feature/october-2026-next-rspamd
  (umask 022; git switch --track origin/feature/october-2026-next-rspamd)
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
list/detail/error responses, existing reload-method names, stubbed route-handler and
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
  git fetch origin
  git merge-base --is-ancestor HEAD origin/feature/october-2026-next-dockerapi
  (umask 022; git switch --track origin/feature/october-2026-next-dockerapi)
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

## Stage 5: Olefy

Pin: `ghcr.io/mailcow/olefy:1.15@sha256:cec980cddf162594f5f1a7b575ae95c0f17f0c42febcfac94a478eca2d2bfd9e`.
Retains port 10055, the configured Python/olevba paths, minimum size, scanner
policy, and Rspamd integration. Old/new images passed actual socket PING,
minimum-size rejection, and a harmless synthetic OpenXML document scan using
the real packaged oletools. No external network or production attachments were
used. Macro-malware detection is not asserted from a clean-document fixture.

```sh
(
  set -eu
  set -o pipefail
  cd /opt/mailcow-dockerized
  test "$(git branch --show-current)" = 'feature/october-2026-next-dockerapi'
  git fetch origin
  git merge-base --is-ancestor HEAD origin/feature/october-2026-next-olefy
  (umask 022; git switch --track origin/feature/october-2026-next-olefy)
  bash helper-scripts/maintenance/2026-10-olefy.sh apply
)
```

The helper tags the previous image, tests a disconnected scanner first,
replaces only Olefy, repeats harmless scanner checks, and checks reachability
from the production Rspamd container. Send/receive a normal Office attachment
and check Rspamd for scanner failures. Do not disable scanning to clear a failure.
Rollback uses the saved `OLEFY_IMAGE` override; there is no data-volume migration.

## Stop and recovery rules

Run one stage, inspect output, then confirm the corresponding live paths before
running the next box. A shell exiting early means STOP, not "continue anyway."
The helpers default to `check`; `apply` is explicit. No full-stack `up`, `down`,
volume deletion, forced branch switch, schema migration, or firewall adjustment
belongs in this sequence. Keep the snapshot, recovery directories, and old
image tags until the entire maintenance cycle is accepted.

An image override in a rollback command is temporary for that invocation.
Subsequent ordinary Compose commands would select the branch's newer default
again. After rollback, stop and document the chosen recovery state before any
other deployment command. For a durable return to the preceding stage, switch
back to its branch and recreate only the affected service after inspecting
local changes. Never restore SQL/Redis or untar state blindly over live data.

If a box stops after switching branches but before replacement, diagnose the
error and rerun the stage helper on that same branch, rather than rerunning the
whole branch-switch box. After replacement, retain the ORIGINAL recovery record:
a new helper run tags whichever image is running then, which may already be the
candidate and is not a replacement for the original rollback image. Do not
repeat `apply` to hide a failed post-update check.

The web stage rolls back by switching to the Unbound stage and restarting PHP.
Source rollback for Rspamd uses the pre-switch Lua copy or the web-stage branch;
the newer footer Lua was also tested with 3.14.3. A complete VM snapshot restore
would discard mail received since the snapshot; do not use it as an automatic
fallback while the mail server is receiving new messages.

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
