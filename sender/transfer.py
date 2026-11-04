"""Resumable HTTP upload client (no Kivy). Continues from the byte the Receiver already holds."""
import hashlib, http.client, json, os, time
from urllib.parse import quote

def _get(ip, port, path, timeout=20):
    c = http.client.HTTPConnection(ip, port, timeout=timeout)
    try:
        c.request("GET", path); r = c.getresponse(); return r.status, json.loads(r.read() or b"{}")
    finally:
        c.close()

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def upload_resumable(ip, port, token, path, progress=None, retries=6, chunk=65536, sleep=time.sleep):
    size = os.path.getsize(path); name = os.path.basename(path)
    digest = sha256_file(path)
    q = "t=%s&name=%s&size=%d" % (token, quote(name), size)
    last_err = None
    for attempt in range(retries + 1):
        try:
            _, d = _get(ip, port, "/has?" + q)
            if d.get("has"): return d["name"]
            offset = int(d.get("partial", 0) or 0)
            c = http.client.HTTPConnection(ip, port, timeout=60)
            try:
                c.putrequest("POST", "/upload?%s&offset=%d&sha256=%s" % (q, offset, digest))
                c.putheader("Content-Length", str(size - offset)); c.endheaders()
                sent = offset
                with open(path, "rb") as f:
                    f.seek(offset)
                    while True:
                        b = f.read(chunk)
                        if not b: break
                        c.send(b); sent += len(b)
                        if progress: progress(sent, size)
                r = c.getresponse(); body = json.loads(r.read() or b"{}")
            finally:
                c.close()
            if body.get("done") and "name" in body: return body["name"]
            last_err = body.get("error", "incomplete")
        except (OSError, http.client.HTTPException, ValueError) as e:
            last_err = e
        sleep(min(8, 1 + attempt * 2))
    raise RuntimeError("upload failed: %s" % last_err)
