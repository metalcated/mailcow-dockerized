"""Harmless socket/scanner checks inside a disposable image or existing Olefy."""

import io
import json
import os
import socket
import subprocess
import time
import zipfile


def request(payload):
    with socket.create_connection(("127.0.0.1", 10055), timeout=15) as connection:
        connection.sendall(payload)
        connection.shutdown(socket.SHUT_WR)
        data = b""
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            data += chunk
        return data


process = None
if os.getenv("OLEFY_FIXTURE_EXISTING") != "1":
    env = os.environ.copy()
    env.update(OLEFY_BINDADDRESS="127.0.0.1", OLEFY_BINDPORT="10055", OLEFY_MINLENGTH="500",
               OLEFY_PYTHON_PATH="/usr/bin/python3", OLEFY_OLEVBA_PATH="/usr/bin/olevba")
    process = subprocess.Popen(["/usr/bin/python3", "-u", "/app/olefy.py"], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for attempt in range(40):
        try:
            assert request(b"PING\n\n") == b"PONG"
            break
        except OSError:
            time.sleep(0.1)
    else:
        raise AssertionError("Olefy did not become ready")
    header = b"OLEFY/1.0\nMethod: oletools\nRspamd-ID: fixture123\n\n"
    small = json.loads(request(header + b"small"))
    assert small == [{"error": "File too small"}], small
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as doc:
        doc.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        doc.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        doc.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Harmless maintenance fixture</w:t></w:r></w:p></w:body></w:document>')
    result = json.loads(request(header + archive.getvalue()))
    assert isinstance(result, list) and result, result
    assert not any("error" in item for item in result if isinstance(item, dict)), result
    assert "OpenXML" in json.dumps(result), result
    print("Olefy PING, minimum-size rejection, and clean Office scan passed")
finally:
    if process is not None:
        process.terminate()
        process.wait(timeout=10)
