# October watchdog compatibility stage

Prepared, not deployed. Branch: `feature/october-2026-watchdog-legacy-compat`.
Parent: `c99fa35d`, the separate ACME compatibility stage. Deploy and accept ACME first; switching branches does not itself recreate services.

## Scope and Boundaries

- Only watchdog changes from the parent: digest-pinned image 2.11, read-only compatibility launcher, and three explicit environment settings.
- The launcher verifies the packaged watchdog script SHA-256 before adapting it. Its only change is gating the background worker for the absent `postfix-tlspol` service behind `WATCHDOG_POSTFIX_TLSPOL=n`. Every existing check and action remains byte-identical to the candidate. This is a temporary topology accommodation, not a recommendation against adding outbound MTA-STS.
- `DEV_MODE=n` prevents the new image's unset-variable default from enabling shell tracing. `WATCHDOG_VERBOSE` must remain `n`/`no` during deployment. `SKIP_OLEFY=n` preserves the existing Olefy monitor, which the newer script would otherwise omit when the variable is absent.
- New DNS and MariaDB client checks remain in use. No Dovecot, Postfix, mail routing, authentication, firewall, database, or Outlook change is included.
- Updating monitoring can restart genuinely unhealthy services after the existing grace periods. This is operationally consequential even though only watchdog is recreated. Review current health before applying.

## Preflight

The default helper only pulls, verifies, and syntax-checks the launcher in an offline container. It does not start health workers, mount a Docker socket, connect to production Redis/SQL, or restart services.

```sh
bash <<'BASH'
set -euo pipefail
cd /opt/mailcow-dockerized
git status --short --branch
CURRENT=$(git branch --show-current)
case "$CURRENT" in
  feature/october-2026-acme-legacy-compat|feature/october-2026-watchdog-legacy-compat) ;;
  *) echo "Accept the ACME stage first; current branch is $CURRENT."; exit 1 ;;
esac
git diff --quiet -- docker-compose.yml data/Dockerfiles/watchdog
git diff --cached --quiet
git fetch origin feature/october-2026-watchdog-legacy-compat
if git show-ref --verify --quiet refs/heads/feature/october-2026-watchdog-legacy-compat; then
  (umask 022; git switch feature/october-2026-watchdog-legacy-compat)
else
  (umask 022; git switch --track origin/feature/october-2026-watchdog-legacy-compat)
fi
(umask 022; git pull --ff-only origin feature/october-2026-watchdog-legacy-compat)
bash helper-scripts/maintenance/2026-10-watchdog.sh check
BASH
```

## Apply and Acceptance

After preflight and healthy existing monitoring, run `bash helper-scripts/maintenance/2026-10-watchdog.sh apply`. It preserves a local rollback tag and Compose file, recreates only watchdog, and waits 45 seconds for its 30-second settle delay. Inspect applicable worker health percentages, initialization, failures, and restart requests over several normal check cycles. The helper's running-state check alone is not acceptance. When `USE_WATCHDOG=n`, the existing disabled behavior is preserved; do not enable it implicitly to satisfy a test.

Offline tests run the actual candidate's adapted worker-registration blocks with stand-in healthy/failing checks. They cover optional monitors on/off, the companion gate on/off, and failure notification dispatch without running the actual container-restart action. They compare the complete rendered script against the original plus exactly one gate. Live service health, alert delivery, and restart behavior remain production validation boundaries; do not deliberately fail production mail services for this test.

## Rollback

Use the exact printed recovery directory's `rollback-image.txt`. Recreate only watchdog with both `WATCHDOG_IMAGE=<saved-local-tag>` and `WATCHDOG_SCRIPT=/watchdog.sh` set for that command, followed by `docker compose up -d --no-deps --force-recreate watchdog-mailcow`. The script override is mandatory: it bypasses the version-specific adapter when returning to 2.07. Do not delete rollback images or backups.

## Adding the Companion Later

Upstream's outbound TLS-policy companion is a separate enhancement, not the same as publishing this server's inbound MTA-STS policy through its UI/ACME schema. Stage the container with an internal-only socketmap, preserve SQL TLS override precedence, validate Postfix policy results and deferred delivery on DNS/HTTPS/service failure, then wire the socketmap and enable `WATCHDOG_POSTFIX_TLSPOL=y` together. Merely starting the container does not protect deliveries. Keep Dovecot, client-facing SMTP submission, Nginx routing, and autodiscover untouched. Do not combine that policy change with an OS hop.

The companion itself does not query MariaDB; upstream's bootstrap uses DNS, Redis for logging, and its own persistent cache. The absent `mta_sts` table is needed by the newer inbound policy/UI/ACME integration, not by this outbound resolver. Avoid importing that schema merely to add the companion. The resolver's documented Postfix map name is `QUERY` before Postfix 3.10 and `QUERYwithTLSRPT` from 3.10 onward; verify the actual deployed binary before selecting the map. Current fork `main.cf` already uses native `smtp_tls_security_level = dane` and a SQL override map.

References: [companion documentation](https://github.com/Zuplu/postfix-tlspol), [Mailcow outbound TLS scope](https://docs.mailcow.email/manual-guides/Postfix/u_e-postfix-tls_policy_override/), [upstream bootstrap](https://github.com/mailcow/mailcow-dockerized/blob/55982ac74bfd35581cc44b122ab5fc659e3ae90a/data/Dockerfiles/postfix-tlspol/postfix-tlspol.sh).
