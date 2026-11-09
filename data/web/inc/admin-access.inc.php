<?php
/* Optional administrator source policy. Mailbox users keep their existing access. */
function mailcow_admin_ip_allowed($api = false) {
  global $ADMIN_IP_ALLOWLIST, $ADMIN_IP_API_ALLOWLIST;
  if ($ADMIN_IP_ALLOWLIST === null) return true;
  $address = $_SERVER['REMOTE_ADDR'] ?? '';
  if (!filter_var($address, FILTER_VALIDATE_IP) || !is_array($ADMIN_IP_ALLOWLIST)) return false;
  foreach ($ADMIN_IP_ALLOWLIST as $network) {
    if (!is_string($network) || !valid_network($network)) return false;
  }
  if (ip_acl($address, $ADMIN_IP_ALLOWLIST)) return true;

  // The local monitoring exception never grants a browser session or write access.
  $path = $_SERVER['REQUEST_URI'] ?? ''; // Exact URLs also reject routing-query overrides.
  if (!$api || ($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET' ||
      !in_array($path, ['/api/v1/get/domain/all', '/api/v1/get/status/containers'], true) ||
      !is_array($ADMIN_IP_API_ALLOWLIST)) return false;
  foreach ($ADMIN_IP_API_ALLOWLIST as $network) {
    if (!is_string($network) || !valid_network($network)) return false;
  }
  return ip_acl($address, $ADMIN_IP_API_ALLOWLIST);
}

function mailcow_admin_session_ip_allowed() {
  $roles = [$_SESSION['mailcow_cc_role'] ?? '', $_SESSION['pending_mailcow_cc_role'] ?? '',
    $_SESSION['dual-login']['role'] ?? ''];
  if (!array_intersect(['admin', 'domainadmin'], $roles)) return true;
  $api = !empty($_SERVER['HTTP_X_API_KEY']) &&
    ($_SESSION['mailcow_cc_api'] ?? false) === true &&
    in_array($_SESSION['mailcow_cc_api_access'] ?? '', ['ro', 'rw'], true);
  return mailcow_admin_ip_allowed($api);
}

function mailcow_enforce_admin_session_ip() {
  if (mailcow_admin_session_ip_allowed()) return;
  $_SESSION = [];
  $_POST = [];
  $_FILES = [];
  if (session_status() === PHP_SESSION_ACTIVE) session_destroy();
  http_response_code(403);
  header('Content-Type: application/json; charset=utf-8');
  header('Cache-Control: no-store');
  echo json_encode(['type' => 'error', 'msg' => 'Administrator access is limited to approved networks.']);
  exit;
}
