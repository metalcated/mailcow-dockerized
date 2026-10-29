"""Olefy image and real protocol/scanner fixtures without external connections."""

import os
import unittest
from test_phpfpm_legacy_update import ROOT, compose, run

BASELINE = "ef6bb1c2"
IMAGE = "ghcr.io/mailcow/olefy:1.15@sha256:cec980cddf162594f5f1a7b575ae95c0f17f0c42febcfac94a478eca2d2bfd9e"
OLD_IMAGE = "ghcr.io/mailcow/olefy:1.14"


class OlefyScopeTests(unittest.TestCase):
    def test_only_olefy_image_and_override(self):
        source = run("git", "show", "ec0fb5e34:docker-compose.yml")
        before = compose(run("git", "show", BASELINE + ":docker-compose.yml"))
        before["services"]["olefy-mailcow"]["image"] = IMAGE
        after = compose(source)
        self.assertEqual(before, after)
        self.assertEqual(compose(source, olefy_image=OLD_IMAGE)["services"]["olefy-mailcow"]["image"], OLD_IMAGE)
        self.assertEqual(after["services"]["olefy-mailcow"]["environment"]["OLEFY_BINDPORT"], "10055")
        self.assertNotIn("ports", after["services"]["olefy-mailcow"])
        run("bash", "-n", "helper-scripts/maintenance/2026-10-olefy.sh")

    @unittest.skipUnless(os.getenv("MAILCOW_TEST_OLEFY_RUNTIME") == "1", "Enable offline Olefy fixtures")
    def test_old_new_protocol_and_office_scan(self):
        for image in (OLD_IMAGE, IMAGE):
            with self.subTest(image=image):
                report = run("docker", "run", "--rm", "--pull=never", "--network=none",
                             "--mount", "type=bind,src={},dst=/fixture.py,readonly".format(ROOT / "helper-scripts/tests/olefy_fixture.py"),
                             "--entrypoint", "/usr/bin/python3", image, "/fixture.py")
                self.assertIn("clean Office scan passed", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
