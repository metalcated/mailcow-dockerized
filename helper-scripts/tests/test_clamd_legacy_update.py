"""ClamAV image-only checks and optional disconnected scanner fixtures."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import unittest
import uuid

from test_phpfpm_legacy_update import ROOT, compose, run


BASELINE = "4d1a89d2"
STAGE = "2a8e8973"
OLD_IMAGE = "ghcr.io/mailcow/clamd:1.71"
IMAGE = "ghcr.io/mailcow/clamd:1.4.6-1@sha256:0d512b3a179c5f97e6f3132d1f88d9ec72c456fc6f7ba32a664ed4327fbd1436"
DOC = ROOT / "helper-scripts/maintenance/2026-10-clamd.md"


class ClamdComposeTests(unittest.TestCase):
    def test_only_clamd_image_changes(self):
        old = compose(run("git", "show", BASELINE + ":docker-compose.yml"))
        new = compose(run("git", "show", STAGE + ":docker-compose.yml"))
        self.assertEqual(old["services"]["clamd-mailcow"].pop("image"), OLD_IMAGE)
        self.assertEqual(new["services"]["clamd-mailcow"].pop("image"), IMAGE)
        self.assertEqual(old, new)

    def test_rollback_override_and_retry(self):
        source = run("git", "show", STAGE + ":docker-compose.yml")
        expected = compose(source)
        expected["services"]["clamd-mailcow"]["image"] = OLD_IMAGE
        self.assertEqual(compose(source, clamd_image=OLD_IMAGE), expected)
        self.assertEqual(compose(source, clamd_image=""), compose(source))

    def test_scan_policy_authentication_and_schema_are_unchanged(self):
        for path in (
            "data/conf/clamav/clamd.conf", "data/conf/clamav/freshclam.conf",
            "data/conf/rspamd/local.d/antivirus.conf",
            "data/conf/dovecot/auth/passwd-verify.lua", "data/web/inc/init_db.inc.php",
            "data/conf/nginx/templates/sites-default.conf.j2", "data/conf/sogo/sogo.conf",
        ):
            with self.subTest(path=path):
                self.assertEqual((ROOT / path).read_text(),
                                 run("git", "show", BASELINE + ":" + path))

    def test_runbook_commands_parse_and_do_not_use_compose_preflight(self):
        doc = DOC.read_text()
        for block in re.findall(r"```sh\n(.*?)\n```", doc, re.DOTALL):
            run("bash", "-n", input=block)
        self.assertNotIn("docker compose run", doc)
        checks = [line.strip() for line in doc.splitlines()
                  if line.strip().startswith("docker run ")]
        self.assertEqual(len(checks), 2)
        for check in checks:
            self.assertIn("--network=none", check)
            self.assertNotIn("/var/lib/clamav", check)
        self.assertIn("--no-deps --force-recreate clamd-mailcow", doc)


@unittest.skipUnless(os.getenv("MAILCOW_TEST_CLAMD_RUNTIME") == "1",
                     "Set MAILCOW_TEST_CLAMD_RUNTIME=1 for disconnected scan fixtures")
class ClamdRuntimeTests(unittest.TestCase):
    def container(self, image, script):
        args = ["docker", "run", "--rm", "--pull=never", "--network=none"]
        if os.getenv("MAILCOW_TEST_PLATFORM"):
            args += ["--platform", os.environ["MAILCOW_TEST_PLATFORM"]]
        args += ["--mount", "type=bind,src={},dst=/etc/clamav,readonly".format(ROOT / "data/conf/clamav")]
        return run(*args, "--entrypoint", "bash", image, "-euc", script)

    def test_packaged_startup_and_healthcheck_match(self):
        script = "sha256sum /clamd.sh /usr/local/bin/clamdcheck.sh"
        self.assertEqual(self.container(OLD_IMAGE, script), self.container(IMAGE, script))
        self.assertIn("ClamAV 1.4.6", self.container(IMAGE, "clamd -V; clamconf -n >/dev/null; bash -n /clamd.sh"))

    def test_exact_documented_preflight(self):
        checks = [line.strip() for line in DOC.read_text().splitlines()
                  if line.strip().startswith("docker run ")]
        with tempfile.TemporaryDirectory(prefix="mailcow-clamd-preflight-") as directory:
            env = os.environ.copy()
            env.update({"CLAMD_TARGET": IMAGE, "RECOVERY_DIR": directory,
                        "PWD": str(ROOT)})
            for check in checks:
                run("bash", "-euc", check, env=env)
            self.assertEqual((Path(directory) / "new-startup.sha256").read_text(),
                             self.container(OLD_IMAGE, "sha256sum /clamd.sh /usr/local/bin/clamdcheck.sh"))

    def test_readiness_fails_without_a_daemon(self):
        self.container(IMAGE, "if clamdscan --ping 1 >/dev/null 2>&1; then exit 1; fi")

    def test_current_rspamd_can_reach_real_scanner(self):
        name = "mailcow-clamd-fixture-" + uuid.uuid4().hex
        network = name + "-network"
        script = r'''
            mkdir -p /tmp/fixture-db /run/clamav
            printf '%s\n' 'MailcowFixture:0:*:6d61696c636f772066697874757265' > /tmp/fixture-db/fixture.ndb
            chown -R clamav:clamav /tmp/fixture-db /run/clamav
            exec clamd --datadir=/tmp/fixture-db
        '''
        run("docker", "network", "create", "--internal", network)
        try:
            args = ["docker", "run", "--rm", "-d", "--name", name,
                    "--pull=never", "--network", network, "--network-alias", "clamd"]
            if os.getenv("MAILCOW_TEST_PLATFORM"):
                args += ["--platform", os.environ["MAILCOW_TEST_PLATFORM"]]
            args += ["--mount", "type=bind,src={},dst=/etc/clamav,readonly".format(ROOT / "data/conf/clamav")]
            run(*args, "--entrypoint", "bash", IMAGE, "-euc", script)
            for _ in range(30):
                ready = subprocess.run(["docker", "exec", name, "clamdscan", "--ping", "1"],
                                       capture_output=True, timeout=10)
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                self.fail(run("docker", "logs", name))
            line = next(line.strip() for line in DOC.read_text().splitlines()
                        if line.strip().startswith("docker compose exec -T rspamd-mailcow timeout"))
            command = shlex.split(line)[5:]
            args = ["docker", "run", "--rm", "--pull=never", "--network", network]
            if os.getenv("MAILCOW_TEST_PLATFORM"):
                args += ["--platform", os.environ["MAILCOW_TEST_PLATFORM"]]
            output = run(*args, "--entrypoint", command[0],
                         "ghcr.io/mailcow/rspamd:3.14.3-1", *command[1:])
            self.assertIn("Rspamd to ClamAV: PONG", output)
        finally:
            subprocess.run(["docker", "stop", "--time", "1", name],
                           capture_output=True, timeout=15)
            run("docker", "network", "rm", network)

    def test_actual_daemon_scans_clean_and_matching_streams(self):
        marker = "mailcow harmless scanner fixture marker"
        script = r'''
            mkdir -p /tmp/fixture-db /run/clamav
            printf '%s\n' 'MailcowFixture:0:*:SIGNATURE' > /tmp/fixture-db/fixture.ndb
            chown -R clamav:clamav /tmp/fixture-db /run/clamav
            clamd --datadir=/tmp/fixture-db > /tmp/clamd-fixture.log 2>&1 &
            DAEMON=$!
            trap 'kill "$DAEMON" 2>/dev/null || true; wait "$DAEMON" 2>/dev/null || true' EXIT
            READY=0
            for ATTEMPT in $(seq 1 30); do
                if clamdscan --ping 1 >/dev/null 2>&1; then READY=1; break; fi
                sleep 1
            done
            if [ "$READY" != 1 ]; then cat /tmp/clamd-fixture.log; exit 1; fi
            printf 'ordinary clean fixture\n' | clamdscan --stream --no-summary - > /tmp/clean-report
            set +e
            printf '%s' 'MARKER' | clamdscan --stream --no-summary - > /tmp/match-report
            RESULT=$?
            set -e
            test "$RESULT" -eq 1
            grep -q 'OK' /tmp/clean-report
            grep -q 'MailcowFixture.*FOUND' /tmp/match-report
            cat /tmp/clean-report /tmp/match-report
        '''.replace("SIGNATURE", marker.encode().hex()).replace("MARKER", marker)
        for image in (OLD_IMAGE, IMAGE):
            with self.subTest(image=image):
                report = self.container(image, script)
                self.assertIn("FOUND", report)
                self.assertIn("OK", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
