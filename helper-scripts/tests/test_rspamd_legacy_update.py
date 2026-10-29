"""Rspamd 3-to-4 mail fixtures on a disposable internal Docker network."""

import email
from email import policy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid

from test_phpfpm_legacy_update import ROOT, compose, run

BASELINE = "be4417db"
IMAGE = "ghcr.io/mailcow/rspamd:4.2.1-1@sha256:6e7375761b6234cf6db6d462dc3f68f121401e9e6b75d7889ec0b22a62f64b4c"
OLD_IMAGE = "ghcr.io/mailcow/rspamd:3.14.3-1"
REDIS = "redis:7.4.12-alpine@sha256:338fbfc036dc5517ac0b04d6de21521085935336e565f223406180e9d84166e2"
PHP = "ghcr.io/mailcow/phpfpm:8.2.35-1@sha256:f8fe320173eb99afeb3cfb65ecb3b45c92d7a56c9890a516efbcb13e5ca647fa"

# Copy the same mounted configuration onto the image's own versioned defaults.
BOOTSTRAP = r'''
for item in custom override.d local.d plugins.d lua rspamd.conf.local rspamd.conf.override; do
  cp -a /fixture/$item /etc/rspamd/
done
ln -sf /usr/lib/$(uname -m)-linux-gnu/liblua5.1-cjson.so.0.0.0 /usr/lib/rspamd/cjson.so
rspamadm configtest
exec rspamd -f -u _rspamd -g _rspamd
'''


class RspamdScopeTests(unittest.TestCase):
    def test_image_only_compose_and_override(self):
        before = compose(run("git", "show", BASELINE + ":docker-compose.yml"))
        source = run("git", "show", "cb14bf54:docker-compose.yml")
        after = compose(source)
        before["services"]["rspamd-mailcow"]["image"] = IMAGE
        self.assertEqual(before, after)
        self.assertEqual(compose(source, rspamd_image=OLD_IMAGE)["services"]["rspamd-mailcow"]["image"], OLD_IMAGE)

    def test_footer_change_and_held_paths(self):
        source = (ROOT / "data/conf/rspamd/lua/rspamd.local.lua").read_text()
        self.assertIn("rewrite.new_cte or 'quoted-printable'", source)
        self.assertEqual(source.count("'Content-Transfer-Encoding', new_cte"), 2)
        for path in ("data/conf/postfix", "data/conf/dovecot", "data/conf/nginx", "data/web/inc/init_db.inc.php"):
            self.assertEqual(run("git", "diff", BASELINE, "--", path), "")
        run("bash", "-n", "helper-scripts/maintenance/2026-10-rspamd.sh")


@unittest.skipUnless(os.getenv("MAILCOW_TEST_RSPAMD_RUNTIME") == "1", "Enable isolated Rspamd mail fixtures")
class RspamdRuntimeTests(unittest.TestCase):
    def test_old_and_new_mail_and_footer(self):
        prefix = "mailcow-rspamd-fixture-" + uuid.uuid4().hex[:10]
        network = prefix + "-net"
        containers = []
        run("docker", "network", "create", "--internal", network)
        try:
            with tempfile.TemporaryDirectory(prefix=prefix) as directory:
                fixture = Path(directory)
                (fixture / "router.php").write_text("<?php header('Content-Type: application/json'); echo json_encode(['html'=>'<p>Fixture footer</p>','plain'=>'Fixture footer','skip_replies'=>0]);")
                redis = prefix + "-redis"
                containers.append(redis)
                run("docker", "run", "-d", "--name", redis, "--network", network, "--network-alias", "redis", "--network-alias", "redis-mailcow", REDIS, "redis-server", "--save", "", "--appendonly", "no")
                php = prefix + "-http"
                containers.append(php)
                run("docker", "run", "-d", "--name", php, "--network", network, "--network-alias", "nginx", "--mount", "type=bind,src={},dst=/fixture,readonly".format(fixture), "--entrypoint", "php", PHP, "-S", "0.0.0.0:8081", "/fixture/router.php")
                for index, image in enumerate((OLD_IMAGE, IMAGE)):
                    name = prefix + "-" + str(index)
                    containers.append(name)
                    run("docker", "run", "-d", "--name", name, "--network", network,
                        "--add-host", "rspamd:127.0.0.1", "--add-host", "dovecot:127.0.0.1",
                        "--add-host", "clamd:127.0.0.1", "--add-host", "olefy:127.0.0.1",
                        "--mount", "type=bind,src={},dst=/fixture,readonly".format(ROOT / "data/conf/rspamd"),
                        "--entrypoint", "bash", image, "-ec", BOOTSTRAP)
                    for attempt in range(30):
                        result = subprocess.run(["docker", "exec", name, "rspamc", "-h", "127.0.0.1:11333", "-t", "2", "-E", "-j"], capture_output=True, text=True)
                        if result.returncode == 0:
                            break
                        time.sleep(1)
                    else:
                        logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
                        self.fail(logs.stdout + logs.stderr)
                    settings = '{"symbols_enabled":["MOO_FOOTER","MAILCOW_AUTH"]}'
                    for encoding, body in (("7bit", "Plain fixture text."), ("8bit", "Unicode caf\u00e9 fixture."), ("quoted-printable", "Quoted caf=C3=A9 fixture.")):
                        message = "From: Fixture <fixture@example.test>\r\nTo: receiver@example.test\r\nSubject: Offline footer fixture\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: " + encoding + "\r\n\r\n" + body + "\r\n"
                        output = run("docker", "exec", "-i", name, "rspamc", "-h", "127.0.0.1:11333", "-t", "10", "-u", "fixture@example.test", "-F", "fixture@example.test", "-r", "receiver@example.test", "--settings", settings, "-m", input=message)
                        parsed = email.message_from_string(output, policy=policy.default)
                        content = parsed.get_content()
                        self.assertIn("Fixture footer", content, output)
                        self.assertNotIn("=C3=A9", content)
                        self.assertNotIn("\ufffd", content)
                    gtube = "From: spam@example.test\r\nTo: receiver@example.test\r\nSubject: GTUBE\r\n\r\nXJS*C4JDBQADN1.NSBN3*2IDNEN*GTUBE-STANDARD-ANTI-UBE-TEST-EMAIL*C.34X\r\n"
                    report = json.loads(run("docker", "exec", "-i", name, "rspamc", "-h", "127.0.0.1:11333", "-j", "--settings", settings, input=gtube))
                    self.assertEqual(report["action"], "reject", report)
                    run("docker", "stop", name)
        finally:
            for name in reversed(containers):
                subprocess.run(["docker", "rm", "-f", name], capture_output=True)
            subprocess.run(["docker", "network", "rm", network], capture_output=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
