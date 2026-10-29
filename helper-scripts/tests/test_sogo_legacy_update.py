"""SOGo-only stage and offline startup-fixture checks, with no production data.

Runtime startup uses the actual packaged bootstrap but stubs SQL, socket probes,
and the final daemon handoff. This verifies generated configuration and assets,
not real database compatibility, SSO, mail delivery, or Outlook behavior.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile
import unittest
import uuid

from test_phpfpm_legacy_update import ROOT, compose, run


BASELINE = "f42caf12"
STAGE = "4d1a89d2"
OLD_IMAGE = "ghcr.io/mailcow/sogo:5.12.9-1"
IMAGE = "ghcr.io/mailcow/sogo:5.12.12-1@sha256:dddbb48cbfbd0dd984953fd69e45ed3b33d157665f0ac3df9c0237876ebe8ae0"
ASSETS = {
    "custom-theme.js": "js/theme.js",
    "custom-sogo.js": "js/custom-sogo.js",
    "theme-default.css": "css/theme-default.css",
}


class SogoComposeTests(unittest.TestCase):
    def test_only_sogo_image_changes(self):
        old = compose(run("git", "show", BASELINE + ":docker-compose.yml"))
        new = compose(run("git", "show", STAGE + ":docker-compose.yml"))
        old_image = old["services"]["sogo-mailcow"].pop("image")
        new_image = new["services"]["sogo-mailcow"].pop("image")
        self.assertEqual(old_image, OLD_IMAGE)
        self.assertEqual(new_image, IMAGE)
        self.assertEqual(old, new)

    def test_image_rollback_and_retry(self):
        source = run("git", "show", STAGE + ":docker-compose.yml")
        expected = compose(source)
        rollback = compose(source, sogo_image=OLD_IMAGE)
        expected["services"]["sogo-mailcow"]["image"] = OLD_IMAGE
        self.assertEqual(rollback, expected)
        self.assertEqual(compose(source, sogo_image=""), compose(source))

    def test_authentication_schema_theme_and_routes_are_unchanged(self):
        for path in (
            "data/conf/sogo/sogo.conf", "data/conf/sogo/plist_ldap",
            "data/conf/sogo/custom-theme.js", "data/conf/sogo/custom-sogo.js",
            "data/conf/sogo/theme-default.css", "data/web/inc/init_db.inc.php",
            "data/conf/nginx/templates/sites-default.conf.j2",
            "data/conf/dovecot/auth/passwd-verify.lua",
        ):
            with self.subTest(path=path):
                self.assertEqual((ROOT / path).read_bytes(), subprocess.check_output(
                    ["git", "show", BASELINE + ":" + path], cwd=ROOT))
        self.assertTrue(os.access(ROOT / "data/conf/sogo/plist_ldap.sh", os.X_OK))
        run("bash", "-n", "data/conf/sogo/plist_ldap.sh")

    def test_runbook_commands_parse_and_preflight_never_runs_full_bootstrap(self):
        doc = (ROOT / "helper-scripts/maintenance/2026-10-sogo.md").read_text()
        blocks = re.findall(r"```sh\n(.*?)\n```", doc, re.DOTALL)
        self.assertGreaterEqual(len(blocks), 2)
        for block in blocks:
            run("bash", "-n", input=block)
        self.assertIn("cmp \"$RECOVERY_DIR/old-startup.sha256\"", doc)
        self.assertIn("Existing untracked LDAP script found; stop for review.", doc)
        self.assertNotIn("run --rm --no-deps --pull", doc)
        self.assertNotIn("supervisorctl", doc)
        self.assertNotIn("docker compose run", doc)
        checks = [line.strip() for line in doc.splitlines()
                  if line.strip().startswith("docker run ")]
        self.assertEqual(len(checks), 2)
        for check in checks:
            self.assertIn("--network=none", check)
            self.assertIn("--pull=never", check)
            self.assertNotIn("/var/run/mysqld", check)
            self.assertNotIn("/sogo_web", check)
        self.assertEqual(checks[1].count(",readonly\""), 2)


@unittest.skipUnless(os.getenv("MAILCOW_TEST_SOGO_RUNTIME") == "1",
                     "Set MAILCOW_TEST_SOGO_RUNTIME=1 for offline startup fixtures")
class SogoRuntimeTests(unittest.TestCase):
    def test_documented_preflight_runs_without_compose_network_or_volumes(self):
        doc = (ROOT / "helper-scripts/maintenance/2026-10-sogo.md").read_text()
        checks = [line.strip() for line in doc.splitlines()
                  if line.strip().startswith("docker run ")]
        with tempfile.TemporaryDirectory(prefix="mailcow-sogo-preflight-") as directory:
            env = os.environ.copy()
            env.update({"SOGO_TARGET": IMAGE, "RECOVERY_DIR": directory,
                        "PWD": str(ROOT)})
            for check in checks:
                run("bash", "-euc", check, env=env)
            actual = (Path(directory) / "new-startup.sha256").read_text()
            expected = self.container(OLD_IMAGE, ["-ec",
                "sha256sum /bootstrap-sogo.sh /docker-entrypoint.sh /etc/supervisor/supervisord.conf"])
            self.assertEqual(actual, expected)

    def container(self, image, args, mounts=(), env=()):
        name = "mailcow-sogo-check-" + uuid.uuid4().hex
        command = ["docker", "run", "--rm", "--name", name, "--pull=never", "--network=none"]
        if os.getenv("MAILCOW_TEST_PLATFORM"):
            command += ["--platform", os.environ["MAILCOW_TEST_PLATFORM"]]
        for source, target in mounts:
            command += ["--mount", "type=bind,src={},dst={},readonly".format(source, target)]
        for value in env:
            command += ["--env", value]
        try:
            return run(*command, "--entrypoint", "bash", image, *args)
        except BaseException:
            subprocess.run(["docker", "stop", "--time", "1", name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            raise

    def test_packaged_startup_matches_previous_image(self):
        script = "sha256sum /bootstrap-sogo.sh /docker-entrypoint.sh /etc/supervisor/supervisord.conf"
        self.assertEqual(self.container(OLD_IMAGE, ["-ec", script]),
                         self.container(IMAGE, ["-ec", script]))
        report = self.container(IMAGE, ["-ec", """
            bash -n /bootstrap-sogo.sh
            test -d /usr/local/lib/GNUstep/SOGo/ActiveSync.SOGo
            test -x /usr/sbin/sogo-tool
            test -x /usr/sbin/sogo-ealarms-notify
            ldd /usr/local/sbin/sogod > /tmp/sogo-libraries
            ! grep -q 'not found' /tmp/sogo-libraries
            grep -aom1 '5[.]12[.]12' /usr/local/sbin/sogod /usr/local/lib/sogo/libSOGo.so.5
        """])
        self.assertIn("5.12.12", report)

    def test_ldap_adapter_preserves_template_and_rejects_missing_arguments(self):
        with tempfile.TemporaryDirectory(prefix="mailcow-ldap-fixture-") as directory:
            template = Path(directory) / "plist_ldap"
            template.write_text('<dict><key>domain</key><string>${line}</string><key>gal</key><string>${gal}</string></dict>\n')
            mounts = [(template, "/etc/sogo/plist_ldap"),
                      (ROOT / "data/conf/sogo/plist_ldap.sh", "/etc/sogo/plist_ldap.sh")]
            output = self.container(IMAGE, ["/etc/sogo/plist_ldap.sh", "example.test", "YES"], mounts)
            value = plistlib.loads(('<?xml version="1.0"?><plist version="1.0">' + output + '</plist>').encode())
            self.assertEqual(value, {"domain": "example.test", "gal": "YES"})
            self.container(IMAGE, ["-ec", "if /etc/sogo/plist_ldap.sh; then exit 1; fi"], mounts)

    def startup_fixture(self, image, master="y"):
        with tempfile.TemporaryDirectory(prefix="mailcow-sogo-fixture-") as directory:
            binaries = Path(directory)
            stubs = {
                "mariadb-admin": "#!/bin/sh\nexit 0\n",
                "nc": "#!/bin/sh\nexit 1\n",
                "mariadb": """#!/bin/sh
printf '%s\\n' "$*" >> /tmp/sogo-queries
case "$*" in
  *'SELECT version FROM versions'*) printf '20112024_1105\\n' ;;
  *'SELECT domain, CASE gal'*) printf 'example.test\\tYES\\n' ;;
  *'DROP TRIGGER IF EXISTS sogo_update_password'*) : ;;
  *) echo 'Unexpected fixture SQL' >&2; exit 1 ;;
esac
""",
                "gosu": """#!/bin/sh
test "$*" = 'sogo /usr/sbin/sogod' || exit 1
python3 -c 'import json,base64,hashlib; from pathlib import Path; print(json.dumps({"plist":base64.b64encode(Path("/var/lib/sogo/GNUstep/Defaults/sogod.plist").read_bytes()).decode(),"queries":Path("/tmp/sogo-queries").read_text(),"assets":{p:hashlib.sha256(Path("/sogo_web/WebServerResources/"+p).read_bytes()).hexdigest() for p in ["js/theme.js","js/custom-sogo.js","css/theme-default.css"]}}))'
""",
            }
            for name, content in stubs.items():
                path = binaries / name
                path.write_text(content)
                path.chmod(0o755)
            service = compose((ROOT / "docker-compose.yml").read_text())["services"]["sogo-mailcow"]
            mounts = [(binaries, "/fixture/bin")]
            for mount in service["volumes"]:
                if mount["type"] == "bind" and mount["target"] != "/hooks":
                    mounts.append((mount["source"], mount["target"]))
            output = self.container(image, ["-ec", "mkdir -p /sogo_web /sogo_backup; exec bash /bootstrap-sogo.sh"], mounts, [
                "PATH=/fixture/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "DBUSER=fixture", "DBPASS=fixture-only", "DBNAME=fixture", "MASTER=" + master,
                "IPV4_NETWORK=172.22.1", "MAILCOW_PASS_SCHEME=BLF-CRYPT", "TZ=America/New_York",
            ])
            result = json.loads(output.splitlines()[-1])
            result["plist"] = plistlib.loads(base64.b64decode(result["plist"]))
            return result

    def test_generated_profile_and_copied_theme_match_previous_image(self):
        old = self.startup_fixture(OLD_IMAGE)
        new = self.startup_fixture(IMAGE)
        for value in (old, new):
            self.assertTrue(value["plist"].pop("SOGoEncryptionKey"))
        self.assertEqual(old, new)
        profile = new["plist"]
        self.assertEqual(profile["SOGoTrustProxyAuthentication"], "YES")
        self.assertIn("172.22.1.250:143", profile["SOGoIMAPServer"])
        self.assertIn("172.22.1.253:588", profile["SOGoSMTPServer"])
        self.assertIn("_sogo_static_view", profile["domains"]["example.test"]["SOGoUserSources"][0]["viewURL"])
        self.assertNotRegex(new["queries"], r"CREATE VIEW|ALTER TABLE|CREATE TRIGGER")
        for source, target in ASSETS.items():
            self.assertEqual(new["assets"][target], hashlib.sha256((ROOT / "data/conf/sogo" / source).read_bytes()).hexdigest())

    def test_replica_startup_does_not_drop_trigger(self):
        replica = self.startup_fixture(IMAGE, master="n")
        self.assertNotIn("DROP TRIGGER", replica["queries"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
