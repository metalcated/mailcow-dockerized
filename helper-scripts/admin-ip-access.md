# Administrator IP access

This fork can limit administrator and domain-administrator accounts by source
IP while leaving mailbox users, their self-service portal, SOGo and mail clients
public. The shared login page remains public. This is an account-role policy,
not a hostname-wide firewall rule, and there is no browser setting for it.

Set the policy in the existing `data/web/inc/vars.local.inc.php`, inside its PHP
block. Keep that file private to the installation and outside Git. For example:

```php
$ADMIN_IP_ALLOWLIST = ['192.0.2.0/24', '198.51.100.0/25', '203.0.113.24'];
$ADMIN_IP_API_ALLOWLIST = ['127.0.0.1', '::1', '192.0.2.250'];
```

Use your actual trusted LAN/VPN ranges and fixed public addresses. A `/25` does
not include the upper half of a `/24`; expand it only when that additional range
should be trusted. IPv4 and IPv6 networks are supported. An unset or `null`
administrator list preserves the original unrestricted behavior. An empty list
denies browser administration; malformed administrator configuration fails closed.

The API exception is separate from browser administration. It permits only a
currently verified API key, `GET`, and these two exact ISPConfig URLs, without
query parameters or alternate routing:

- `/api/v1/get/domain/all`
- `/api/v1/get/status/containers`

Mailcow's own API-key source-IP check remains required. The exception grants no
browser access, write API access, or additional endpoint access, even when the
saved key itself has broader permissions. It does not change that key. Use only the
local caller addresses that need those readings, not a whole private subnet.

The policy uses PHP's `REMOTE_ADDR`, supplied by the trusted reverse proxy. The
public proxy must overwrite incoming forwarded-address headers, and direct
container HTTP/HTTPS ports must remain private. Do not substitute arbitrary
`X-Forwarded-For` or `X-Real-IP` headers in the policy.

Enforcement covers administrator password login before MFA is prepared,
pending MFA, existing sessions, administrator impersonation sessions, verified
API sessions, passwordless FIDO2 login and domain-administrator SSO. A session that moves outside its
allowed range receives HTTP 403 and loses its privileged session; its next
request can use the ordinary public mailbox login. Mailbox user roles are not
restricted. Native authentication, CSRF, API permissions and MFA checks remain.

Before installing, preserve the five affected PHP files and the local settings
file, record hashes, and compare them with the current deployed revision. Install
only this patch; unrelated prepared component updates are not part of it. No
database migration or mail-service restart is needed. Allow the existing PHP
opcode cache to revalidate changed files and verify the actual HTTP behavior.

Run `python3 -m unittest discover -s helper-scripts/tests -p test_admin_ip_access.py -v`.
Set `MAILCOW_PHP_COMMAND` to a JSON argument array if using an existing isolated
PHP runtime. The fixtures execute the real password and session code against
synthetic accounts, an in-memory database substitute and in-memory sessions.
They do not send email or connect to the production database.

Verify trusted administrator access, rejected untrusted administrator access,
public mailbox self-service and SOGo login, discovery/synchronization endpoints,
and the existing ISPConfig readings. Keep browser/client acceptance distinct
from fixture results. Restore the saved files and local configuration together
to roll back. Never replace or delete existing local settings to force a retry.
