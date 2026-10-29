"""PHP-stage regression checks; runtime checks use disposable, offline containers.

Run with Python 3 and Docker Compose installed. Set MAILCOW_TEST_PHP_RUNTIME=1
to exercise a previously pulled image, and MAILCOW_TEST_PLATFORM=linux/amd64
to check the server architecture on an ARM workstation. No production services,
Docker sockets, database volumes, secrets, or host ports are mounted in tests.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import time
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[2]
BASELINE = "925ba011"
IMAGE = (
    "ghcr.io/mailcow/phpfpm:8.2.35-1@"
    "sha256:f8fe320173eb99afeb3cfb65ecb3b45c92d7a56c9890a516efbcb13e5ca647fa"
)
ENTRYPOINT = "data/Dockerfiles/phpfpm/docker-entrypoint.sh"
INI_DIR = ROOT / "data/conf/phpfpm/php-conf.d"


def run(*args, **kwargs):
    result = subprocess.run(
        args, cwd=ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=180, **kwargs
    )
    if result.returncode:
        raise AssertionError(
            "Command failed ({}):\n{}\n{}".format(
                result.returncode, result.stdout, result.stderr
            )
        )
    return result.stdout


def baseline(path):
    return run("git", "show", BASELINE + ":" + path)


def compose(source, image=None, nginx_image=None, sogo_image=None, clamd_image=None, redis_image=None, unbound_image=None, rspamd_image=None, dockerapi_image=None, olefy_image=None, acme_image=None):
    env = os.environ.copy()
    env.pop("PHPFPM_IMAGE", None)
    env.pop("NGINX_IMAGE", None)
    env.pop("SOGO_IMAGE", None)
    env.pop("CLAMD_IMAGE", None)
    env.pop("REDIS_IMAGE", None)
    env.pop("UNBOUND_IMAGE", None)
    env.pop("RSPAMD_IMAGE", None)
    env.pop("DOCKERAPI_IMAGE", None)
    env.pop("OLEFY_IMAGE", None)
    env.pop("ACME_IMAGE", None)
    env.pop("COMPOSE_FILE", None)
    env.update({
        "TZ": "America/New_York", "DBNAME": "fixture", "DBUSER": "fixture",
        "DBPASS": "fixture-only", "DBROOT": "fixture-only",
        "REDISPASS": "fixture-only", "MAILCOW_HOSTNAME": "mail.example.test",
        "ADDITIONAL_SAN": "",
    })
    if image is not None:
        env["PHPFPM_IMAGE"] = image
    if nginx_image is not None:
        env["NGINX_IMAGE"] = nginx_image
    if sogo_image is not None:
        env["SOGO_IMAGE"] = sogo_image
    if clamd_image is not None:
        env["CLAMD_IMAGE"] = clamd_image
    if redis_image is not None:
        env["REDIS_IMAGE"] = redis_image
    if unbound_image is not None:
        env["UNBOUND_IMAGE"] = unbound_image
    if rspamd_image is not None:
        env["RSPAMD_IMAGE"] = rspamd_image
    if dockerapi_image is not None:
        env["DOCKERAPI_IMAGE"] = dockerapi_image
    if olefy_image is not None:
        env["OLEFY_IMAGE"] = olefy_image
    if acme_image is not None:
        env["ACME_IMAGE"] = acme_image
    return json.loads(run(
        "docker", "compose", "--env-file", os.devnull,
        "--project-directory", str(ROOT), "-f", "-", "config", "--format", "json",
        input=source, env=env
    ))


class ComposeRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Seal the PHP stage; the Nginx tests verify later stages preserve it exactly.
        cls.source = run("git", "show", "5cabaf3c:docker-compose.yml")
        cls.before = compose(baseline("docker-compose.yml"))
        cls.after = compose(cls.source)

    def test_only_php_service_changes(self):
        before = json.loads(json.dumps(self.before))
        after = json.loads(json.dumps(self.after))
        old_php = before["services"].pop("php-fpm-mailcow")
        new_php = after["services"].pop("php-fpm-mailcow")
        self.assertEqual(before, after)
        self.assertEqual(old_php.pop("image"), "ghcr.io/mailcow/phpfpm:8.2.29-2")
        self.assertEqual(new_php.pop("image"), IMAGE)
        mounts = new_php["volumes"]
        override = next(m for m in mounts if m["target"] == "/docker-entrypoint.sh")
        self.assertEqual(override["type"], "bind")
        self.assertTrue(override["read_only"])
        self.assertEqual(Path(override["source"]), ROOT / ENTRYPOINT)
        mounts.remove(override)
        self.assertEqual(old_php, new_php)

    def test_image_override_and_retry(self):
        rollback = compose(self.source, "ghcr.io/mailcow/phpfpm:8.2.29-2")
        expected = json.loads(json.dumps(self.after))
        expected["services"]["php-fpm-mailcow"]["image"] = "ghcr.io/mailcow/phpfpm:8.2.29-2"
        self.assertEqual(rollback, expected)
        self.assertEqual(compose(self.source, ""), self.after)
        self.assertEqual(compose(self.source), self.after)

    def test_legacy_startup_schema_and_auth_files_are_unchanged(self):
        for path in (
            ENTRYPOINT,
            "data/web/inc/init_db.inc.php",
            "data/conf/dovecot/auth/passwd-verify.lua",
            "data/conf/nginx/templates/sites-default.conf.j2",
            "data/conf/phpfpm/php-fpm.d/pools.conf",
        ):
            with self.subTest(path=path):
                self.assertEqual((ROOT / path).read_bytes(),
                                 subprocess.check_output(
                                     ["git", "show", BASELINE + ":" + path], cwd=ROOT))
        script = (ROOT / ENTRYPOINT).read_text()
        self.assertIn("DELETE FROM spamalias WHERE validity < UNIX_TIMESTAMP();", script)
        self.assertNotIn("permanent", script)
        self.assertTrue(os.access(ROOT / ENTRYPOINT, os.X_OK))

    def test_only_upload_progress_setting_is_added(self):
        path = "data/conf/phpfpm/php-conf.d/other.ini"
        self.assertEqual((ROOT / path).read_text(),
                         baseline(path) + "session.upload_progress.enabled = Off\n")

    def test_runbook_shell_commands_parse(self):
        runbook = (ROOT / "helper-scripts/maintenance/2026-10-php.md").read_text()
        blocks = re.findall(r"```sh\n(.*?)\n```", runbook, re.DOTALL)
        self.assertGreater(len(blocks), 5)
        for number, block in enumerate(blocks):
            with self.subTest(block=number):
                run("bash", "-n", input=block)

    def test_runbook_selects_php_without_dependency_images(self):
        selector = r"/^ghcr[.]io\/mailcow\/phpfpm[:@]/"
        runbook = (ROOT / "helper-scripts/maintenance/2026-10-php.md").read_text()
        self.assertIn("awk '" + selector + "'", runbook)
        images = "ghcr.io/mailcow/netfilter:1.64\n" + IMAGE + "\nredis:7.4.8-alpine\n"
        self.assertEqual(run("awk", selector, input=images).strip(), IMAGE)
        self.assertEqual(run("awk", selector, input="redis:7.4.8-alpine\n"), "")


@unittest.skipUnless(os.getenv("MAILCOW_TEST_PHP_RUNTIME") == "1",
                     "Set MAILCOW_TEST_PHP_RUNTIME=1 for offline image checks")
class PhpRuntimeTests(unittest.TestCase):
    def container(self, entrypoint, *args, user=None, legacy_startup=True, network="none"):
        name = "mailcow-php-check-" + uuid.uuid4().hex
        command = ["docker", "run", "--name", name, "--rm", "--pull=never", "--network", network,
                   "--read-only", "--tmpfs", "/tmp", "--cap-drop=ALL",
                   "--security-opt", "no-new-privileges"]
        if os.getenv("MAILCOW_TEST_PLATFORM"):
            command += ["--platform", os.environ["MAILCOW_TEST_PLATFORM"]]
        if user:
            command += ["--user", user]
        command += ["--mount", "type=bind,src={},dst=/web,readonly".format(ROOT / "data/web"),
                    "--mount", "type=bind,src={},dst=/usr/local/etc/php-fpm.d/z-pools.conf,readonly".format(
                        ROOT / "data/conf/phpfpm/php-fpm.d/pools.conf")]
        if legacy_startup:
            command += ["--mount", "type=bind,src={},dst=/docker-entrypoint.sh,readonly".format(ROOT / ENTRYPOINT)]
        for ini_name, target in (("other.ini", "zzz-other.ini"),
                             ("upload.ini", "upload.ini"),
                             ("opcache-recommended.ini", "opcache-recommended.ini")):
            command += ["--mount", "type=bind,src={},dst=/usr/local/etc/php/conf.d/{},readonly".format(
                INI_DIR / ini_name, target)]
        try:
            return run(*command, "--entrypoint", entrypoint, IMAGE, *args)
        except BaseException:
            subprocess.run(["docker", "stop", "--time", "1", name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            raise

    def test_actual_runtime_and_extensions(self):
        values = json.loads(self.container("php", "-r", """
            echo json_encode([
                'version' => PHP_VERSION,
                'upload_progress' => ini_get('session.upload_progress.enabled'),
                'modules' => get_loaded_extensions(),
                'drivers' => PDO::getAvailableDrivers()
            ]);
        """))
        self.assertEqual(values["version"], "8.2.35")
        self.assertIn(values["upload_progress"], ("", "0"))
        self.assertIn("mysql", values["drivers"])
        required = {"apcu", "imagick", "mailparse", "memcached", "redis", "intl",
                    "gd", "gettext", "ldap", "openssl", "mbstring", "imap", "zip",
                    "soap", "sockets", "bcmath", "gmp", "session"}
        self.assertFalse(required - set(values["modules"]))

    def test_fpm_and_legacy_entrypoint_syntax(self):
        self.container("php-fpm", "-t", "-d", "date.timezone=America/New_York", "-d", "expose_php=0")
        self.container("bash", "-n", "/docker-entrypoint.sh")
        self.container("sh", "-ec", """
            for tool in bash curl jq mariadb mariadb-admin redis-cli find chown; do
                command -v "$tool" > /dev/null
            done
        """)

    def test_shipped_startup_difference_is_schema_specific(self):
        shipped = self.container("cat", "/docker-entrypoint.sh", legacy_startup=False)
        legacy_sql = "DELETE FROM spamalias WHERE validity < UNIX_TIMESTAMP();"
        upstream_sql = "DELETE FROM spamalias WHERE validity < UNIX_TIMESTAMP() AND permanent = 0;"
        self.assertEqual(shipped.count(upstream_sql), 1)
        self.assertEqual(shipped.replace(upstream_sql, legacy_sql),
                         (ROOT / ENTRYPOINT).read_text())

    def test_web_worker_can_read_mounted_files(self):
        self.container("sh", "-ec", """
            test -x /docker-entrypoint.sh
            test -r /web/inc/functions.inc.php
            test -r /usr/local/etc/php-fpm.d/z-pools.conf
            test -r /usr/local/etc/php/conf.d/zzz-other.ini
        """, user="www-data")

    def test_first_party_php_syntax(self):
        result = self.container("sh", "-ec", """
            find /web -type f -name '*.php' ! -path '/web/inc/lib/*' -print0 |
                xargs -0 -n 1 php -l
        """)
        self.assertNotIn("Parse error", result)
        self.assertGreater(result.count("No syntax errors"), 50)

    def test_password_and_template_paths(self):
        self.container("php", "-r", r"""
            require '/web/inc/lib/vendor/autoload.php';
            require '/web/inc/functions.inc.php';
            $default_pass_scheme = 'BLF-CRYPT';
            $hash = hash_password('fixture-password-only');
            if (substr($hash, 0, 11) !== '{BLF-CRYPT}' ||
                !password_verify('fixture-password-only', substr($hash, 11)) ||
                password_verify('incorrect-password', substr($hash, 11))) { exit(1); }
            $loader = new Twig\Loader\ArrayLoader(['test' => '{{ value }}']);
            $twig = new Twig\Environment($loader, ['autoescape' => 'html']);
            if ($twig->render('test', ['value' => '<unsafe>']) !== '&lt;unsafe&gt;') { exit(2); }
            if (!class_exists('Redis') || !function_exists('imap_open') ||
                !valid_network('192.0.2.0/24') || valid_network('not-a-network')) { exit(3); }
        """)

    @unittest.skipUnless(os.getenv("MAILCOW_TEST_PHP_DATABASE") == "1",
                         "Set MAILCOW_TEST_PHP_DATABASE=1 for a disposable MariaDB fixture")
    def test_legacy_schema_events_and_php_database_access(self):
        database = run(
            "docker", "run", "--detach", "--rm", "--pull=never", "--network=none",
            "--tmpfs", "/var/lib/mysql", "--tmpfs", "/run/mysqld",
            "--env", "MARIADB_ROOT_PASSWORD=fixture-only",
            "--env", "MARIADB_DATABASE=fixture", "--env", "MARIADB_USER=fixture",
            "--env", "MARIADB_PASSWORD=fixture-only", "mariadb:10.11"
        ).strip()
        try:
            for attempt in range(60):
                ready = subprocess.run(
                    ["docker", "exec", database, "mariadb", "--host=127.0.0.1",
                     "--user=fixture", "--password=fixture-only", "--execute=SELECT 1", "fixture"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10
                )
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                self.fail("Disposable MariaDB did not become ready")

            def sql(statement):
                return run("docker", "exec", "-i", database, "mariadb",
                           "--user=fixture", "--password=fixture-only", "--batch",
                           "--skip-column-names", "fixture", input=statement)

            sql("""
                CREATE TABLE spamalias (address VARCHAR(255) PRIMARY KEY, validity BIGINT);
                INSERT INTO spamalias VALUES ('expired@example.test', 1),
                    ('active@example.test', UNIX_TIMESTAMP() + 86400);
                CREATE TABLE mailbox (username VARCHAR(255) PRIMARY KEY);
                CREATE TABLE sasl_log (username VARCHAR(255), service VARCHAR(32), datetime DATETIME);
                CREATE TABLE oauth_refresh_tokens (expires DATETIME);
                CREATE TABLE oauth_access_tokens (expires DATETIME);
                CREATE TABLE oauth_authorization_codes (expires DATETIME);
            """)
            # Exercise the exact SQL heredoc from the retained startup script, including retry.
            script = (ROOT / ENTRYPOINT).read_text()
            events = re.search(r"(?ms)^DROP EVENT IF EXISTS clean_spamalias;.*?(?=^EOF$)", script)
            self.assertIsNotNone(events)
            sql(events.group())
            sql(events.group())
            self.assertEqual(sql("SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA='fixture';").strip(), "3")
            self.assertEqual(sql("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='fixture' AND TABLE_NAME='spamalias' AND COLUMN_NAME='permanent';").strip(), "0")
            self.container("sh", "-ec", """
                mariadb-admin --ssl=false --host=127.0.0.1 --user=fixture --password=fixture-only status --silent
                mariadb --skip-ssl --host=127.0.0.1 --user=fixture --password=fixture-only fixture --execute='SELECT 1'
            """, network="container:" + database)
            self.container("php", "-r", """
                $pdo = new PDO('mysql:host=127.0.0.1;dbname=fixture', 'fixture', 'fixture-only',
                    [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
                $pdo->exec('DELETE FROM spamalias WHERE validity < UNIX_TIMESTAMP()');
                if ($pdo->query('SELECT COUNT(*) FROM spamalias')->fetchColumn() != 1) { exit(1); }
                try {
                    $pdo->exec('DELETE FROM spamalias WHERE validity < UNIX_TIMESTAMP() AND permanent = 0');
                    exit(2);
                } catch (PDOException $error) {
                    if ($error->errorInfo[1] !== 1054) { throw $error; }
                }
            """, network="container:" + database)
            self.assertEqual(sql("SELECT address FROM spamalias;").strip(), "active@example.test")
        finally:
            run("docker", "stop", "--time", "10", database)


if __name__ == "__main__":
    unittest.main(verbosity=2)
