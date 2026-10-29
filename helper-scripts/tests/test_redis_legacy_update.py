"""Redis image-only checks and disposable persistence/client fixtures."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import unittest
import uuid

from test_phpfpm_legacy_update import ROOT, compose, run


BASELINE = "2a8e8973"
OLD_IMAGE = "redis:7.4.8-alpine"
IMAGE = "redis:7.4.12-alpine@sha256:338fbfc036dc5517ac0b04d6de21521085935336e565f223406180e9d84166e2"
HELPER = ROOT / "helper-scripts/maintenance/2026-10-redis.sh"


class RedisComposeTests(unittest.TestCase):
    def test_only_redis_image_changes(self):
        old = compose(run("git", "show", BASELINE + ":docker-compose.yml"))
        new = compose((ROOT / "docker-compose.yml").read_text())
        self.assertEqual(old["services"]["redis-mailcow"].pop("image"), OLD_IMAGE)
        self.assertEqual(new["services"]["redis-mailcow"].pop("image"), IMAGE)
        self.assertEqual(old, new)

    def test_image_rollback_and_retry(self):
        source = (ROOT / "docker-compose.yml").read_text()
        expected = compose(source)
        expected["services"]["redis-mailcow"]["image"] = OLD_IMAGE
        self.assertEqual(compose(source, redis_image=OLD_IMAGE), expected)
        self.assertEqual(compose(source, redis_image=""), compose(source))

    def test_configuration_acl_and_related_processes_are_unchanged(self):
        for path in (
            "data/conf/redis/redis-conf.sh", "data/conf/rspamd/local.d/redis.conf",
            "data/conf/sogo/sogo.conf", "data/web/inc/prerequisites.inc.php",
            "data/web/inc/sessions.inc.php", "data/Dockerfiles/netfilter/main.py",
            "data/conf/dovecot/auth/passwd-verify.lua", "data/web/inc/init_db.inc.php",
        ):
            with self.subTest(path=path):
                self.assertEqual((ROOT / path).read_bytes(), subprocess.check_output(
                    ["git", "show", BASELINE + ":" + path], cwd=ROOT))

    def test_handoff_gates_and_backup_before_replacement(self):
        script = HELPER.read_text()
        run("bash", "-n", str(HELPER))
        doc = (ROOT / "helper-scripts/maintenance/2026-10-redis.md").read_text()
        for block in re.findall(r"```sh\n(.*?)\n```", doc, re.DOTALL):
            run("bash", "-n", input=block)
        for gate in ("role:master", "cluster_enabled:0", "CONFIG GET appendonly",
                     "CONFIG GET dbfilename", "PUBSUB NUMSUB F2B_CHANNEL"):
            self.assertIn(gate, script)
        self.assertIn('export REDISCLI_AUTH="$REDISPASS"', script)
        self.assertNotIn("FLUSHALL", script)
        self.assertNotIn("FLUSHDB", script)
        self.assertNotIn("docker compose run", script)
        self.assertLess(script.index("--entrypoint redis-check-rdb"),
                        script.index("\ndocker compose up"))
        self.assertIn("--no-deps --force-recreate --timeout 120 redis-mailcow", script)


@unittest.skipUnless(os.getenv("MAILCOW_TEST_REDIS_RUNTIME") == "1",
                     "Set MAILCOW_TEST_REDIS_RUNTIME=1 for disposable Redis fixtures")
class RedisRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.prefix = "mailcow-redis-fixture-" + uuid.uuid4().hex
        self.volume = self.prefix + "-data"
        self.network = self.prefix + "-network"
        run("docker", "volume", "create", self.volume)
        self.addCleanup(run, "docker", "volume", "rm", self.volume)
        run("docker", "network", "create", "--internal", self.network)
        self.addCleanup(run, "docker", "network", "rm", self.network)

    def start(self, image):
        name = self.prefix + "-" + uuid.uuid4().hex[:8]
        args = ["docker", "run", "--rm", "-d", "--name", name,
                "--pull=never", "--network", self.network,
                "--network-alias", "redis-mailcow", "--env", "REDISPASS=fixture-only",
                "--env", "REDISMASTERPASS=", "--mount", "type=volume,src={},dst=/data".format(self.volume),
                "--mount", "type=bind,src={},dst=/redis-conf.sh,readonly".format(ROOT / "data/conf/redis/redis-conf.sh")]
        if os.getenv("MAILCOW_TEST_PLATFORM"):
            args += ["--platform", os.environ["MAILCOW_TEST_PLATFORM"]]
        run(*args, "--entrypoint", "/bin/sh", image, "/redis-conf.sh")
        self.addCleanup(subprocess.run, ["docker", "stop", "--time", "5", name],
                        capture_output=True, timeout=15)
        for _ in range(30):
            ready = subprocess.run(["docker", "exec", "--env", "REDISCLI_AUTH=fixture-only",
                                    name, "redis-cli", "--raw", "PING"],
                                   capture_output=True, text=True, timeout=10)
            if ready.returncode == 0 and ready.stdout.strip() == "PONG":
                return name
            time.sleep(0.2)
        self.fail(run("docker", "logs", name))

    def cli(self, name, *args):
        return run("docker", "exec", "--env", "REDISCLI_AUTH=fixture-only", name,
                   "redis-cli", "-e", "--raw", *args).strip()

    def test_old_new_old_data_and_expiry(self):
        name = self.start(OLD_IMAGE)
        self.cli(name, "SET", "fixture:string", "preserved", "EX", "300")
        self.cli(name, "HSET", "fixture:hash", "dkim-fixture", "not-a-real-key")
        self.cli(name, "LPUSH", "fixture:list", "first", "second")
        self.cli(name, "SADD", "fixture:set", "member")
        self.cli(name, "ZADD", "fixture:zset", "2", "member")
        self.cli(name, "XADD", "fixture:stream", "1-0", "field", "value")
        self.cli(name, "-n", "1", "SET", "fixture:db1", "preserved-db1")
        self.cli(name, "SAVE")
        run("docker", "stop", "--time", "10", name)
        for image in (IMAGE, OLD_IMAGE):
            name = self.start(image)
            self.assertEqual(self.cli(name, "GET", "fixture:string"), "preserved")
            self.assertGreater(int(self.cli(name, "TTL", "fixture:string")), 200)
            self.assertEqual(self.cli(name, "HGET", "fixture:hash", "dkim-fixture"), "not-a-real-key")
            self.assertEqual(self.cli(name, "LRANGE", "fixture:list", "0", "-1"), "second\nfirst")
            self.assertEqual(self.cli(name, "SMEMBERS", "fixture:set"), "member")
            self.assertEqual(self.cli(name, "ZSCORE", "fixture:zset", "member"), "2")
            self.assertEqual(self.cli(name, "XLEN", "fixture:stream"), "1")
            self.assertEqual(self.cli(name, "-n", "1", "GET", "fixture:db1"), "preserved-db1")
            self.assertEqual(self.cli(name, "INCR", "fixture:roundtrip"), "1" if image == IMAGE else "2")
            self.cli(name, "SAVE")
            run("docker", "stop", "--time", "10", name)

    def test_authentication_quota_acl_and_lua(self):
        name = self.start(IMAGE)
        missing = run("docker", "exec", name, "redis-cli", "--raw", "PING")
        self.assertIn("NOAUTH", missing)
        self.cli(name, "SET", "QW_fixture", "allowed")
        quota = ["docker", "exec", name, "redis-cli", "-e", "--raw", "--user",
                 "quota_notify", "-a", "", "--no-auth-warning"]
        self.assertEqual(run(*quota, "GET", "QW_fixture").strip(), "allowed")
        denied = subprocess.run([*quota, "SET", "QW_fixture", "blocked"],
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("NOPERM", denied.stdout + denied.stderr)
        self.assertEqual(self.cli(name, "EVAL", "return redis.call('INCR', KEYS[1])", "1", "fixture:lua"), "1")

    def test_online_snapshot_and_candidate_checksum_validation(self):
        name = self.start(OLD_IMAGE)
        self.cli(name, "SET", "fixture:backup", "preserved")
        with tempfile.TemporaryDirectory(prefix="mailcow-redis-rdb-") as directory:
            snapshot = Path(directory) / "dump.rdb"
            with snapshot.open("wb") as output:
                exported = subprocess.run(["docker", "exec", name, "sh", "-ec",
                    'export REDISCLI_AUTH="$REDISPASS"; exec timeout 180 redis-cli --rdb -'],
                    stdout=output, stderr=subprocess.PIPE, timeout=180)
            self.assertEqual(exported.returncode, 0, exported.stderr.decode())
            self.assertTrue(snapshot.read_bytes().startswith(b"REDIS"))
            args = ["docker", "run", "--rm", "--pull=never", "--network=none",
                    "--mount", "type=bind,src={},dst=/backup,readonly".format(directory),
                    "--entrypoint", "redis-check-rdb", IMAGE, "/backup/dump.rdb"]
            self.assertIn("RDB looks OK", run(*args))
            snapshot.write_bytes(b"not an RDB snapshot")
            bad = subprocess.run(args, capture_output=True, timeout=15)
            self.assertNotEqual(bad.returncode, 0)

    def test_real_php_rspamd_clients_and_pubsub(self):
        name = self.start(IMAGE)
        for service, image in (
            ("php-fpm-mailcow", "ghcr.io/mailcow/phpfpm:8.2.35-1@sha256:f8fe320173eb99afeb3cfb65ecb3b45c92d7a56c9890a516efbcb13e5ca647fa"),
            ("rspamd-mailcow", "ghcr.io/mailcow/rspamd:3.14.3-1"),
        ):
            line = next(line for line in HELPER.read_text().splitlines()
                        if line.startswith("docker compose exec -T " + service + " ")
                        and "to Redis: PONG" in line)
            command = shlex.split(line)[5:]
            output = run("docker", "run", "--rm", "--pull=never", "--network", self.network,
                         "--env", "REDISPASS=fixture-only", "--entrypoint", command[0], image, *command[1:])
            self.assertIn("to Redis: PONG", output)
        subscriber = subprocess.Popen(["docker", "exec", "--env", "REDISCLI_AUTH=fixture-only", name,
            "timeout", "3", "redis-cli", "--raw", "SUBSCRIBE", "F2B_CHANNEL"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(20):
                if self.cli(name, "PUBSUB", "NUMSUB", "F2B_CHANNEL").endswith("\n1"):
                    break
                time.sleep(0.1)
            self.assertEqual(self.cli(name, "PUBLISH", "F2B_CHANNEL", "harmless-fixture-event"), "1")
            output, _ = subscriber.communicate(timeout=10)
            self.assertIn("harmless-fixture-event", output)
        finally:
            if subscriber.poll() is None:
                subscriber.kill()
                subscriber.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
