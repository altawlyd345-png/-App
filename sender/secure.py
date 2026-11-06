"""BLE Remote V9 — real authentication + encryption (pure Python, no third-party packages).
X25519 key agreement (RFC 7748) -> HKDF-SHA256 (RFC 5869) -> ChaCha20-Poly1305 AEAD (RFC 8439).
Pairing uses a 6-digit short authentication string (SAS) that the user compares on BOTH devices.
Notes: pure-Python big-int maths is not constant-time (acceptable for this local, short-range use)."""
import base64, hashlib, hmac, json, os, struct, time

class SecureError(Exception):
    pass

# ---------------------------------------------------------------- X25519
_P = 2 ** 255 - 19
_A24 = 121665

def x25519(k, u):
    if len(k) != 32 or len(u) != 32: raise SecureError("bad key length")
    kb = bytearray(k); kb[0] &= 248; kb[31] &= 127; kb[31] |= 64
    kk = int.from_bytes(kb, "little"); x1 = int.from_bytes(u, "little") & ((1 << 255) - 1)
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    for t in range(254, -1, -1):
        kt = (kk >> t) & 1; swap ^= kt
        if swap: x2, x3, z2, z3 = x3, x2, z3, z2
        swap = kt
        a = (x2 + z2) % _P; aa = a * a % _P; b = (x2 - z2) % _P; bb = b * b % _P; e = (aa - bb) % _P
        c = (x3 + z3) % _P; d = (x3 - z3) % _P; da = d * a % _P; cb = c * b % _P
        x3 = (da + cb) ** 2 % _P; z3 = x1 * ((da - cb) ** 2 % _P) % _P
        x2 = aa * bb % _P; z2 = e * ((aa + _A24 * e) % _P) % _P
    if swap: x2, x3, z2, z3 = x3, x2, z3, z2
    return (x2 * pow(z2, _P - 2, _P) % _P).to_bytes(32, "little")

_BASE = (9).to_bytes(32, "little")

def keypair():
    priv = os.urandom(32)
    return priv, x25519(priv, _BASE)

def shared_secret(priv, peer_pub):
    s = x25519(priv, peer_pub)
    if s == bytes(32): raise SecureError("low-order public key")
    return s

# ---------------------------------------------------------------- HKDF
def hkdf(ikm, salt, info, length):
    prk = hmac.new(salt or bytes(32), ikm, hashlib.sha256).digest()
    out, t, i = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest(); out += t; i += 1
    return out[:length]

# ---------------------------------------------------------------- ChaCha20-Poly1305
def _rotl(v, n): return ((v << n) & 0xFFFFFFFF) | (v >> (32 - n))

def _quarter(s, a, b, c, d):
    s[a] = (s[a] + s[b]) & 0xFFFFFFFF; s[d] = _rotl(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF; s[b] = _rotl(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b]) & 0xFFFFFFFF; s[d] = _rotl(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF; s[b] = _rotl(s[b] ^ s[c], 7)

def _block(key, counter, nonce):
    st = [0x61707865, 0x3320646e, 0x79622d32, 0x6b206574] + list(struct.unpack("<8I", key)) + [counter] + list(struct.unpack("<3I", nonce))
    w = st[:]
    for _ in range(10):
        _quarter(w, 0, 4, 8, 12); _quarter(w, 1, 5, 9, 13); _quarter(w, 2, 6, 10, 14); _quarter(w, 3, 7, 11, 15)
        _quarter(w, 0, 5, 10, 15); _quarter(w, 1, 6, 11, 12); _quarter(w, 2, 7, 8, 13); _quarter(w, 3, 4, 9, 14)
    return struct.pack("<16I", *[(w[i] + st[i]) & 0xFFFFFFFF for i in range(16)])

def _chacha_xor(key, counter, nonce, data):
    out = bytearray()
    for i in range(0, len(data), 64):
        ks = _block(key, counter + i // 64, nonce); chunk = data[i:i + 64]
        out += bytes(a ^ b for a, b in zip(chunk, ks))
    return bytes(out)

def _poly1305(key, msg):
    r = int.from_bytes(key[:16], "little") & 0x0ffffffc0ffffffc0ffffffc0fffffff
    s = int.from_bytes(key[16:], "little"); acc, p = 0, (1 << 130) - 5
    for i in range(0, len(msg), 16):
        acc = (acc + int.from_bytes(msg[i:i + 16] + b"\x01", "little")) * r % p
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")

def _pad16(b): return b"\x00" * (-len(b) % 16)

def _tag(otk, aad, ct):
    return _poly1305(otk, aad + _pad16(aad) + ct + _pad16(ct) + struct.pack("<QQ", len(aad), len(ct)))

def aead_encrypt(key, nonce, plaintext, aad=b""):
    if len(key) != 32 or len(nonce) != 12: raise SecureError("bad key/nonce length")
    ct = _chacha_xor(key, 1, nonce, plaintext)
    return ct + _tag(_block(key, 0, nonce)[:32], aad, ct)

def aead_decrypt(key, nonce, data, aad=b""):
    if len(key) != 32 or len(nonce) != 12 or len(data) < 16: raise SecureError("bad input")
    ct, tag = data[:-16], data[-16:]
    if not hmac.compare_digest(tag, _tag(_block(key, 0, nonce)[:32], aad, ct)): raise SecureError("authentication failed")
    return _chacha_xor(key, 1, nonce, ct)

# ---------------------------------------------------------------- session (counters = replay protection)
MAX_PLAIN = 60000
S2R, R2S = 0, 1          # directions; each direction has its own key

class Session:
    def __init__(self, role, k_send, k_recv, send_ctr=0, recv_ctr=0):
        self.role = role                      # "sender" or "receiver"
        self.k_send, self.k_recv = k_send, k_recv
        self.send_ctr, self.recv_ctr = send_ctr, recv_ctr
        self.d_send = S2R if role == "sender" else R2S
        self.d_recv = R2S if role == "sender" else S2R

    @staticmethod
    def _nonce(direction, ctr): return bytes([direction]) + b"\x00" * 3 + ctr.to_bytes(8, "little")
    @staticmethod
    def _aad(direction, ctr): return b"ble-remote-v9" + bytes([direction]) + ctr.to_bytes(8, "little")

    def wrap(self, msg):
        raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_PLAIN: raise SecureError("message too large")
        self.send_ctr += 1; c = self.send_ctr
        ct = aead_encrypt(self.k_send, self._nonce(self.d_send, c), raw, self._aad(self.d_send, c))
        return {"c": c, "b": base64.b64encode(ct).decode("ascii")}

    def unwrap(self, d):
        try:
            c = d["c"]; blob = base64.b64decode(d["b"], validate=True)
        except Exception: raise SecureError("malformed secure frame")
        if not isinstance(c, int) or isinstance(c, bool) or c <= self.recv_ctr or c >= 1 << 62:
            raise SecureError("replayed or out-of-order frame")
        if len(blob) > MAX_PLAIN + 16: raise SecureError("frame too large")
        raw = aead_decrypt(self.k_recv, self._nonce(self.d_recv, c), blob, self._aad(self.d_recv, c))
        self.recv_ctr = c                                   # only advance after successful authentication
        try: msg = json.loads(raw.decode("utf-8"))
        except Exception: raise SecureError("bad payload")
        if not isinstance(msg, dict): raise SecureError("bad payload")
        return msg

    def to_dict(self):
        return {"role": self.role, "k_send": self.k_send.hex(), "k_recv": self.k_recv.hex(),
                "send_ctr": self.send_ctr, "recv_ctr": self.recv_ctr}

    @classmethod
    def from_dict(cls, d):
        return cls(d["role"], bytes.fromhex(d["k_send"]), bytes.fromhex(d["k_recv"]), int(d["send_ctr"]), int(d["recv_ctr"]))

# ---------------------------------------------------------------- pairing
PAIR_WINDOW = 90.0
MAX_PROOF_TRIES = 3

def _derive(shared, pub_s, pub_r):
    okm = hkdf(shared, pub_s + pub_r, b"ble-remote-v9 keys", 32 * 3 + 4)
    sas = int.from_bytes(okm[96:100], "big") % 1000000
    return okm[:32], okm[32:64], okm[64:96], "%03d %03d" % (sas // 1000, sas % 1000)

def _proof(k_confirm, pub_s, pub_r):
    return hmac.new(k_confirm, b"confirm" + pub_s + pub_r, hashlib.sha256).hexdigest()

class PairSender:
    def __init__(self):
        self.priv, self.pub = keypair(); self.rpub = None; self.sas = None; self._k = None

    def begin(self): return {"pub": self.pub.hex()}

    def on_reply(self, rpub_hex):
        try: self.rpub = bytes.fromhex(rpub_hex)
        except (ValueError, TypeError): raise SecureError("bad receiver key")
        if len(self.rpub) != 32: raise SecureError("bad receiver key")
        k_s2r, k_r2s, k_conf, self.sas = _derive(shared_secret(self.priv, self.rpub), self.pub, self.rpub)
        self._k = (k_s2r, k_r2s, k_conf)
        return self.sas

    def proof(self): return {"proof": _proof(self._k[2], self.pub, self.rpub)}
    def session(self): return Session("sender", self._k[0], self._k[1])

class PairReceiver:
    def __init__(self, now=time.time):
        self.now = now; self.reset()

    def reset(self):
        self.priv = self.pub = self.spub = self.sas = self._k = None
        self.accepted = False; self.deadline = 0.0; self.tries = 0

    @property
    def active(self): return self._k is not None and self.now() < self.deadline

    def on_begin(self, spub_hex):
        try: spub = bytes.fromhex(spub_hex)
        except (ValueError, TypeError): raise SecureError("bad sender key")
        if len(spub) != 32: raise SecureError("bad sender key")
        self.reset(); self.priv, self.pub = keypair(); self.spub = spub
        k_s2r, k_r2s, k_conf, self.sas = _derive(shared_secret(self.priv, spub), spub, self.pub)
        self._k = (k_s2r, k_r2s, k_conf); self.deadline = self.now() + PAIR_WINDOW
        return {"pub": self.pub.hex()}

    def accept(self):                          # the user pressed "accept" on THIS device after comparing the codes
        if not self.active: return False
        self.accepted = True; return True

    def decline(self): self.reset()

    def on_confirm(self, proof_hex):
        """-> ("ok", Session) | ("pending", None) | ("expired", None) | ("bad", None)"""
        if self._k is None or self.now() >= self.deadline: self.reset(); return "expired", None
        if not isinstance(proof_hex, str) or not hmac.compare_digest(proof_hex, _proof(self._k[2], self.spub, self.pub)):
            self.tries += 1
            if self.tries >= MAX_PROOF_TRIES: self.reset()
            return "bad", None
        if not self.accepted: return "pending", None
        sess = Session("receiver", self._k[1], self._k[0]); self.reset(); return "ok", sess
