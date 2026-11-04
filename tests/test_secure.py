import os, sys, time, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
import secure as X

h = bytes.fromhex

class Vectors(unittest.TestCase):
    def test_x25519_rfc7748_5_2(self):
        k = h("a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4")
        u = h("e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c")
        self.assertEqual(X.x25519(k, u).hex(), "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552")
    def test_x25519_rfc7748_6_1_diffie_hellman(self):
        a = h("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"); b = h("5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb")
        A, B = X.x25519(a, X._BASE), X.x25519(b, X._BASE)
        self.assertEqual(A.hex(), "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a")
        self.assertEqual(B.hex(), "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f")
        self.assertEqual(X.shared_secret(a, B).hex(), "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742")
        self.assertEqual(X.shared_secret(a, B), X.shared_secret(b, A))
    def test_hkdf_rfc5869_case1(self):
        okm = X.hkdf(h("0b" * 22), h("000102030405060708090a0b0c"), h("f0f1f2f3f4f5f6f7f8f9"), 42)
        self.assertEqual(okm.hex(), "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865")
    def test_chacha20poly1305_rfc8439_2_8_2(self):
        key = bytes(range(0x80, 0xa0)); nonce = h("070000004041424344454647"); aad = h("50515253c0c1c2c3c4c5c6c7")
        pt = b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, sunscreen would be it."
        out = X.aead_encrypt(key, nonce, pt, aad)
        self.assertEqual(out[-16:].hex(), "1ae10b594f09e26a7e902ecbd0600691"); self.assertTrue(out.hex().startswith("d31a8d34648e60db7b86afbc53ef7ec2"))
        self.assertEqual(X.aead_decrypt(key, nonce, out, aad), pt)

class CrossCheck(unittest.TestCase):
    """Compare with the reference `cryptography` library on random inputs."""
    @classmethod
    def setUpClass(cls):
        try:
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
            from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
            from cryptography.hazmat.primitives import serialization
            cls.lib = (X25519PrivateKey, X25519PublicKey, ChaCha20Poly1305, serialization)
        except ImportError: raise unittest.SkipTest("cryptography not installed")
    def test_x25519_random(self):
        Priv, Pub, _, ser = self.lib
        for _ in range(10):
            a, b = os.urandom(32), os.urandom(32)
            ref = Priv.from_private_bytes(a).exchange(Pub.from_public_bytes(X.x25519(b, X._BASE)))
            self.assertEqual(X.shared_secret(a, X.x25519(b, X._BASE)), ref)
    def test_aead_random_sizes(self):
        C = self.lib[2]
        for n in (0, 1, 15, 16, 17, 63, 64, 65, 1000, 4096):
            k, nonce, pt, aad = os.urandom(32), os.urandom(12), os.urandom(n), os.urandom(7)
            self.assertEqual(X.aead_encrypt(k, nonce, pt, aad), C(k).encrypt(nonce, pt, aad))
            self.assertEqual(C(k).decrypt(nonce, X.aead_encrypt(k, nonce, pt, aad), aad), pt)

class SessionTests(unittest.TestCase):
    def setUp(self):
        k1, k2 = os.urandom(32), os.urandom(32)
        self.s = X.Session("sender", k1, k2); self.r = X.Session("receiver", k2, k1)
    def test_roundtrip_both_directions(self):
        m = {"id": "a1", "t": "apply_text", "d": {"text": "مرحبا بالعالم"}}
        self.assertEqual(self.r.unwrap(self.s.wrap(m)), m)
        self.assertEqual(self.s.unwrap(self.r.wrap({"id": "a1", "t": "ack", "d": {"ok": True}}))["t"], "ack")
    def test_replay_rejected(self):
        f = self.s.wrap({"id": "1", "t": "ping", "d": {}}); self.r.unwrap(f)
        with self.assertRaises(X.SecureError): self.r.unwrap(f)
    def test_old_counter_rejected_after_newer(self):
        f1 = self.s.wrap({"id": "1", "t": "ping", "d": {}}); f2 = self.s.wrap({"id": "2", "t": "ping", "d": {}})
        self.r.unwrap(f2)
        with self.assertRaises(X.SecureError): self.r.unwrap(f1)
    def test_tamper_rejected_and_counter_not_advanced(self):
        f = self.s.wrap({"id": "1", "t": "ping", "d": {}}); bad = dict(f); raw = bytearray(__import__("base64").b64decode(bad["b"])); raw[3] ^= 1
        bad["b"] = __import__("base64").b64encode(bytes(raw)).decode()
        with self.assertRaises(X.SecureError): self.r.unwrap(bad)
        self.assertEqual(self.r.unwrap(f)["id"], "1")                      # genuine frame still accepted
    def test_counter_field_tamper_rejected(self):
        f = self.s.wrap({"id": "1", "t": "ping", "d": {}}); f["c"] = 99
        with self.assertRaises(X.SecureError): self.r.unwrap(f)
    def test_reflection_rejected(self):
        f = self.s.wrap({"id": "1", "t": "ping", "d": {}})
        with self.assertRaises(X.SecureError): self.s.unwrap(f)            # own frame sent back
    def test_wrong_key_and_garbage(self):
        other = X.Session("receiver", os.urandom(32), os.urandom(32)); f = self.s.wrap({"id": "1", "t": "ping", "d": {}})
        for bad in (f, {"c": 1}, {"b": "zz"}, {"c": True, "b": f["b"]}, {"c": "1", "b": f["b"]}, None, 5):
            with self.assertRaises(X.SecureError): other.unwrap(bad)
    def test_persistence_keeps_counters(self):
        f1 = self.s.wrap({"id": "1", "t": "ping", "d": {}}); self.r.unwrap(f1)
        r2 = X.Session.from_dict(self.r.to_dict())
        with self.assertRaises(X.SecureError): r2.unwrap(f1)               # replay after restart still blocked
        self.assertEqual(r2.unwrap(self.s.wrap({"id": "2", "t": "ping", "d": {}}))["id"], "2")
    def test_too_large(self):
        with self.assertRaises(X.SecureError): self.s.wrap({"id": "x", "t": "t", "d": {"b": "a" * 70000}})
    def test_speed_is_acceptable(self):
        m = {"id": "x", "t": "apply_scene", "d": {"t": "ن" * 1500}}; t = time.time()
        for _ in range(5): self.r.unwrap(self.s.wrap(m))
        self.assertLess((time.time() - t) / 5, 0.25)

class PairingTests(unittest.TestCase):
    def flow(self, accept=True, clock=None):
        s = X.PairSender(); r = X.PairReceiver(now=clock or time.time)
        reply = r.on_begin(s.begin()["pub"]); sas_s = s.on_reply(reply["pub"])
        if accept: r.accept()
        return s, r, sas_s
    def test_success_same_sas_and_working_channel(self):
        s, r, sas_s = self.flow(); self.assertEqual(sas_s, r.sas); self.assertRegex(sas_s, r"^\d{3} \d{3}$")
        st, sess_r = r.on_confirm(s.proof()["proof"]); self.assertEqual(st, "ok"); sess_s = s.session()
        m = {"id": "1", "t": "apply_text", "d": {"text": "x"}}
        self.assertEqual(sess_r.unwrap(sess_s.wrap(m)), m); self.assertEqual(sess_s.unwrap(sess_r.wrap({"id": "1", "t": "ack", "d": {}}))["t"], "ack")
    def test_pending_until_user_accepts_on_receiver(self):
        s, r, _ = self.flow(accept=False)
        self.assertEqual(r.on_confirm(s.proof()["proof"])[0], "pending"); r.accept(); self.assertEqual(r.on_confirm(s.proof()["proof"])[0], "ok")
    def test_mitm_gets_different_codes(self):
        s = X.PairSender(); r = X.PairReceiver()
        mallory = X.PairReceiver(); m_reply = mallory.on_begin(s.begin()["pub"])            # attacker answers the sender
        ms = X.PairSender(); r_reply = r.on_begin(ms.begin()["pub"])                         # attacker talks to the receiver
        sas_sender = s.on_reply(m_reply["pub"]); ms.on_reply(r_reply["pub"])
        self.assertNotEqual(sas_sender, r.sas)                                               # the user sees different codes and refuses
    def test_attacker_cannot_confirm_without_matching_proof(self):
        s, r, _ = self.flow(); evil = X.PairSender(); evil.on_reply(r.pub.hex())            # different public key
        self.assertEqual(r.on_confirm(evil.proof()["proof"])[0], "bad")
    def test_three_bad_proofs_reset(self):
        s, r, _ = self.flow()
        for _ in range(3): r.on_confirm("00" * 32)
        self.assertEqual(r.on_confirm(s.proof()["proof"])[0], "expired")
    def test_expiry(self):
        t = [1000.0]; s, r, _ = self.flow(clock=lambda: t[0]); t[0] += X.PAIR_WINDOW + 1
        self.assertEqual(r.on_confirm(s.proof()["proof"])[0], "expired"); self.assertFalse(r.accept())
    def test_bad_inputs(self):
        r = X.PairReceiver()
        for bad in ("zz", "00" * 31, None, "00" * 32):
            with self.assertRaises(X.SecureError): r.on_begin(bad)                           # all-zero key = low-order point
        with self.assertRaises(X.SecureError): X.PairSender().on_reply("11" * 3)
    def test_decline_clears_state(self):
        s, r, _ = self.flow(); r.decline(); self.assertEqual(r.on_confirm(s.proof()["proof"])[0], "expired")

class CopiesInSync(unittest.TestCase):
    def test_copies(self):
        base = (ROOT / "shared" / "secure.py").read_text()
        for app in ("sender", "receiver"): self.assertEqual((ROOT / app / "secure.py").read_text(), base)

if __name__ == "__main__": unittest.main()
