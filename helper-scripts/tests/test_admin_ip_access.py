"""Exercise the real login/session code with synthetic accounts and no database/network."""
import base64
import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
PHP = json.loads(os.getenv("MAILCOW_PHP_COMMAND", '["php"]'))


def source(name):
    return base64.b64encode((ROOT / "data/web/inc" / name).read_bytes()).decode()


prerequisites = (ROOT / 'data/web/inc/prerequisites.inc.php').read_text()
remote_ip = prerequisites[prerequisites.index('function get_remote_ip()'):prerequisites.index('// Load core functions first')].strip()


BOOT = r'''
eval(base64_decode('REMOTE_IP'));
$functions = base64_decode('FUNCTIONS');
$functions = str_replace("require_once __DIR__ . '/admin-access.inc.php';", '', $functions);
eval('?>' . base64_decode('POLICY'));
eval('?>' . $functions);
class FixtureStatement {
  public $sql; public $args = [];
  function __construct($sql) {$this->sql = $sql;}
  function execute($args = []) {$this->args = $args; return true;}
  function fetchAll($mode = null) {
    $name = $this->args[':user'] ?? $this->args[':username'] ?? '';
    if (strpos($this->sql, 'FROM `tfa`') !== false) return !empty($GLOBALS['fixture_mfa']) ? [['id'=>1,'key_id'=>'fictional','authmech'=>'webauthn']] : [];
    if ((strpos($this->sql, "`superadmin` = '1'") !== false && $name === 'fixtureadmin') ||
        (strpos($this->sql, "`superadmin` = '0'") !== false && $name === 'fixturedomain') ||
        (strpos($this->sql, 'FROM `mailbox`') !== false && $name === 'user@example.test')) {
      return [['password'=>$GLOBALS['fixture_hash']]];
    }
    return [];
  }
  function fetch($mode = null) {
    if (strpos($this->sql, 'SELECT `superadmin` FROM `admin`') !== false) return $GLOBALS['fixture_role'] === 'user' ? false : ['superadmin'=>$GLOBALS['fixture_role'] === 'admin' ? 1 : 0];
    if (strpos($this->sql, 'SELECT `username` FROM `mailbox`') !== false) return ['username'=>'user@example.test'];
    if (strpos($this->sql, 'FROM `api`') !== false) return ['api_key'=>'fictional', 'skip_ip_check'=>0, 'allow_from'=>$GLOBALS['fixture_api_ip'] ?? $_SERVER['REMOTE_ADDR'], 'access'=>$GLOBALS['fixture_api_access'] ?? 'ro'];
    $rows = $this->fetchAll($mode); return $rows[0] ?? false;
  }
}
class FixtureDatabase {public $queries=0; function prepare($sql) {$this->queries++; return new FixtureStatement($sql);}}
class FixtureRedis {function publish($channel, $message) {return true;}}
$pdo = new FixtureDatabase; $redis = new FixtureRedis;
$fixture_hash = '{BLF-CRYPT}' . password_hash('fictional-password', PASSWORD_BCRYPT);
$ADMIN_IP_ALLOWLIST = ['192.0.2.0/24', '198.51.100.0/25', '203.0.113.24'];
$ADMIN_IP_API_ALLOWLIST = ['127.0.0.1', '::1', '192.0.2.250'];
$_SERVER = ['REMOTE_ADDR'=>'203.0.113.90','REQUEST_METHOD'=>'GET','REQUEST_URI'=>'/admin','HTTP_USER_AGENT'=>'fixture','HTTPS'=>'on'];
$_SESSION = []; $_POST = []; $_GET = []; $_FILES = [];
'''.replace("REMOTE_IP", base64.b64encode(remote_ip.encode()).decode()).replace("FUNCTIONS", source("functions.inc.php")).replace("POLICY", source("admin-access.inc.php"))


def php(code):
    result = subprocess.run(PHP, input="<?php\n" + BOOT + "\n" + code, text=True, capture_output=True, check=True)
    return json.loads(result.stdout.strip())


class AdministratorIpAccessTests(unittest.TestCase):
    def test_network_boundaries_default_ipv6_and_header_spoofing(self):
        report = php(r'''
$out=[];
foreach (['192.0.2.1','192.0.2.255','198.51.100.0','198.51.100.127','198.51.100.128','203.0.113.24','203.0.113.25','::1','not-an-address'] as $ip) {
  $_SERVER['REMOTE_ADDR']=$ip; $out[$ip]=mailcow_admin_ip_allowed();
}
$_SERVER['REMOTE_ADDR']='203.0.113.90'; $_SERVER['HTTP_X_FORWARDED_FOR']='203.0.113.24'; $_SERVER['HTTP_X_REAL_IP']='203.0.113.24';
$out['spoofed_headers']=mailcow_admin_ip_allowed();
$ADMIN_IP_ALLOWLIST=['2001:db8:1234::/64']; $_SERVER['REMOTE_ADDR']='2001:db8:1234::5'; $out['ipv6_allowed']=mailcow_admin_ip_allowed();
$_SERVER['REMOTE_ADDR']='2001:db8:1235::5'; $out['ipv6_denied']=mailcow_admin_ip_allowed();
$ADMIN_IP_ALLOWLIST=[]; $out['empty']=mailcow_admin_ip_allowed();
$ADMIN_IP_ALLOWLIST=['203.0.113.0/99']; $out['invalid']=mailcow_admin_ip_allowed();
$ADMIN_IP_ALLOWLIST='203.0.113.24'; $out['invalid_type']=mailcow_admin_ip_allowed();
$ADMIN_IP_ALLOWLIST=null; $out['disabled']=mailcow_admin_ip_allowed();
echo json_encode($out);
''')
        for ip in ["192.0.2.1", "192.0.2.255", "198.51.100.0", "198.51.100.127", "203.0.113.24", "ipv6_allowed", "disabled"]:
            self.assertTrue(report[ip], ip)
        for ip in ["198.51.100.128", "203.0.113.25", "::1", "not-an-address", "spoofed_headers", "ipv6_denied", "empty", "invalid", "invalid_type"]:
            self.assertFalse(report[ip], ip)

    def test_actual_password_login_and_mfa_keep_mailbox_users_public(self):
        report = php(r'''
$out=[];
foreach (['fixtureadmin','fixturedomain','user@example.test'] as $user) {
  foreach ([false,true] as $mfa) {
    foreach (['203.0.113.24','203.0.113.90'] as $ip) {
      $_SESSION=[]; $fixture_mfa=$mfa; $_SERVER['REMOTE_ADDR']=$ip;
      $role=check_login($user,'fictional-password',['eas'=>false,'dav'=>false]);
      $out[]=[$user,$mfa,$ip,$role,$_SESSION['pending_mailcow_cc_role']??null];
    }
  }
}
echo json_encode($out);
''')
        for user, mfa, ip, role, pending in report:
            wanted = {"fixtureadmin": "admin", "fixturedomain": "domainadmin", "user@example.test": "user"}[user]
            if ip == "203.0.113.90" and wanted != "user":
                self.assertFalse(role)
                self.assertIsNone(pending)
            else:
                self.assertEqual(role, "pending" if mfa else wanted)
                self.assertEqual(pending, wanted if mfa else None)

    def test_sessions_mfa_dual_login_and_scoped_local_api(self):
        report = php(r'''
$out=[];
foreach ([['mailcow_cc_role'=>'admin'],['mailcow_cc_role'=>'domainadmin'],['pending_mailcow_cc_role'=>'admin'],['mailcow_cc_role'=>'user','dual-login'=>['role'=>'admin']],['mailcow_cc_role'=>'user'],['pending_mailcow_cc_role'=>'user'],[]] as $session) {
  $_SESSION=$session; $out[]=mailcow_admin_session_ip_allowed();
}
$ADMIN_IP_ALLOWLIST=['203.0.113.24'];
$_SERVER['REMOTE_ADDR']='192.0.2.250'; $_SERVER['REQUEST_URI']='/api/v1/get/domain/all';
$_SESSION=['mailcow_cc_role'=>'admin','mailcow_cc_api'=>true,'mailcow_cc_api_access'=>'ro'];
$out['no_current_key']=mailcow_admin_session_ip_allowed();
$_SERVER['HTTP_X_API_KEY']='fictional'; $out['local_ro']=mailcow_admin_session_ip_allowed();
$_SERVER['REQUEST_URI']='/api/v1/get/status/containers'; $out['containers']=mailcow_admin_session_ip_allowed();
$_SERVER['REQUEST_URI']='/admin'; $out['browser']=mailcow_admin_session_ip_allowed();
$_SERVER['REQUEST_URI']='/api/v1/get/domain/all'; $_SERVER['REQUEST_METHOD']='POST'; $out['post']=mailcow_admin_session_ip_allowed();
$_SERVER['REQUEST_METHOD']='GET'; $_SESSION['mailcow_cc_api_access']='rw'; $out['rw_read']=mailcow_admin_session_ip_allowed();
$_SERVER['REQUEST_METHOD']='POST'; $out['rw_post']=mailcow_admin_session_ip_allowed();
$_SERVER['REQUEST_METHOD']='GET'; $_SERVER['REQUEST_URI']='/api/v1/delete/mailbox'; $out['rw_write_endpoint']=mailcow_admin_session_ip_allowed();
$_SERVER['REQUEST_URI']='/api/v1/get/domain/all';
$_SESSION['mailcow_cc_api_access']='ro'; $_SERVER['REMOTE_ADDR']='203.0.113.90'; $out['external_ro']=mailcow_admin_session_ip_allowed();
$_SERVER['REMOTE_ADDR']='192.0.2.250'; $_SERVER['REQUEST_URI']='/api/v1/get/domain/all/../admin'; $out['path_trick']=mailcow_admin_session_ip_allowed();
$_SERVER['REQUEST_URI']='/api/v1/get/domain/all?query=get/admin/all'; $out['routing_override']=mailcow_admin_session_ip_allowed();
$_SESSION=['pending_mailcow_cc_role'=>'admin']; $_SERVER['REMOTE_ADDR']='203.0.113.90';
$out['mfa_refused']=verify_tfa_login('fixtureadmin',[]); $out['mfa_queries']=$pdo->queries;
echo json_encode($out);
''')
        self.assertEqual([report[str(n)] for n in range(7)], [False, False, False, False, True, True, True])
        for name in ["local_ro", "containers", "rw_read"]:
            self.assertTrue(report[name])
        for name in ["no_current_key", "browser", "post", "rw_post", "rw_write_endpoint", "external_ro", "path_trick", "routing_override", "mfa_refused"]:
            self.assertFalse(report[name], name)
        self.assertEqual(report["mfa_queries"], 0)

    def test_actual_session_entrypoint_enforces_before_actions(self):
        sessions = source("sessions.inc.php")
        for role, address, api, access, uri, wanted in [
            ("admin", "203.0.113.90", False, "ro", "/admin", 403),
            ("domainadmin", "203.0.113.90", False, "ro", "/user", 403),
            ("admin", "203.0.113.24", False, "ro", "/admin", 200),
            ("user", "203.0.113.90", False, "ro", "/user", 200),
            ("admin", "192.0.2.250", True, "ro", "/api/v1/get/domain/all", 200),
            ("admin", "192.0.2.250", True, "rw", "/api/v1/get/domain/all", 200),
            ("admin", "192.0.2.250", True, "ro", "/admin", 403),
        ]:
            with self.subTest(role=role, address=address, api=api, access=access, uri=uri):
                code = r'''
$ADMIN_IP_ALLOWLIST=['203.0.113.24']; $SESSION_LIFETIME=3600;
session_set_save_handler(function(){return true;},function(){return true;},function(){return '';},function(){return true;},function(){return true;},function(){return 0;});
session_start();
$_SESSION=['mailcow_cc_role'=>__ROLE__,'SESS_REMOTE_UA'=>'fixture','CSRF'=>['TOKEN'=>'fictional']];
$_SERVER['REMOTE_ADDR']=__ADDRESS__; $_SERVER['REQUEST_URI']=__URI__;
$fixture_api_access=__ACCESS__; if (__API__) $_SERVER['HTTP_X_API_KEY']='fictional';
register_shutdown_function(function(){echo "\n".json_encode(['status'=>http_response_code()?:200,'role'=>$_SESSION['mailcow_cc_role']??null,'post_empty'=>empty($_POST)]);});
eval('?>'.base64_decode('SESSIONS'));
'''.replace("__ROLE__", json.dumps(role)).replace("__ADDRESS__", json.dumps(address)).replace("__ACCESS__", json.dumps(access)).replace("__URI__", json.dumps(uri)).replace("__API__", "true" if api else "false").replace("SESSIONS", sessions)
                # A denied request emits its response before the shutdown report.
                result = subprocess.run(PHP, input="<?php\n" + BOOT + "\n" + code, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout[-1600:] + result.stderr[-1600:])
                report = json.loads(result.stdout.strip().splitlines()[-1])
                self.assertEqual(report["status"], wanted, result.stderr)
                if wanted == 403:
                    self.assertIsNone(report["role"])

    def test_actual_passwordless_role_promotion_keeps_mailbox_users_public(self):
        api = (ROOT / "data/web/json_api.php").read_text()
        start = api.index("          header('Content-Type: application/json');", api.index('case "fido2-args":'))
        end = api.index('          echo json_encode($return);', api.index('          $_SESSION["fido2_cid"]', start)) + len('          echo json_encode($return);')
        block = api[start:end]
        block = block.replace("file_get_contents('php://input')", "json_encode(['clientDataJSON'=>'','authenticatorData'=>'','signature'=>'','id'=>'fictional'])")
        block = block.replace('fido2(array("action" => "get_by_b64cid", "cid" => $post->id))', "['pub_key'=>'fictional','username'=>'user@example.test','cid'=>'fictional']")
        encoded = base64.b64encode(block.encode()).decode()
        for role in ["admin", "domainadmin", "user"]:
            for address in ["203.0.113.24", "203.0.113.90"]:
                with self.subTest(role=role, address=address):
                    code = r'''
class FixtureWebAuthn {function processGet(...$args) {return true;}}
$WebAuthn=new FixtureWebAuthn; $fixture_role=__ROLE__; $_SERVER['REMOTE_ADDR']=__ADDRESS__;
$_SESSION=['challenge'=>'fictional'];
register_shutdown_function(function(){echo "\n".json_encode(['status'=>http_response_code()?:200,'role'=>$_SESSION['mailcow_cc_role']??null]);});
eval(base64_decode('BLOCK'));
'''.replace("__ROLE__", json.dumps(role)).replace("__ADDRESS__", json.dumps(address)).replace("BLOCK", encoded)
                    result = subprocess.run(PHP, input="<?php\n" + BOOT + "\n" + code, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout[-1600:] + result.stderr[-1600:])
                    report = json.loads(result.stdout.strip().splitlines()[-1])
                    denied = role != "user" and address == "203.0.113.90"
                    self.assertEqual(report, {"status": 403 if denied else 200, "role": None if denied else role})

    def test_domain_admin_sso_does_not_consume_token_outside_policy(self):
        triggers = source("triggers.inc.php")
        for address, wanted_calls in [("203.0.113.90", 0), ("203.0.113.24", 1)]:
            result = php(r'''
function domain_admin_sso($action,$token){$GLOBALS['sso_calls']++;return false;}
$sso_calls=0; $_SERVER['REMOTE_ADDR']=__ADDRESS__; $_GET['sso_token']='fictional';
eval('?>'.base64_decode('TRIGGERS'));
echo json_encode(['calls'=>$sso_calls,'role'=>$_SESSION['mailcow_cc_role']??null]);
'''.replace("__ADDRESS__", json.dumps(address)).replace("TRIGGERS", triggers))
            self.assertEqual(result["calls"], wanted_calls)
            self.assertIsNone(result["role"])


if __name__ == "__main__":
    unittest.main()
