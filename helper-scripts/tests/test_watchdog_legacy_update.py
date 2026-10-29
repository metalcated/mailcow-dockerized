"""Exact watchdog adapter scope and offline worker registration/failure fixtures."""

import hashlib
import os
from pathlib import Path
import re
import unittest
from test_phpfpm_legacy_update import ROOT, compose, run

BASELINE = "c99fa35d"
IMAGE = "ghcr.io/mailcow/watchdog:2.11@sha256:5436050d566d972cb157225f8a2b5c828c6bb188118f3bcab94dd8db065892c7"
ADAPTER = "data/Dockerfiles/watchdog/legacy-entrypoint.sh"


class WatchdogScopeTests(unittest.TestCase):
    def test_only_watchdog_changes_and_rollback_bypasses_adapter(self):
        source = (ROOT / "docker-compose.yml").read_text()
        before = compose(run("git", "show", BASELINE + ":docker-compose.yml"))
        after = compose(source)
        old = before["services"].pop("watchdog-mailcow")
        new = after["services"].pop("watchdog-mailcow")
        self.assertEqual(before, after)
        self.assertEqual(old.pop("image"), "ghcr.io/mailcow/watchdog:2.07")
        self.assertIsNone(old.pop("command"))
        self.assertEqual(new.pop("image"), IMAGE)
        self.assertEqual(new.pop("command"), ["/bin/bash", "/watchdog-legacy-entrypoint.sh"])
        for key, value in (("DEV_MODE", "n"), ("SKIP_OLEFY", "n"), ("WATCHDOG_POSTFIX_TLSPOL", "n")):
            self.assertEqual(new["environment"].pop(key), value)
        mount = next(m for m in new["volumes"] if m["target"] == "/watchdog-legacy-entrypoint.sh")
        self.assertEqual(Path(mount["source"]), ROOT / ADAPTER)
        self.assertTrue(mount["read_only"])
        new["volumes"].remove(mount)
        self.assertEqual(old, new)
        rollback = compose(source, watchdog_image="mailcow-watchdog-rollback:fixture", watchdog_script="/watchdog.sh")
        service = rollback["services"]["watchdog-mailcow"]
        self.assertEqual(service["command"], ["/bin/bash", "/watchdog.sh"])
        self.assertEqual(service["image"], "mailcow-watchdog-rollback:fixture")

    def test_scripts_parse_and_no_related_service_or_policy_changes(self):
        for path in (ADAPTER, "helper-scripts/maintenance/2026-10-watchdog.sh"):
            run("bash", "-n", str(ROOT / path))
        for path in ("data/conf", "data/web", "data/Dockerfiles/acme", "data/Dockerfiles/postfix",
                     "data/Dockerfiles/dovecot", "data/Dockerfiles/netfilter"):
            self.assertEqual(run("git", "diff", BASELINE, "--", path), "")
        helper = (ROOT / "helper-scripts/maintenance/2026-10-watchdog.sh").read_text()
        self.assertIn("--network=none", helper)
        self.assertIn("docker compose up -d --no-deps --force-recreate watchdog-mailcow", helper)
        self.assertNotIn("docker compose down", helper)
        doc = (ROOT / "helper-scripts/maintenance/2026-10-watchdog.md").read_text()
        for box in re.findall(r"```sh\n(.*?)\n```", doc, re.S):
            run("bash", "-n", input=box)

    @unittest.skipUnless(os.getenv("MAILCOW_TEST_WATCHDOG_RUNTIME") == "1", "Enable offline watchdog fixture")
    def test_exact_image_adaptation_worker_gates_and_failure_dispatch(self):
        base = ["docker", "run", "--rm", "--pull=never", "--network=none",
                "--mount", "type=bind,src={},dst=/adapter.sh,readonly".format(ROOT / ADAPTER)]
        original = run(*base, "--entrypoint", "cat", IMAGE, "/watchdog.sh")
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
                         "6330df1749a112aa9f510e500d3e717b3d089fc30818eaa1e2a275084d69dcf7")
        rendered = run(*base, "--entrypoint", "bash", IMAGE, "/adapter.sh", "--print")
        block = re.search(r'\(\nwhile true; do\n  if ! postfix-tlspol_checks; then.*?BACKGROUND_TASKS\+=\(\$\{PID\}\)', original, re.S).group()
        self.assertEqual(original.count(block), 1)
        self.assertEqual(rendered, original.replace(block,
                         'if [[ ${WATCHDOG_POSTFIX_TLSPOL:-n} == y ]]; then\n' + block + '\nfi'))
        self.assertIn('/usr/lib/mailcow/check_dns.sh', rendered)
        self.assertIn('-f /etc/my.cnf.d/client.cnf', rendered)
        rejected = run(*base, "--entrypoint", "bash", IMAGE, "-ec",
                       'printf "# changed\\n" >> /watchdog.sh; '
                       'if bash /adapter.sh --check; then exit 1; fi; echo rejection-passed')
        self.assertIn('rejection-passed', rejected)
        start = rendered.index('(\nwhile true; do\n  if ! nginx_checks; then')
        end = rendered.index('# Monitor watchdog agents,')
        workers = rendered[start:end]
        names = re.findall(r'if ! ([\w-]+_checks); then', workers)
        for tlspol, skip_olefy in (("n", "n"), ("y", "n"), ("n", "y")):
            for failure in (False, True):
                setup = 'BACKGROUND_TASKS=()\nlog_msg() { echo "ALERT:$*"; }\n'
                for name in names:
                    body = 'echo CHECK:' + name + '; exit 0;'
                    if failure:
                        body = 'if [[ ${SEEN:-n} == y ]]; then exit 0; fi; SEEN=y; return 1;'
                    setup += name + '() { ' + body + ' }\n'
                env = '\n'.join('export ' + k + '=' + v for k, v in {
                    'WATCHDOG_POSTFIX_TLSPOL': tlspol, 'SKIP_OLEFY': skip_olefy,
                    'SKIP_SOGO': 'n', 'SKIP_CLAMD': 'n', 'CHECK_UNBOUND': '1',
                    'WATCHDOG_EXTERNAL_CHECKS': 'y', 'WATCHDOG_MYSQL_REPLICATION_CHECKS': 'y'}.items())
                script = setup + env + '\n' + workers + '\nwait "${BACKGROUND_TASKS[@]}"\n'
                output = run(*base, "-i", "--entrypoint", "bash", IMAGE, "-s", input=script)
                expected = len(names) - (tlspol == 'n') - (skip_olefy == 'y')
                self.assertEqual(output.count('Spawned '), expected)
                if failure:
                    self.assertEqual(output.count('ALERT:'), expected)
                else:
                    self.assertEqual(output.count('CHECK:'), expected)
                self.assertEqual('Spawned postfix-tlspol_checks' in output, tlspol == 'y')
                self.assertEqual('Spawned olefy_checks' in output, skip_olefy == 'n')


if __name__ == "__main__":
    unittest.main(verbosity=2)
