"""Tiny HTTP server on the Receiver (no Kivy). Token-protected.
Endpoints: GET /has /list /thumb /files /space   POST /upload (resumable) /delete /rename."""
import hashlib, json, os, shutil, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

def safe(name):
    n = os.path.basename(name or "").replace("..", "_").strip()
    return n or ("file_%d" % int(time.time()))

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def part_path(media_dir, name, size):
    return os.path.join(media_dir, "%s.%d.part" % (name, size))

def disk_space(path):
    try:
        u = shutil.disk_usage(path)
        return {"free": u.free, "total": u.total}
    except Exception:
        return {"free": 0, "total": 0}

def list_files(media_dir):
    out = []
    for n in sorted(os.listdir(media_dir)):
        p = os.path.join(media_dir, n)
        if os.path.isfile(p):
            st = os.stat(p)
            out.append({"name": n, "size": st.st_size, "mtime": int(st.st_mtime), "partial": n.endswith(".part")})
    return out

def start(port, token, media_dir, list_fn, thumb_fn):
    os.makedirs(media_dir, exist_ok=True)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def reply(self, code, body, ctype="application/json"):
            if not isinstance(body, bytes): body = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def parts(self):
            u = urlparse(self.path)
            return u.path, {k: v[0] for k, v in parse_qs(u.query).items()}

        def do_GET(self):
            try:
                path, q = self.parts()
                if q.get("t") != token: return self.reply(403, {"error": "token"})
                if path == "/has":
                    name = safe(q.get("name")); size = int(q.get("size", -1)); f = os.path.join(media_dir, name)
                    if os.path.isfile(f) and os.path.getsize(f) == size:
                        return self.reply(200, {"has": True, "name": name})
                    pp = part_path(media_dir, name, size)
                    have = os.path.getsize(pp) if os.path.isfile(pp) else 0
                    return self.reply(200, {"has": False, "partial": have if 0 < have < size else 0})
                if path == "/list":
                    return self.reply(200, list_fn().encode("utf-8"))
                if path == "/thumb":
                    b = thumb_fn(q.get("uri", ""))
                    return self.reply(200, b, "image/jpeg") if b else self.reply(404, {"error": "nothumb"})
                if path == "/files":
                    return self.reply(200, {"files": list_files(media_dir), **disk_space(media_dir)})
                if path == "/space":
                    return self.reply(200, disk_space(media_dir))
                self.reply(404, {"error": "path"})
            except Exception as e:
                try: self.reply(500, {"error": str(e)})
                except Exception: pass

        def do_POST(self):
            try:
                path, q = self.parts()
                if q.get("t") != token: return self.reply(403, {"error": "token"})
                if path == "/delete":
                    f = os.path.join(media_dir, safe(q.get("name")))
                    if not os.path.isfile(f): return self.reply(404, {"error": "missing"})
                    os.remove(f); return self.reply(200, {"ok": True})
                if path == "/rename":
                    a = os.path.join(media_dir, safe(q.get("old"))); b = os.path.join(media_dir, safe(q.get("new")))
                    if not os.path.isfile(a): return self.reply(404, {"error": "missing"})
                    if os.path.exists(b): return self.reply(409, {"error": "exists"})
                    os.replace(a, b); return self.reply(200, {"ok": True, "name": os.path.basename(b)})
                if path != "/upload": return self.reply(404, {"error": "path"})
                n = int(self.headers.get("Content-Length", 0)); name = safe(q.get("name"))
                offset = int(q.get("offset", 0) or 0)
                total = int(q.get("size", offset + n) or (offset + n))
                pp = part_path(media_dir, name, total)
                have = os.path.getsize(pp) if os.path.isfile(pp) else 0
                if offset != have:                      # resume point must match what we hold
                    return self.reply(409, {"error": "offset", "have": have})
                left = n
                with open(pp, "ab") as f:
                    while left > 0:
                        b = self.rfile.read(min(65536, left))
                        if not b: break
                        f.write(b); left -= len(b)
                have = os.path.getsize(pp)
                if have < total:                        # connection dropped: keep the partial file
                    return self.reply(202, {"done": False, "have": have})
                want = (q.get("sha256") or "").lower()
                if want and sha256_file(pp) != want:     # corrupted in transit: discard so the client restarts clean
                    os.remove(pp); return self.reply(422, {"error": "sha256"})
                dest = os.path.join(media_dir, name)
                if os.path.exists(dest): dest = os.path.join(media_dir, "%d_%s" % (time.time(), name))
                os.replace(pp, dest)
                self.reply(200, {"name": os.path.basename(dest), "done": True})
            except Exception as e:
                try: self.reply(500, {"error": str(e)})
                except Exception: pass

    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
