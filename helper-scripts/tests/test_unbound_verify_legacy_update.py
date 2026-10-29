"""Exercise actual verification scripts with deterministic Docker responses."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_phpfpm_legacy_update import ROOT, run

IMAGE = "ghcr.io/mailcow/unbound:1.26.2-1@sha256:016bd7056ac86ef3f43ae05d38b7bfa0c59afed69ffac1eab30ea00e0850cb8b"
MOCK = r'''#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$FIXTURE_CALLS"
case "$*" in
  'compose config --quiet') exit 0 ;;
  'compose config --images unbound-mailcow') printf '%s\n' "$FIXTURE_IMAGE"; exit 0 ;;
  'compose ps -q unbound-mailcow') echo fixture-container; exit 0 ;;
  'inspect --format '*)
    if [ "$FIXTURE_CASE" = wrong_image ]; then echo sha256:older; else echo sha256:fixture; fi
    exit 0 ;;
  'image inspect '*) echo sha256:fixture; exit 0 ;;
  'compose ps '*|'compose logs '*) exit 0 ;;
  'compose exec -T postfix-mailcow getent '*)
    if [ "$FIXTURE_CASE" = client_failure ]; then exit 2; fi
    echo '192.0.2.9 STREAM gmail.com'; exit 0 ;;
  'compose exec -T rspamd-mailcow getent '*) echo '192.0.2.9 STREAM gmail.com'; exit 0 ;;
  'compose exec -T unbound-mailcow dig '*) ;;
  *) echo "Unexpected operation: $*" >&2; exit 97 ;;
esac
domain=$7
status=NOERROR
flags='qr rd ra ad'
answer=1
if [ "$domain" = cloudflare.com ]; then
  if [ "$FIXTURE_CASE" = missing_ad ]; then flags='qr rd ra'; fi
else
  if [ "$FIXTURE_CASE" = all_timeout ] || { [ "$FIXTURE_CASE" = fallback ] && [ "$domain" = dnssec-failed.org ]; }; then
    echo ';; communications error to 127.0.0.1#53: timed out'; exit 9
  fi
  if [[ " $* " == *' +cdflag '* ]]; then
    flags='qr rd ra cd'
    if [ "$FIXTURE_CASE" = no_control ]; then status=SERVFAIL; answer=0; fi
    if [ "$FIXTURE_CASE" = no_control_a ]; then answer=0; fi
  elif [ "$FIXTURE_CASE" != fail_open ]; then
    if [ "$FIXTURE_CASE" = transient ] && [ ! -e "$FIXTURE_COUNTER" ]; then
      : > "$FIXTURE_COUNTER"
      echo ';; no servers could be reached'; exit 9
    fi
    status=SERVFAIL
    flags='qr rd ra'
    answer=0
  fi
fi
printf ';; ->>HEADER<<- opcode: QUERY, status: %s, id: 123\n' "$status"
printf ';; flags: %s; QUERY: 1, ANSWER: %s, AUTHORITY: 0, ADDITIONAL: 1\n' "$flags" "$answer"
if [ "$answer" -eq 1 ]; then printf '%s. 60 IN A 192.0.2.9\n' "$domain"; fi
'''


class UnboundVerificationTests(unittest.TestCase):
    def fixture(self, scenario, mode="verify"):
        with tempfile.TemporaryDirectory(prefix="mailcow-unbound-verify-") as directory:
            folder = Path(directory)
            tools = {
                "docker": MOCK,
                "git": "#!/bin/sh\nprintf '%s\\n' feature/october-2026-next-unbound\n",
                "sleep": "#!/bin/sh\nexit 0\n",
            }
            for name, source in tools.items():
                path = folder / name
                path.write_text(source)
                path.chmod(0o700)
            env = os.environ.copy()
            env.update(PATH=str(folder) + os.pathsep + env["PATH"], FIXTURE_CASE=scenario,
                       FIXTURE_CALLS=str(folder / "calls"), FIXTURE_COUNTER=str(folder / "counter"),
                       FIXTURE_IMAGE=IMAGE)
            result = subprocess.run(["bash", "helper-scripts/maintenance/2026-10-unbound.sh", mode],
                                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=15)
            calls = (folder / "calls").read_text()
            for forbidden in ("image tag", " pull ", "compose up", "compose restart", "compose stop", "docker run"):
                self.assertNotIn(forbidden, calls)
            return result, calls

    def test_verify_passes_paired_dnssec_checks_without_replacement(self):
        result, calls = self.fixture("good")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Unbound DNS verification passed", result.stdout)
        self.assertIn("+cdflag +time=15", calls)
        self.assertNotIn("brokendnssec.net", calls)

    def test_unavailable_domain_uses_paired_fallback(self):
        result, calls = self.fixture("fallback")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("brokendnssec.net", calls)
        self.assertIn("INCONCLUSIVE: dnssec-failed.org", result.stderr)

    def test_timeouts_never_count_as_rejection(self):
        result, _ = self.fixture("all_timeout")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("negative DNSSEC verification remains inconclusive", result.stderr)
        self.assertIn("Exit code: 9", result.stdout)

    def test_accepted_bogus_answers_fail(self):
        result, _ = self.fixture("fail_open")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("verification passed", result.stdout)

    def test_servfail_without_successful_control_cannot_pass(self):
        for scenario in ("no_control", "no_control_a"):
            with self.subTest(scenario=scenario):
                result, _ = self.fixture(scenario)
                self.assertNotEqual(result.returncode, 0)

    def test_positive_answer_requires_ad(self):
        result, _ = self.fixture("missing_ad")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("validated positive answer was not obtained", result.stderr)

    def test_incomplete_rejection_query_retries_once(self):
        result, calls = self.fixture("transient")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("retrying this query once", result.stderr)
        self.assertEqual(calls.count("dnssec-failed.org A +dnssec +time=15"), 2)

    def test_client_lookup_failure_stops_acceptance(self):
        result, _ = self.fixture("client_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("postfix-mailcow DNS lookup failed", result.stderr)

    def test_wrong_running_image_cannot_be_verified(self):
        result, calls = self.fixture("wrong_image")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(" dig ", calls)
        self.assertIn("selected Unbound image to be running", result.stderr)

    def test_repeat_apply_preserves_original_recovery_record(self):
        result, _ = self.fixture("good", "apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ORIGINAL recovery record", result.stderr)

    def test_verifier_syntax(self):
        run("bash", "-n", "helper-scripts/maintenance/2026-10-unbound-verify.sh")


if __name__ == "__main__":
    unittest.main(verbosity=2)
