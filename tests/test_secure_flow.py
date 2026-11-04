import json, os, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
import secure as X, secure_flow as F, protocol as P

def over_ble(env, chunk=185):
    """Push an envelope through real BLE-style fragmentation and back."""
    r = P.Reassembler(); out = None
    for f in P.fragment(env, chunk): out = r.feed(f) or out
    return out

class Rig:
    """A Receiver router and a Sender facade wired together, no Kivy."""
    def __init__(self, tmp=None):
        self.tmp = tmp or tempfile.mkdtemp(); self.rpath = os.path.join(self.tmp, "r.json"); self.spath = os.path.join(self.tmp, "s.json")
        self.R = F.ReceiverSecurity(self.rpath, "rid12345"); self.S = F.SenderSecurity(self.spath); self.executed = []
    def to_receiver(self, type_, data, secure=None):
        mid, env = self.S.build(type_, data, secure); return mid, self.receive(over_ble(env))
    def receive(self, m):
        """Mimics Receiver.handle(): returns the (decoded, opened) reply message the Sender would see."""
        kind, pl = self.R.route(m)
        if kind == "drop": return None
        if kind == "plain": return self.S.open_frame(over_ble(P.encode("ack", pl)))
        if kind == "pair_begin":
            mid, d = pl; ok, body, sas = self.R.begin(d); self.r_sas = sas
            return self.S.open_frame(over_ble(P.encode("ack", {"id": mid, "ok": ok, **body})))
        if kind == "pair_confirm":
            mid, d = pl; st, body = self.R.confirm(d)
            secure = st == "ok"
            env = self.R.ack_envelope(mid, {"ok": secure, **body}, secure)
            return self.S.open_frame(over_ble(env))
        msg, secure = pl; self.executed.append((msg["t"], msg.get("d"), secure))
        extra = {"rid": "rid12345", "paired": self.R.paired} if msg["t"] == "hello" and not secure else {}
        if msg["t"] == "hello" and secure: extra = {"ip": "192.168.1.5", "port": 8765, "token": "tok"}
        if msg["t"] == "unpair": env = self.R.ack_envelope(msg["id"], {"ok": True}, secure); self.R.unpair(); return self.S.open_frame(over_ble(env))
        return self.S.open_frame(over_ble(self.R.ack_envelope(msg["id"], {"ok": True, **extra}, secure)))
    def pair(self, accept=True):
        _, rep = self.to_receiver("hello", {}); self.S.note_hello(rep["d"] if "d" in rep else rep)
        body = self.S.start_pairing(); mid, env = self.S.build("pair_begin", body, secure=False)
        rep = self.receive(over_ble(env)); sas = self.S.on_pair_reply(rep["d"] if "d" in rep else rep)
        if accept: self.R.accept()
        mid, env = self.S.build("pair_confirm", self.S.confirm_body(), secure=False)
        return sas, self.receive(over_ble(env))

def body(m): return m.get("d", m)

class FlowTests(unittest.TestCase):
    def test_open_mode_is_unchanged_v8_behaviour(self):
        rig = Rig(); mid, rep = rig.to_receiver("apply_scene", {"bg": "#000000"})
        self.assertTrue(body(rep)["ok"]); self.assertEqual(rig.executed[-1], ("apply_scene", {"bg": "#000000"}, False))
        self.assertEqual(rig.S.note_hello({"ok": True}), "legacy")                       # old receivers still work

    def test_full_pairing_then_secure_commands(self):
        rig = Rig(); sas, rep = rig.pair()
        self.assertEqual(sas, rig.r_sas); self.assertTrue(body(rep)["ok"])
        self.assertTrue(rig.R.paired and rig.S.sess is not None and rig.S.cand is None)
        mid, rep = rig.to_receiver("apply_text", {"text": "سري"}); self.assertTrue(body(rep)["ok"])
        self.assertEqual(rig.executed[-1], ("apply_text", {"text": "سري"}, True))

    def test_pending_until_accept(self):
        rig = Rig(); sas, rep = rig.pair(accept=False)
        self.assertFalse(body(rep)["ok"]); self.assertEqual(body(rep)["result"], "pending"); self.assertFalse(rig.R.paired)
        rig.R.accept(); mid, env = rig.S.build("pair_confirm", rig.S.confirm_body(), secure=False)
        self.assertTrue(body(rig.receive(over_ble(env)))["ok"]); self.assertTrue(rig.R.paired)

    def test_stranger_cannot_control_a_paired_receiver(self):
        rig = Rig(); rig.pair(); n = len(rig.executed)
        stranger = F.SenderSecurity(os.path.join(rig.tmp, "x.json"))
        for t, d in (("clear", {}), ("apply_text", {"text": "x"}), ("status", {})):
            _, env = stranger.build(t, d); rep = rig.receive(over_ble(env)); self.assertFalse(body(rep)["ok"])
        self.assertEqual(len(rig.executed), n)
        s2 = F.SenderSecurity(os.path.join(rig.tmp, "y.json")); s2.rid = "rid12345"
        s2.sess = X.Session("sender", os.urandom(32), os.urandom(32))                    # forged key
        _, env = s2.build("clear", {}); rep = rig.receive(over_ble(env)); self.assertFalse(body(rep)["ok"]); self.assertEqual(len(rig.executed), n)

    def test_cannot_hijack_pairing_when_already_paired(self):
        rig = Rig(); rig.pair(); evil = F.SenderSecurity(os.path.join(rig.tmp, "e.json")); evil.rid = "rid12345"
        env = P.encode("pair_begin", X.PairSender().begin()); rep = rig.receive(over_ble(env)); self.assertFalse(body(rep)["ok"])
        self.assertTrue(rig.R.paired and not rig.R.pair.active)

    def test_replayed_frame_is_rejected(self):
        rig = Rig(); rig.pair(); mid, env = rig.S.build("apply_text", {"text": "a"}); frame = over_ble(env)
        rig.receive(frame); n = len(rig.executed); rep = rig.receive(frame)
        self.assertEqual(len(rig.executed), n); self.assertFalse(body(rep)["ok"])

    def test_plain_hello_when_paired_leaks_nothing(self):
        rig = Rig(); rig.pair(); _, rep = rig.to_receiver("hello", {})
        b = body(rep); self.assertEqual((b["rid"], b["paired"]), ("rid12345", True)); self.assertNotIn("token", b); self.assertNotIn("ip", b)
        self.assertEqual(rig.S.note_hello(b), "secure_hello")
        _, rep = rig.to_receiver("hello", {}, secure=True); self.assertEqual(body(rep)["token"], "tok")

    def test_both_sides_survive_restart(self):
        rig = Rig(); rig.pair(); rig.to_receiver("apply_text", {"text": "1"}); old_frame = over_ble(rig.S.build("ping", {})[1])
        R2 = F.ReceiverSecurity(rig.rpath, "rid12345"); S2 = F.SenderSecurity(rig.spath)
        rig.R, rig.S = R2, S2
        _, rep = rig.to_receiver("hello", {}); self.assertEqual(S2.note_hello(body(rep)), "secure_hello")
        _, rep = rig.to_receiver("apply_text", {"text": "2"}); self.assertTrue(body(rep)["ok"])
        n = len(rig.executed); rig.receive(old_frame); rig.receive(old_frame); self.assertLessEqual(len(rig.executed) - n, 1)   # old counter frame cannot run twice

    def test_unpair_restores_open_mode_and_forgets_key(self):
        rig = Rig(); rig.pair(); _, rep = rig.to_receiver("unpair", {}); self.assertTrue(body(rep)["ok"])
        self.assertFalse(rig.R.paired); rig.S.forget(); self.assertIsNone(rig.S.sess)
        _, rep = rig.to_receiver("apply_text", {"text": "x"}); self.assertTrue(body(rep)["ok"]); self.assertEqual(rig.executed[-1][2], False)
        self.assertEqual(rig.S.note_hello({"rid": "rid12345", "paired": False}), "open")

    def test_receiver_reset_makes_sender_drop_stale_key(self):
        rig = Rig(); rig.pair(); os.remove(rig.rpath); rig.R = F.ReceiverSecurity(rig.rpath, "rid12345")
        self.assertEqual(rig.S.note_hello({"rid": "rid12345", "paired": False}), "open"); self.assertNotIn("rid12345", json.load(open(rig.spath)))

    def test_new_sender_without_key_is_marked_foreign(self):
        rig = Rig(); rig.pair(); other = F.SenderSecurity(os.path.join(rig.tmp, "o.json"))
        self.assertEqual(other.note_hello({"rid": "rid12345", "paired": True}), "foreign")

    def test_garbage_messages_do_not_crash(self):
        rig = Rig()
        for m in (None, 5, {}, {"id": 1, "t": "x"}, {"id": "a", "t": "sec", "d": None}, {"id": "a", "t": "pair_begin", "d": 5}, {"id": "a", "t": "pair_confirm", "d": {}}):
            rig.receive(m)
        rig.pair(); rig.receive({"id": "a", "t": "sec", "d": {"c": 1, "b": "!!"}}); rig.receive({"id": "a", "t": "ping"})

    def test_wrong_proof_never_pairs(self):
        rig = Rig(); rig.to_receiver("hello", {}); rig.S.note_hello({"rid": "rid12345", "paired": False})
        body0 = rig.S.start_pairing(); mid, env = rig.S.build("pair_begin", body0, secure=False); rep = rig.receive(over_ble(env)); rig.S.on_pair_reply(body(rep)); rig.R.accept()
        for _ in range(3): rep = rig.receive(over_ble(P.encode("pair_confirm", {"proof": "00" * 32})))
        mid, env = rig.S.build("pair_confirm", rig.S.confirm_body(), secure=False); rep = rig.receive(over_ble(env))
        self.assertFalse(body(rep)["ok"]); self.assertFalse(rig.R.paired)

class CopiesInSync(unittest.TestCase):
    def test_copies(self):
        base = (ROOT / "shared" / "secure_flow.py").read_text()
        for app in ("sender", "receiver"): self.assertEqual((ROOT / app / "secure_flow.py").read_text(), base)

if __name__ == "__main__": unittest.main()
