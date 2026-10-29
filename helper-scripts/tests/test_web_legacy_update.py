"""Encoding and OAuth backport fixtures without production database access."""

import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_phpfpm_legacy_update import ROOT, run

BASELINE = "29286ab5"
PHP = "ghcr.io/mailcow/phpfpm:8.2.35-1@sha256:f8fe320173eb99afeb3cfb65ecb3b45c92d7a56c9890a516efbcb13e5ca647fa"


class WebScopeTests(unittest.TestCase):
    def test_proxy_images_schema_and_authentication_unchanged(self):
        for path in ("docker-compose.yml", "data/conf/nginx/templates/sites-default.conf.j2",
                     "data/conf/dovecot/auth/passwd-verify.lua", "data/web/inc/init_db.inc.php",
                     "data/conf/sogo/custom-sogo.js"):
            self.assertEqual((ROOT / path).read_bytes(), subprocess.check_output(
                ["git", "show", BASELINE + ":" + path], cwd=ROOT))

    def test_log_fields_escape_in_actual_postprocessor(self):
        source = (ROOT / "data/web/js/site/debug.js").read_text()
        code = source[source.index("  function process_table_data("):source.index("  $('.add_log_lines')")]
        script = """
const assert = require('assert');
const $ = { each: (items, fn) => items.forEach((item, i) => fn(i, item)) };
function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
""" + code + """
const input = '<img src=x onerror=alert(1)>';
const a = process_table_data([{user:'u',call:'c',msg:input,task:'t',type:'success'}], 'mailcow_ui');
assert(!a[0].msg.includes('<img'));
const b = process_table_data([{username:'u',real_rip:input,service:'imap'}], 'sasl_log_table');
assert(!b[0].real_rip.includes('<img'));
assert.equal(process_table_data([{user:'u',call:'c',msg:null,task:'t',type:'success'}], 'mailcow_ui')[0].msg, null);
"""
        run("node", "-e", script)


@unittest.skipUnless(os.getenv("MAILCOW_TEST_WEB_RUNTIME") == "1", "Enable PHP web fixtures")
class WebPhpTests(unittest.TestCase):
    def php(self, script, mounts=()):
        args = ["docker", "run", "--rm", "--pull=never", "--network=none"]
        for source, target in mounts:
            args += ["--mount", "type=bind,src={},dst={},readonly".format(source, target)]
        return run(*args, "--entrypoint", "php", PHP, "-r", script)

    def test_json_roundtrip_and_dns_export_encoding(self):
        functions = (ROOT / "data/web/inc/functions.inc.php").read_text()
        expression = re.search(r"\$msg = (json_encode\(\$return\['msg'\], [^;]+);", functions).group(1)
        payload = base64.b64encode(json.dumps({"msg": '<tag a="x"> & quote\''}).encode()).decode()
        report = self.php("$return=json_decode(base64_decode('" + payload + "'),true); $msg=" + expression + "; echo json_encode([$msg,json_decode($msg)]);")
        encoded, decoded = json.loads(report)
        self.assertNotIn("<", encoded)
        self.assertEqual(decoded, '<tag a="x"> & quote\'')
        report = self.php("$s='v=TXT \"x&y<z>\"'; $e=htmlspecialchars($s,ENT_QUOTES|ENT_SUBSTITUTE,'UTF-8'); echo json_encode([$e,html_entity_decode($e,ENT_QUOTES|ENT_HTML5,'UTF-8')]);")
        escaped, original = json.loads(report)
        self.assertNotIn("<z>", escaped)
        self.assertEqual(original, 'v=TXT "x&y<z>"')
        dns = (ROOT / "data/web/inc/ajax/dns_diagnostics.php").read_text()
        self.assertIn("html_entity_decode($val, ENT_QUOTES | ENT_HTML5, 'UTF-8')", dns)
        self.assertIn("htmlspecialchars($_GET['domain'], ENT_QUOTES | ENT_SUBSTITUTE", dns)

    def test_oauth_missing_session_user_and_authorized_paths(self):
        bootstrap = r'''<?php
namespace OAuth2 { class Request { static function createFromGlobals() { return new self; } } class Response { function send() {} function getHttpHeader($h) { return 'https://client.example.test/callback'; } } }
namespace {
$_SESSION = json_decode(getenv('FIXTURE_SESSION'), true);
$_POST = ['authorized'=>getenv('FIXTURE_APPROVE')];
$_SERVER['REQUEST_URI'] = '/oauth/authorize.php?client_id=fixture';
$GLOBALS['OAUTH2_FORGET_SESSION_AFTER_LOGIN']=false;
$GLOBALS['handled']=false;
$oauth2_server = new class { function validateAuthorizeRequest($q,$r) { return true; } function handleAuthorizeRequest($q,$r,$ok,$user) { $GLOBALS['handled']=[$ok,$user]; } };
register_shutdown_function(function () { echo json_encode(['handled'=>$GLOBALS['handled']]); });
}
'''
        with tempfile.TemporaryDirectory(prefix="mailcow-oauth-") as directory:
            root = Path(directory)
            (root / "inc").mkdir()
            (root / "inc/prerequisites.inc.php").write_text(bootstrap)
            for session, approve, expected in (
                ({}, "1", False), ({"mailcow_cc_role":"user"}, "1", False),
                ({"mailcow_cc_role":"user","mailcow_cc_username":"fixture@example.test"}, "1", [True,"fixture@example.test"]),
                ({"mailcow_cc_role":"user","mailcow_cc_username":"fixture@example.test"}, "0", [False,"fixture@example.test"]),
            ):
                args = ["docker", "run", "--rm", "--pull=never", "--network=none",
                        "--env", "FIXTURE_SESSION=" + json.dumps(session), "--env", "FIXTURE_APPROVE=" + approve,
                        "--mount", "type=bind,src={},dst=/fixture,readonly".format(root),
                        "--mount", "type=bind,src={},dst=/authorize.php,readonly".format(ROOT / "data/web/oauth/authorize.php")]
                output = run(*args, "--entrypoint", "php", PHP, "-r",
                             "$_SERVER['DOCUMENT_ROOT']='/fixture'; require '/authorize.php';")
                self.assertEqual(json.loads(output)["handled"], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
