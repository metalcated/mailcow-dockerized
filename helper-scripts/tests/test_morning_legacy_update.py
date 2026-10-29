"""Cumulative preparation boundaries and reasons for holding support images."""

import os
from pathlib import Path
import re
import stat
import tempfile
import unittest
from test_phpfpm_legacy_update import ROOT, compose, run


class MorningHandoffTests(unittest.TestCase):
    def test_git_updates_scope_source_permissions_separately_from_backups(self):
        updates = 0
        for path in (ROOT / "helper-scripts/maintenance").glob("2026-10-*.md"):
            for box in re.findall(r"```sh\n(.*?)\n```", path.read_text(), re.S):
                run("bash", "-n", input=box)
                for line in box.splitlines():
                    if re.search(r"\bgit (switch|pull)\b", line):
                        with self.subTest(path=path.name, command=line.strip()):
                            self.assertRegex(line.strip(), r"^\(umask 022; git (switch|pull) .+\)$")
                        updates += 1
        self.assertGreaterEqual(updates, 10)

    def test_real_checkout_preserves_public_modes_and_private_outer_mask(self):
        with tempfile.TemporaryDirectory(prefix="mailcow-checkout-modes-") as directory:
            repo = Path(directory)
            run("git", "init", "-q", str(repo))

            def git(*args, **kwargs):
                return run("git", "-C", str(repo), *args, **kwargs).strip()

            for branch, content in (("before", "before\n"), ("after", "after\n")):
                blob = git("hash-object", "-w", "--stdin", input=content)
                tree = git("mktree", input=(
                    "100644 blob " + blob + "\tentry.php\n"
                    "100755 blob " + blob + "\tadapter.sh\n"))
                commit = git("-c", "user.name=Mailcow tests",
                             "-c", "user.email=mailcow-tests@example.invalid",
                             "-c", "commit.gpgsign=false", "commit-tree", tree, "-m", branch)
                git("update-ref", "refs/heads/" + branch, commit)
            git("switch", "-q", "before")

            run("bash", "-ec", 'umask 077; git -C "$1" switch -q after', "--", str(repo))
            self.assertEqual(stat.S_IMODE((repo / "entry.php").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((repo / "adapter.sh").stat().st_mode), 0o700)

            mask = run("bash", "-ec", 'umask 077; (umask 022; git -C "$1" switch -q before); umask',
                       "--", str(repo)).strip()
            self.assertEqual(int(mask, 8), 0o077)
            self.assertEqual(stat.S_IMODE((repo / "entry.php").stat().st_mode), 0o644)
            self.assertEqual(stat.S_IMODE((repo / "adapter.sh").stat().st_mode), 0o755)

    def test_web_preflight_reads_all_changed_files_as_php_worker(self):
        doc = (ROOT / "helper-scripts/maintenance/2026-10-morning.md").read_text()
        section = doc.split("## Stage 2: web hardening", 1)[1].split("## Stage 3:", 1)[0]
        self.assertIn("--user www-data php-fpm-mailcow php -l", section)
        self.assertIn('inc/functions.inc.php inc/ajax/dns_diagnostics.php oauth/authorize.php', section)
        self.assertIn('--user www-data php-fpm-mailcow php -r', section)
        self.assertIn('is_readable("/web/js/site/debug.js")', section)

    def test_only_four_followon_images_change_and_sensitive_files_stay_put(self):
        before = compose(run("git", "show", "72055a93:docker-compose.yml"))
        after = compose(run("git", "show", "ec0fb5e34:docker-compose.yml"))
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
