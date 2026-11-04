"""V9 secure-channel glue (pure Python, no Kivy): routing/persistence for both apps, fully testable.
Open mode (never paired) behaves exactly like V8. After pairing, everything except the pairing
handshake and a minimal plain 'hello' probe must arrive as an encrypted 'sec' frame."""
import json, os, time, uuid
import secure as X
from protocol import encode

PAIR_TYPES = ("pair_begin", "pair_confirm")

def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(obj, f)
    os.replace(tmp, path)

def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except Exception: return None

def _nack(mid, text): return {"id": mid, "ok": False, "result": text}

class ReceiverSecurity:
    def __init__(self, path, rid, now=time.time):
        self.path, self.rid, self.now = path, rid, now
        d = _read_json(path); self.sess = None
        try:
            if d and d.get("session"): self.sess = X.Session.from_dict(d["session"])
        except Exception: self.sess = None
        self.pair = X.PairReceiver(now=now)

    @property
    def paired(self): return self.sess is not None

    def _save(self):
        if self.sess: _write_json(self.path, {"session": self.sess.to_dict()})
        elif os.path.exists(self.path): os.remove(self.path)

    def route(self, m):
        """-> (kind, payload): 'drop' | 'plain' (payload = ack body to send unencrypted)
        | 'pair_begin' / 'pair_confirm' (payload = (id, data)) | 'dispatch' (payload = (message, secure))"""
        if not isinstance(m, dict) or not isinstance(m.get("id"), str) or not isinstance(m.get("t"), str): return "drop", None
        t, mid, d = m["t"], m["id"], m.get("d", {})
        if t in PAIR_TYPES:
            if self.sess: return "plain", _nack(mid, "الجهاز مقترن مسبقاً: ألغِ الاقتران أولاً")
            if not isinstance(d, dict): return "plain", _nack(mid, "بنية غير صالحة")
            return t, (mid, d)
        if t == "sec":
            if not self.sess: return "plain", _nack(mid, "الجهاز غير مقترن")
            try: inner = self.sess.unwrap(d)
            except X.SecureError: return "plain", _nack(mid, "فشل التحقق من الرسالة المشفرة")
            self._save()                                   # persist the replay counter
            if not isinstance(inner.get("id"), str) or not isinstance(inner.get("t"), str): return "drop", None
            if inner["t"] in ("sec",) + PAIR_TYPES: return "drop", None
            return "dispatch", (inner, True)
        if self.sess:
            if t == "hello": return "plain", {"id": mid, "ok": True, "rid": self.rid, "paired": True}
            return "plain", _nack(mid, "الاتصال مشفّر: يلزم الاقتران أولاً")
        return "dispatch", (m, False)

    def ack_envelope(self, mid, body, secure):
        body = dict(body); body["id"] = mid
        if secure and self.sess:
            env = encode("sec", self.sess.wrap({"id": mid, "t": "ack", "d": body})); self._save(); return env
        return encode("ack", body)

    # ---- pairing (receiver side)
    def begin(self, d):
        try: return True, self.pair.on_begin(d.get("pub")), self.pair.sas
        except X.SecureError as e: return False, {"result": "فشل الاقتران: %s" % e}, None

    def accept(self): return self.pair.accept()
    def decline(self): self.pair.decline()

    def confirm(self, d):
        """-> (status, body). status 'ok' means the session is now active (reply with a SECURE ack)."""
        status, sess = self.pair.on_confirm(d.get("proof"))
        if status == "ok":
            self.sess = sess; self._save(); return "ok", {}
        return status, {"result": {"pending": "pending", "expired": "انتهت مهلة الاقتران", "bad": "رمز غير صحيح"}[status]}

    def unpair(self):
        self.sess = None; self._save()

class SenderSecurity:
    def __init__(self, path):
        self.path = path; raw = _read_json(path); self.raw = raw if isinstance(raw, dict) else {}
        self.rid = None; self.sess = None; self.cand = None; self.pairing = None

    def _save(self):
        if self.rid and self.sess: self.raw[self.rid] = self.sess.to_dict()
        _write_json(self.path, self.raw)

    def note_hello(self, d):
        """Call with every ack that carries rid/paired. -> 'legacy' | 'open' | 'secure_hello' | 'foreign'."""
        if "rid" not in d or "paired" not in d: return "legacy"
        self.rid = str(d["rid"])
        if not d["paired"]:
            self.sess = None
            if self.raw.pop(self.rid, None) is not None: _write_json(self.path, self.raw)    # receiver was reset
            return "open"
        if self.sess is None and self.rid in self.raw:
            try: self.sess = X.Session.from_dict(self.raw[self.rid])
            except Exception: self.sess = None
        return "secure_hello" if self.sess else "foreign"

    def build(self, type_, data, secure=None):
        """-> (id, envelope bytes). secure=None: encrypt whenever paired (except the first plain hello)."""
        use = (self.sess is not None) if secure is None else (bool(secure) and self.sess is not None)
        if type_ == "hello" and secure is None: use = False
        if use:
            mid = uuid.uuid4().hex[:12]; env = encode("sec", self.sess.wrap({"id": mid, "t": type_, "d": data})); self._save()
            return mid, env
        env = encode(type_, data); return json.loads(env[8:].decode("utf-8"))["id"], env

    def open_frame(self, m):
        """Decrypt 'sec' frames. Returns the plain message, or None if it must be ignored."""
        if not isinstance(m, dict): return None
        if m.get("t") != "sec": return m
        sess = self.sess or self.cand
        if sess is None: return None
        try: inner = sess.unwrap(m.get("d"))
        except X.SecureError: return None
        if sess is self.cand and self.sess is None:        # first authentic frame after pairing -> adopt the session
            self.sess, self.cand, self.pairing = sess, None, None
        self._save()
        return inner if isinstance(inner.get("id"), str) else None

    # ---- pairing (sender side)
    def start_pairing(self):
        if not self.rid: raise X.SecureError("receiver not identified")
        if self.sess: raise X.SecureError("already paired")
        self.cand = None; self.pairing = X.PairSender(); return self.pairing.begin()

    def on_pair_reply(self, d):
        sas = self.pairing.on_reply(d.get("pub")); self.cand = self.pairing.session(); return sas

    def confirm_body(self): return self.pairing.proof()
    def cancel_pairing(self): self.pairing = self.cand = None

    def forget(self):
        if self.rid: self.raw.pop(self.rid, None)
        self.sess = self.cand = self.pairing = None; _write_json(self.path, self.raw)
