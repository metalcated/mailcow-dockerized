"""Unbound-only stage and disconnected resolver configuration/runtime checks."""

import os
from pathlib import Path
import re
import subprocess
import unittest

from test_phpfpm_legacy_update import ROOT, compose, run

BASELINE = "72055a93"
IMAGE = "ghcr.io/mailcow/unbound:1.26.2-1@sha256:016bd7056ac86ef3f43ae05d38b7bfa0c59afed69ffac1eab30ea00e0850cb8b"
OLD_IMAGE = "ghcr.io/mailcow/unbound:1.25.1-1"


class UnboundComposeTests(unittest.TestCase):
    def test_only_image_changes_and_rollback(self):
        source = (ROOT / "docker-compose.yml").read_text()
        old = compose(run("git", "show", BASELINE + ":docker-compose.yml"))
        new = compose(source)
        self.assertEqual(old["services"]["unbound-mailcow"].pop("image"), OLD_IMAGE)
        self.assertEqual(new["services"]["unbound-mailcow"].pop("image"), IMAGE)
        self.assertEqual(old, new)
        restored = compose(source, unbound_image=OLD_IMAGE)
        baseline = compose(run("git", "show", BASELINE + ":docker-compose.yml"))
        self.assertEqual(restored, baseline)

    def test_config_and_sensitive_workflows_unchanged(self):
        for path in ("data/conf/unbound/unbound.conf", "data/conf/dovecot/auth/passwd-verify.lua",
                     "data/conf/nginx/templates/sites-default.conf.j2", "data/web/inc/init_db.inc.php"):
            self.assertEqual((ROOT / path).read_bytes(), subprocess.check_output(
                ["git", "show", BASELINE + ":" + path], cwd=ROOT))

    def test_handoff_syntax_and_isolation(self):
        helper = ROOT / "helper-scripts/maintenance/2026-10-unbound.sh"
        run("bash", "-n", str(helper))
        self.assertIn("--network=none", helper.read_text())
        self.assertNotIn("docker compose run", helper.read_text())
        self.assertIn("MODE=${1:-check}", helper.read_text())
        doc = (ROOT / "helper-scripts/maintenance/2026-10-morning.md").read_text()
        for block in re.findall(r"```sh\n(.*?)\n```", doc, re.DOTALL):
            run("bash", "-n", input=block)


@unittest.skipUnless(os.getenv("MAILCOW_TEST_UNBOUND_RUNTIME") == "1", "Enable offline resolver fixtures")
class UnboundRuntimeTests(unittest.TestCase):
    def test_actual_config_start_and_udp_tcp_queries(self):
        script = r'''
            cp /fixture/unbound.conf /etc/unbound/unbound.conf
            cp /usr/share/dnssec-root/trusted-key.key /etc/unbound/trusted-key.key
            unbound-control-setup >/dev/null 2>&1
            printf '\nserver:\n  local-zone: "fixture.test." static\n  local-data: "fixture.test. 60 IN A 192.0.2.9"\n' >> /etc/unbound/unbound.conf
            unbound-checkconf
            unbound-checkconf -o module-config | grep -q validator
            unbound -d > /tmp/unbound-fixture.log 2>&1 &
            DAEMON=$!
            trap 'kill "$DAEMON" 2>/dev/null || true; wait "$DAEMON" 2>/dev/null || true' EXIT
            READY=0
            for ATTEMPT in $(seq 1 20); do
              if dig @127.0.0.1 fixture.test A +short +time=1 +tries=1 | grep -qx 192.0.2.9; then READY=1; break; fi
              sleep 1
            done
            if [ "$READY" != 1 ]; then cat /tmp/unbound-fixture.log; exit 1; fi
            dig @127.0.0.1 fixture.test A +tcp +short +time=1 +tries=1 | grep -qx 192.0.2.9
            echo 'UDP/TCP fixture passed with validator enabled'
        '''
        for image in (OLD_IMAGE, IMAGE):
            with self.subTest(image=image):
                command = ["docker", "run", "--rm", "--pull=never", "--network=none",
                    "--mount", "type=bind,src={},dst=/fixture,readonly".format(ROOT / "data/conf/unbound")]
                if os.getenv("MAILCOW_TEST_PLATFORM"):
                    command += ["--platform", os.environ["MAILCOW_TEST_PLATFORM"]]
                output = run(*command, "--entrypoint", "sh", image, "-ec", script)
                self.assertIn("fixture passed", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
