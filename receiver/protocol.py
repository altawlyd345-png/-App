"""BLE Remote protocol v2 (shared by Sender and Receiver).
Envelope : [len:4][crc32:4][JSON body]   body = {"id","t","d","s"?}
Fragment : [msg:2][idx:2][total:2][payload]
Sender->Receiver types: apply_text, apply_design, apply_playlist, clear, hide, restore, reload,
                        next, prev, emergency, emergency_off, ping, set_pin, font, image
Receiver->Sender: ack {"id","ok"}
"s" = HMAC-SHA256 signature (pairing key) over id|t|data. Nothing is shown on Receiver without an explicit apply."""
import hashlib, hmac, json, struct, time, uuid, zlib

SERVICE = "12345678-1234-5678-1234-56789abcdef0"
WRITE_CHAR = "12345678-1234-5678-1234-56789abcdef1"
NOTIFY_CHAR = "12345678-1234-5678-1234-56789abcdef2"
_counter = [0]

def new_id():
    return uuid.uuid4().hex[:12]

def make_key(pin):
    return hashlib.sha256(("ble-remote:" + pin).encode("utf-8")).hexdigest()

def _canon(id_, t, d):
    return "%s|%s|%s" % (id_, t, json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":")))

def sign(key, id_, t, d):
    return hmac.new(bytes.fromhex(key), _canon(id_, t, d).encode("utf-8"), hashlib.sha256).hexdigest()

def verify(msg, key):
    try:
        return bool(key) and hmac.compare_digest(str(msg.get("s", "")), sign(key, msg["id"], msg["t"], msg.get("d") or {}))
    except Exception:
        return False

def encode(type_, data=None, id_=None, key=None):
    id_ = id_ or new_id(); data = data or {}
    m = {"id": id_, "t": type_, "d": data}
    if key:
        m["s"] = sign(key, id_, type_, data)
    body = json.dumps(m, ensure_ascii=False).encode("utf-8")
    return struct.pack(">II", len(body), zlib.crc32(body) & 0xFFFFFFFF) + body

def fragment(envelope, chunk_size):
    size = max(8, chunk_size - 6)
    _counter[0] = (_counter[0] + 1) & 0xFFFF
    parts = [envelope[i:i + size] for i in range(0, len(envelope), size)] or [b""]
    return [struct.pack(">HHH", _counter[0], i, len(parts)) + p for i, p in enumerate(parts)]

class Reassembler:
    def __init__(self):
        self.buf = {}
    def feed(self, packet):
        if len(packet) < 6:
            return None
        mid, idx, total = struct.unpack(">HHH", packet[:6])
        parts = self.buf.setdefault(mid, {})
        parts[idx] = packet[6:]
        if len(parts) < total:
            return None
        env = b"".join(parts[i] for i in range(total) if i in parts)
        del self.buf[mid]
        if len(env) < 8:
            return None
        ln, crc = struct.unpack(">II", env[:8])
        body = env[8:8 + ln]
        if len(body) != ln or (zlib.crc32(body) & 0xFFFFFFFF) != crc:
            return None
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            return None

def dyn_text(d):
    """Live text for clock/date/countdown elements; None for ordinary elements."""
    k = d.get("k")
    if k == "clock":
        return time.strftime("%H:%M:%S")
    if k == "date":
        return time.strftime("%Y-%m-%d")
    if k == "countdown":
        try:
            t = time.mktime(time.strptime(str(d.get("text", "")).strip(), "%Y-%m-%d %H:%M"))
        except Exception:
            return "--:--:--"
        r = max(0, int(t - time.time()))
        dd, r = divmod(r, 86400); hh, r = divmod(r, 3600); mm, ss = divmod(r, 60)
        return "%d:%02d:%02d:%02d" % (dd, hh, mm, ss)
    return None

def shape(text):
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text

def to_bytes(java_arr):
    return bytes((b & 0xFF) for b in java_arr)
