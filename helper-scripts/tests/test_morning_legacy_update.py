"""Cumulative preparation boundaries and reasons for holding support images."""

import os
import re
import unittest
from test_phpfpm_legacy_update import ROOT, compose, run


class MorningHandoffTests(unittest.TestCase):
    def test_only_four_followon_images_change_and_sensitive_files_stay_put(self):
        before = compose(run("git", "show", "72055a93:docker-compose.yml"))
        after = compose((ROOT / "docker-compose.yml").read_text())
        for name in ("unbound-mailcow", "rspamd-mailcow", "dockerapi-mailcow", "olefy-mailcow"):
            before["services"][name]["image"] = after["services"][name]["image"]
            self.assertIn("@sha256:", after["services"][name]["image"])
        self.assertEqual(before, after)
        self.assertEqual(after["services"]["acme-mailcow"]["image"], "ghcr.io/mailcow/acme:1.92")
        self.assertEqual(after["services"]["watchdog-mailcow"]["image"], "ghcr.io/mailcow/watchdog:2.07")
        for path in ("data/conf/postfix", "data/conf/dovecot", "data/conf/nginx", "data/conf/sogo",
                     "data/conf/rspamd/local.d/redis.conf", "data/web/inc/init_db.inc.php",
                     "data/Dockerfiles/netfilter", "data/Dockerfiles/phpfpm/docker-entrypoint.sh"):
            self.assertEqual(run("git", "diff", "72055a93", "--", path), "")

    def test_all_command_boxes_parse_and_deployment_is_service_scoped(self):
        doc = (ROOT / "helper-scripts/maintenance/2026-10-morning.md").read_text()
        boxes = re.findall(r"```sh\n(.*?)\n```", doc, re.S)
        self.assertEqual(len(boxes), 5)
        for box in boxes:
            run("bash", "-n", input=box)
            self.assertIn("git branch --show-current", box)
            self.assertNotIn("reset --hard", box)
        for service in ("unbound", "rspamd", "dockerapi", "olefy"):
            path = ROOT / ("helper-scripts/maintenance/2026-10-" + service + ".sh")
            source = path.read_text()
            run("bash", "-n", str(path))
            self.assertIn("MODE=${1:-check}", source)
            self.assertIn("--network=none", source)
            self.assertIn("docker compose up -d --no-deps --force-recreate " + service + "-mailcow", source)
            self.assertNotIn("docker compose run", source)
            self.assertNotIn("/var/run/docker.sock", source)

    @unittest.skipUnless(os.getenv("MAILCOW_TEST_SUPPORT_AUDIT") == "1", "Enable downloaded support-image audit")
    def test_held_candidates_really_require_missing_features(self):
        acme = run("docker", "run", "--rm", "--pull=never", "--network=none", "--entrypoint", "cat",
                   "ghcr.io/mailcow/acme:1.98@sha256:ebbd0e6a7d5313189f847d0d6219507a693f6d77d257c1671ebab9656680a5ba", "/srv/acme.sh")
        self.assertIn("SELECT domain FROM mta_sts WHERE active = 1", acme)
        self.assertIn("INNER JOIN mta_sts", acme)
        self.assertNotRegex((ROOT / "data/web/inc/init_db.inc.php").read_text(), r"CREATE TABLE[^;]+mta_sts")
        watchdog = run("docker", "run", "--rm", "--pull=never", "--network=none", "--entrypoint", "cat",
                       "ghcr.io/mailcow/watchdog:2.11@sha256:5436050d566d972cb157225f8a2b5c828c6bb188118f3bcab94dd8db065892c7", "/watchdog.sh")
        self.assertIn("if ! postfix-tlspol_checks; then", watchdog)
        self.assertNotIn("postfix-tlspol-mailcow", compose((ROOT / "docker-compose.yml").read_text())["services"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
