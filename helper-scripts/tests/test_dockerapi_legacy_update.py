"""Docker API image contract checks with no host Docker socket."""

import os
import unittest
from test_phpfpm_legacy_update import ROOT, compose, run

BASELINE = "cb14bf54"
IMAGE = "ghcr.io/mailcow/dockerapi:2.12@sha256:90d6f26eb3fb8a47696d8719b71e9159849d5b49e4ce3e48967f2dfb5a8df55a"
OLD_IMAGE = "ghcr.io/mailcow/dockerapi:2.11"


class DockerApiScopeTests(unittest.TestCase):
    def test_only_dockerapi_image_and_override(self):
        source = (ROOT / "docker-compose.yml").read_text()
        before = compose(run("git", "show", BASELINE + ":docker-compose.yml"))
        before["services"]["dockerapi-mailcow"]["image"] = IMAGE
        after = compose(source)
        self.assertEqual(before, after)
        self.assertNotIn("ports", after["services"]["dockerapi-mailcow"])
        self.assertEqual(compose(source, dockerapi_image=OLD_IMAGE)["services"]["dockerapi-mailcow"]["image"], OLD_IMAGE)
        run("bash", "-n", "helper-scripts/maintenance/2026-10-dockerapi.sh")

    @unittest.skipUnless(os.getenv("MAILCOW_TEST_DOCKERAPI_RUNTIME") == "1", "Enable offline API fixtures")
    def test_old_new_api_with_stubbed_clients(self):
        for image in (OLD_IMAGE, IMAGE):
            with self.subTest(image=image):
                report = run("docker", "run", "--rm", "--pull=never", "--network=none",
                             "--mount", "type=bind,src={},dst=/fixture.py,readonly".format(ROOT / "helper-scripts/tests/dockerapi_fixture.py"),
                             "--entrypoint", "python", image, "/fixture.py")
                self.assertIn("fixtures passed", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
