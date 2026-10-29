"""ACME base-image refresh with byte-identical legacy HTTP-01 orchestration."""

import copy
import os
from pathlib import Path
import unittest
from test_phpfpm_legacy_update import ROOT, compose, run

BASELINE = "931548ae"
IMAGE = "ghcr.io/mailcow/acme:1.98@sha256:ebbd0e6a7d5313189f847d0d6219507a693f6d77d257c1671ebab9656680a5ba"
SCRIPTS = ("acme.sh", "functions.sh", "obtain-certificate.sh")


class AcmeScopeTests(unittest.TestCase):
    def test_only_acme_image_and_three_readonly_adapters_change(self):
        before = compose(run("git", "show", BASELINE + ":docker-compose.yml"))
        source = run("git", "show", "c99fa35d:docker-compose.yml")
        after = compose(source)
        expected = copy.deepcopy(before)
        expected["services"]["acme-mailcow"]["image"] = IMAGE
        mounts = after["services"]["acme-mailcow"]["volumes"]
        for name in SCRIPTS:
            mount = next(m for m in mounts if m["target"] == "/srv/" + name)
            self.assertTrue(mount["read_only"])
            self.assertEqual(Path(mount["source"]), ROOT / "data/Dockerfiles/acme" / name)
            expected["services"]["acme-mailcow"]["volumes"].append(mount)
        self.assertEqual(expected, after)
        rollback = compose(source, acme_image="ghcr.io/mailcow/acme:1.92")
        after["services"]["acme-mailcow"]["image"] = "ghcr.io/mailcow/acme:1.92"
        self.assertEqual(rollback, after)

    def test_legacy_scripts_and_related_workflows_stay_identical(self):
        for name in SCRIPTS + ("reload-configurations.sh",):
            path = "data/Dockerfiles/acme/" + name
            self.assertEqual((ROOT / path).read_text(), run("git", "show", BASELINE + ":" + path))
            run("bash", "-n", str(ROOT / path))
        main = (ROOT / "data/Dockerfiles/acme/acme.sh").read_text()
        self.assertNotIn("mta_sts", main)
        self.assertNotIn("ACME_DNS_CHALLENGE", main)
        for path in ("data/conf/dovecot", "data/conf/postfix", "data/conf/nginx", "data/conf/sogo",
                     "data/web", "data/Dockerfiles/phpfpm/docker-entrypoint.sh"):
            self.assertEqual(run("git", "diff", BASELINE, "--", path), "")

    def test_helper_is_offline_first_and_service_scoped(self):
        path = ROOT / "helper-scripts/maintenance/2026-10-acme.sh"
        source = path.read_text()
        run("bash", "-n", str(path))
        self.assertIn("MODE=${1:-check}", source)
        self.assertIn("--network=none", source)
        self.assertIn("docker compose up -d --no-deps --force-recreate acme-mailcow", source)
        self.assertIn("-checkend 2592000", source)
        self.assertNotIn("docker compose down", source)
        self.assertNotIn("touch data/assets/ssl/force_renew", source)

    @unittest.skipUnless(os.getenv("MAILCOW_TEST_ACME_RUNTIME") == "1", "Enable offline certificate fixtures")
    def test_real_new_image_executes_legacy_renewal_and_failure_paths(self):
        command = ["docker", "run", "--rm", "--pull=never", "--network=none"]
        for name in SCRIPTS:
            command += ["--mount", "type=bind,src={},dst=/srv/{},readonly".format(
                ROOT / "data/Dockerfiles/acme" / name, name)]
        command += ["--mount", "type=bind,src={},dst=/fixture.sh,readonly".format(
            ROOT / "helper-scripts/tests/acme_legacy_fixture.sh"),
                    "--entrypoint", "bash", IMAGE, "/fixture.sh"]
        self.assertIn("passed (offline CA stand-in)", run(*command))


if __name__ == "__main__":
    unittest.main(verbosity=2)
