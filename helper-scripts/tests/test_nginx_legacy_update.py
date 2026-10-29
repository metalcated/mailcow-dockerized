"""Nginx-only stage checks against the completed PHP source stage.

MAILCOW_TEST_NGINX_RUNTIME=1 enables offline containers with generated fixture
certificates. They publish no ports and mount no production configuration.
"""

import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest
import uuid
import subprocess

from test_phpfpm_legacy_update import ROOT, compose, run


BASELINE = "5cabaf3c"
OLD_IMAGE = "ghcr.io/mailcow/nginx:1.30.4-1"
IMAGE = "ghcr.io/mailcow/nginx:1.30.6-1@sha256:68697b99f272527dc38bbfb4c8cf217c02dffc7bc0a0b3b19b0c5256eda2aef4"


class NginxComposeTests(unittest.TestCase):
    def test_only_nginx_image_and_bootstrap_mount_change(self):
        before = compose(run("git", "show", BASELINE + ":docker-compose.yml"))
        after = compose((ROOT / "docker-compose.yml").read_text())
        old = before["services"].pop("nginx-mailcow")
        new = after["services"].pop("nginx-mailcow")
        self.assertEqual(before, after)
        self.assertEqual(old.pop("image"), OLD_IMAGE)
        self.assertEqual(new.pop("image"), IMAGE)
        mount = next(m for m in new["volumes"] if m["target"] == "/bootstrap.py")
        self.assertEqual(mount["type"], "bind")
        self.assertEqual(Path(mount["source"]), ROOT / "data/Dockerfiles/nginx/bootstrap.py")
        self.assertTrue(mount["read_only"])
        new["volumes"].remove(mount)
        self.assertEqual(old, new)

    def test_image_rollback_and_retry(self):
        source = (ROOT / "docker-compose.yml").read_text()
        expected = compose(source)
        rollback = compose(source, nginx_image=OLD_IMAGE)
        expected["services"]["nginx-mailcow"]["image"] = OLD_IMAGE
        self.assertEqual(rollback, expected)
        self.assertEqual(compose(source, nginx_image=""), compose(source))

    def test_renderer_templates_and_entrypoint_remain_unchanged(self):
        for path in (
            "data/Dockerfiles/nginx/bootstrap.py",
            "data/Dockerfiles/nginx/docker-entrypoint.sh",
            "data/conf/nginx/templates/nginx.conf.j2",
            "data/conf/nginx/templates/sites-default.conf.j2",
        ):
            with self.subTest(path=path):
                self.assertEqual((ROOT / path).read_bytes(), subprocess.check_output(
                    ["git", "show", BASELINE + ":" + path], cwd=ROOT))

    def test_runbook_shell_commands_parse(self):
        doc = (ROOT / "helper-scripts/maintenance/2026-10-nginx.md").read_text()
        blocks = re.findall(r"```sh\n(.*?)\n```", doc, re.DOTALL)
        self.assertGreaterEqual(len(blocks), 3)
        for block in blocks:
            run("bash", "-n", input=block)
            self.assertNotIn("--entrypoint sh", block)
        self.assertIn("nginx-mailcow nginx -t", doc)
        self.assertNotIn("run --rm --no-deps --pull", doc)


@unittest.skipUnless(os.getenv("MAILCOW_TEST_NGINX_RUNTIME") == "1",
                     "Set MAILCOW_TEST_NGINX_RUNTIME=1 for offline image checks")
class NginxRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="mailcow-nginx-fixture-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.ssl = Path(cls.temporary.name)
        run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=mail.example.test", "-keyout", str(cls.ssl / "key.pem"),
            "-out", str(cls.ssl / "cert.pem"))

    def render(self, image, disabled, proxy_protocol="n", normal_startup=False):
        name = "mailcow-nginx-check-" + uuid.uuid4().hex
        if normal_startup:
            config = tempfile.TemporaryDirectory(prefix="mailcow-nginx-config-")
            self.addCleanup(config.cleanup)
            shutil.copytree(ROOT / "data/conf/nginx", Path(config.name) / "conf.d")
            config_mount = "type=bind,src={},dst=/etc/nginx/conf.d".format(Path(config.name) / "conf.d")
        else:
            config_mount = "type=tmpfs,dst=/etc/nginx/conf.d"
        command = [
            "docker", "run", "--rm", "--name", name, "--pull=never", "--network=none",
            "--mount", config_mount,
            "--mount", "type=bind,src={},dst=/fixtures,readonly".format(ROOT / "data/conf/nginx"),
            "--mount", "type=bind,src={},dst=/bootstrap.py,readonly".format(ROOT / "data/Dockerfiles/nginx/bootstrap.py"),
            "--mount", "type=bind,src={},dst=/etc/ssl/mail,readonly".format(self.ssl),
            "--env", "MAILCOW_HOSTNAME=mail.example.test",
            "--env", "PHPFPMHOST=" + ("" if normal_startup else "127.0.0.1"),
            "--env", "SOGOHOST=" + ("" if normal_startup else "127.0.0.1"),
            "--env", "RSPAMDHOST=" + ("" if normal_startup else "127.0.0.1"),
            "--env", "IPV4_NETWORK=127.0.0",
            "--env", "DISABLE_IPv6=" + disabled,
            "--env", "NGINX_USE_PROXY_PROTOCOL=" + proxy_protocol,
            "--env", "TRUSTED_PROXIES=192.0.2.0/24,198.51.100.1",
            "--add-host", "php-fpm-mailcow:127.0.0.1",
            "--add-host", "rspamd-mailcow:127.0.0.1",
        ]
        if os.getenv("MAILCOW_TEST_PLATFORM"):
            command += ["--platform", os.environ["MAILCOW_TEST_PLATFORM"]]
        script = """
            nginx -t
            nginx -v 2>&1
            python3 -c 'import json; from pathlib import Path; print(json.dumps({p: Path(p).read_text() for p in ["/etc/nginx/nginx.conf", "/etc/nginx/includes/sites-default.conf", "/etc/nginx/conf.d/listen_plain.active", "/etc/nginx/conf.d/listen_ssl.active"]}))'
        """
        try:
            if normal_startup:
                output = run(*command, image, "sh", "-ec", script)
            else:
                script = "cp -R /fixtures/. /etc/nginx/conf.d/\npython3 /bootstrap.py\n" + script
                output = run(*command, "--entrypoint", "sh", image, "-ec", script)
        except BaseException:
            subprocess.run(["docker", "stop", "--time", "1", name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            raise
        self.assertIn("nginx/1.30.6" if image == IMAGE else "nginx/1.30.4", output)
        return json.loads(output.splitlines()[-1])

    def test_normal_entrypoint_defaults_empty_backend_hosts(self):
        configs = self.render(IMAGE, "n", normal_startup=True)
        site = configs["/etc/nginx/includes/sites-default.conf"]
        self.assertIn("fastcgi_pass php-fpm-mailcow:9002;", site)
        self.assertIn("http://127.0.0.248:20000", site)
        self.assertIn("http://rspamd-mailcow:11334", site)
        self.assertNotIn("fastcgi_pass :", site)

    def test_rendered_configuration_matches_old_image(self):
        for disabled, proxy_protocol in (("n", "n"), ("y", "n"), ("n", "y")):
            with self.subTest(disabled=disabled, proxy_protocol=proxy_protocol):
                old = self.render(OLD_IMAGE, disabled, proxy_protocol)
                new = self.render(IMAGE, disabled, proxy_protocol)
                self.assertEqual(old, new)
                self.assertEqual("listen [::]" in new["/etc/nginx/nginx.conf"], disabled == "n")
                site = new["/etc/nginx/includes/sites-default.conf"]
                self.assertIn("location /sogo-auth-verify", site)
                self.assertIn("location ^~ /Microsoft-Server-ActiveSync", site)
                self.assertIn("autodiscover", site)


if __name__ == "__main__":
    unittest.main(verbosity=2)
