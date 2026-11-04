import http.client, json, os, socket, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "receiver", ROOT / "sender"):
    if str(p) not in sys.path: sys.path.insert(0, str(p))
import mediaserver, transfer

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

class ServerCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(); self.port = free_port(); self.tok = "tok"
        self.srv = mediaserver.start(self.port, self.tok, self.dir, lambda: "[]", lambda u: None)
        self.src = os.path.join(tempfile.mkdtemp(), "video.bin"); self.data = os.urandom(300000)
        open(self.src, "wb").write(self.data)
    def tearDown(self): self.srv.shutdown()
    def call(self, method, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port); c.request(method, path + "&t=" + self.tok if "?" in path else path + "?t=" + self.tok)
        r = c.getresponse(); return r.status, json.loads(r.read() or b"{}")

class ResumeTests(ServerCase):
    def test_full_upload(self):
        name = transfer.upload_resumable("127.0.0.1", self.port, self.tok, self.src)
        self.assertEqual(open(os.path.join(self.dir, name), "rb").read(), self.data)

    def test_resume_after_dropped_connection(self):
        size = len(self.data)
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.putrequest("POST", "/upload?t=tok&name=video.bin&size=%d&offset=0" % size)
        c.putheader("Content-Length", str(size)); c.endheaders()
        c.send(self.data[:123456]); c.sock.close()                     # connection drops half-way
        import time; time.sleep(0.4)
        st, d = self.call("GET", "/has?name=video.bin&size=%d" % size)
        self.assertEqual(d["has"], False); self.assertEqual(d["partial"], 123456)
        seen = []
        name = transfer.upload_resumable("127.0.0.1", self.port, self.tok, self.src, progress=lambda s, t: seen.append(s))
        self.assertEqual(open(os.path.join(self.dir, name), "rb").read(), self.data)
        self.assertGreater(min(seen), 123456 - 1)                      # resumed, did not restart at 0

    def test_wrong_offset_rejected(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.putrequest("POST", "/upload?t=tok&name=a.bin&size=10&offset=5"); c.putheader("Content-Length", "5"); c.endheaders(); c.send(b"12345")
        r = c.getresponse(); self.assertEqual(r.status, 409)

    def test_bad_token(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port); c.request("GET", "/files?t=nope")
        self.assertEqual(c.getresponse().status, 403)

class FileManagerTests(ServerCase):
    def test_list_rename_delete_space(self):
        transfer.upload_resumable("127.0.0.1", self.port, self.tok, self.src)
        st, d = self.call("GET", "/files")
        self.assertEqual([f["name"] for f in d["files"]], ["video.bin"]); self.assertGreater(d["total"], 0)
        st, d = self.call("POST", "/rename?old=video.bin&new=clip.bin"); self.assertEqual(st, 200)
        st, d = self.call("GET", "/files"); self.assertEqual(d["files"][0]["name"], "clip.bin")
        st, d = self.call("POST", "/delete?name=clip.bin"); self.assertEqual(st, 200)
        st, d = self.call("GET", "/files"); self.assertEqual(d["files"], [])
        st, d = self.call("POST", "/delete?name=clip.bin"); self.assertEqual(st, 404)

    def test_path_traversal_is_neutralised(self):
        open(os.path.join(os.path.dirname(self.dir), "secret.txt"), "w").write("x")
        st, d = self.call("POST", "/delete?name=../secret.txt"); self.assertEqual(st, 404)
        self.assertTrue(os.path.exists(os.path.join(os.path.dirname(self.dir), "secret.txt")))

if __name__ == "__main__": unittest.main()

class IntegrityTests(ServerCase):
    def test_wrong_sha256_rejected_and_part_removed(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port); data = b"hello world" * 100
        c.putrequest("POST", "/upload?t=tok&name=a.bin&size=%d&offset=0&sha256=%s" % (len(data), "0" * 64))
        c.putheader("Content-Length", str(len(data))); c.endheaders(); c.send(data)
        r = c.getresponse(); self.assertEqual(r.status, 422)
        self.assertEqual([f for f in os.listdir(self.dir)], [])                       # nothing left behind
    def test_correct_sha256_accepted(self):
        import hashlib
        data = b"abc" * 1000; c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.putrequest("POST", "/upload?t=tok&name=b.bin&size=%d&offset=0&sha256=%s" % (len(data), hashlib.sha256(data).hexdigest()))
        c.putheader("Content-Length", str(len(data))); c.endheaders(); c.send(data)
        self.assertEqual(c.getresponse().status, 200); self.assertEqual(open(os.path.join(self.dir, "b.bin"), "rb").read(), data)
    def test_resume_still_verifies_whole_file(self):
        size = len(self.data); c = http.client.HTTPConnection("127.0.0.1", self.port)
        c.putrequest("POST", "/upload?t=tok&name=video.bin&size=%d&offset=0" % size); c.putheader("Content-Length", str(size)); c.endheaders()
        c.send(self.data[:50000]); c.sock.close(); import time; time.sleep(0.3)
        name = transfer.upload_resumable("127.0.0.1", self.port, self.tok, self.src)
        self.assertEqual(open(os.path.join(self.dir, name), "rb").read(), self.data)

class DevInfoTests(unittest.TestCase):
    def test_battery_and_lines(self):
        sys.path.insert(0, str(ROOT / "shared")); import devinfo as D
        self.assertEqual(D.battery_from(82, 100, 2), {"level": 82, "charging": True})
        self.assertEqual(D.battery_from(-1, 100, 3), {"level": -1, "charging": False})
        self.assertEqual(D.battery_from("x", None, 0)["level"], -1); self.assertEqual(D.battery_from(50, 0, 0)["level"], -1)
        self.assertEqual(D.battery_from(150, 100, 0)["level"], 100)
        line = D.status_line({"battery": {"level": 40, "charging": False}, "free": 3 * 1024 ** 3, "paired": True})
        self.assertIn("40%", line); self.assertIn("3.0 GB", line); self.assertIn("مقترن", line)
        self.assertEqual(D.human_bytes(512), "512 B")
    def test_copies(self):
        base = (ROOT / "shared" / "devinfo.py").read_text()
        for app in ("sender", "receiver"): self.assertEqual((ROOT / app / "devinfo.py").read_text(), base)
