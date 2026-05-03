function auth_password_verify(req, pass)
  if req.domain == nil then
    return dovecot.auth.PASSDB_RESULT_USER_UNKNOWN, "No such user"
  end

  if cur == nil then
    script_init()
  end

  if req.user == nil then
    req.user = ''
  end

  local cur,errorString = con:execute(string.format([[SELECT password FROM mailbox
    WHERE username = '%s'
      AND active = '1'
      AND domain IN (SELECT domain FROM domain WHERE domain='%s' AND active='1')
      AND IFNULL(JSON_UNQUOTE(JSON_VALUE(mailbox.attributes, '$.force_pw_update')), 0) != '1'
      AND IFNULL(JSON_UNQUOTE(JSON_VALUE(attributes, '$.%s_access')), 1) = '1']], con:escape(req.user), con:escape(req.domain), con:escape(req.service)))
  local row = cur:fetch ({}, "a")
  while row do
    if req.password_verify(req, row.password, pass) == 1 then
      con:execute(string.format([[REPLACE INTO sasl_log (service, app_password, username, real_rip)
        VALUES ("%s", 0, "%s", "%s")]], con:escape(req.service), con:escape(req.user), con:escape(req.real_rip)))
      cur:close()
      con:close()
      return dovecot.auth.PASSDB_RESULT_OK, ""
    end
    row = cur:fetch (row, "a")
  end

  if req.service == "smtp" or req.service == "imap" or req.service == "sieve" or req.service == "pop3" then
    local cur,errorString = con:execute(string.format([[SELECT app_passwd.id, %s_access AS has_prot_access, app_passwd.password FROM app_passwd
      INNER JOIN mailbox ON mailbox.username = app_passwd.mailbox
      WHERE mailbox = '%s'
        AND app_passwd.active = '1'
        AND mailbox.active = '1'
        AND app_passwd.domain IN (SELECT domain FROM domain WHERE domain='%s' AND active='1')]], con:escape(req.service), con:escape(req.user), con:escape(req.domain)))
    local row = cur:fetch ({}, "a")
    while row do
      if req.password_verify(req, row.password, pass) == 1 then
        if tostring(req.real_rip) == tostring(os.getenv("IPV4_NETWORK") or "172.22.1") .. ".248" then
          cur:close()
          con:close()
          return dovecot.auth.PASSDB_RESULT_OK, ""
        elseif row.has_prot_access == "1" then
          con:execute(string.format([[REPLACE INTO sasl_log (service, app_password, username, real_rip)
            VALUES ("%s", %d, "%s", "%s")]], con:escape(req.service), row.id, con:escape(req.user), con:escape(req.real_rip)))
          cur:close()
          con:close()
          return dovecot.auth.PASSDB_RESULT_OK, ""
        end
      end
      row = cur:fetch (row, "a")
    end
  end

  cur:close()
  con:close()

  return dovecot.auth.PASSDB_RESULT_PASSWORD_MISMATCH, "Failed to authenticate"
end

function auth_passdb_lookup(req)
   return dovecot.auth.PASSDB_RESULT_USER_UNKNOWN, ""
end

function script_init()
  mysql = require "luasql.mysql"
  env = mysql.mysql()
  con = env:connect(os.getenv("DBNAME"), os.getenv("DBUSER"), os.getenv("DBPASS"), "localhost")
  return 0
end

function script_deinit()
  con:close()
  env:close()
end
