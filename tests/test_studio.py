import copy, json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
import studio as S

class Normalize(unittest.TestCase):
    def test_garbage_never_raises(self):
        for bad in (None, 5, "x", [], {"kind": "nope", "x": "abc", "w": float("nan"), "items": 7, "bg": "red", "speed": "fast"}):
            l = S.normalize_layer(bad); self.assertIn(l["kind"], S.KINDS); self.assertTrue(0.02 <= l["w"] <= 1)
    def test_clamps_and_enums(self):
        l = S.normalize_layer({"kind": "ticker", "speed": 99, "dur": 99, "anim_in": "spin", "mode": "x", "dir": "up", "opacity": 3, "size": 9})
        self.assertEqual((l["speed"], l["dur"], l["anim_in"], l["mode"], l["dir"], l["opacity"], l["size"]), (10, 5.0, "none", "continuous", "rtl", 1.0, 0.5))
    def test_ticker_items_from_text_and_limits(self):
        l = S.normalize_layer({"kind": "ticker", "items": "a\n\n b \n" + "\n".join("x%d" % i for i in range(80))})
        self.assertEqual(l["items"][:2], ["a", "b"]); self.assertEqual(len(l["items"]), S.MAX_ITEMS)
    def test_color_validation_and_empty_bg(self):
        self.assertEqual(S.normalize_layer({"kind": "text", "color": "#abcdef"})["color"], "#ABCDEF")
        self.assertEqual(S.normalize_layer({"kind": "text", "color": "javascript"})["color"], "#FFFFFF")
        self.assertEqual(S.normalize_layer({"kind": "text", "bg": ""})["bg"], "")
    def test_v7_scene_untouched(self):
        sc = {"bg": "#000000", "text": {"msgs": ["a"], "mode": "static"}, "visual": {"kind": "image"}}
        self.assertEqual(S.normalize_scene(sc), sc)          # no layers key -> identical
    def test_scene_layers_cleaned_unique_ids(self):
        sc = S.normalize_scene({"layers": [{"id": "a"}, {"id": "a"}, "junk", {"kind": "box", "id": "b"}]})
        ids = [l["id"] for l in sc["layers"]]; self.assertEqual(len(ids), 3); self.assertEqual(len(set(ids)), 3)
    def test_idempotent(self):
        sc = S.build_template("news_tv"); self.assertEqual(S.normalize_scene(sc), sc)

class Ops(unittest.TestCase):
    def setUp(self):
        self.ls = []; [S.add_layer(self.ls, {"id": i}) for i in "abc"]
    def test_move_and_bounds(self):
        self.assertTrue(S.move_layer(self.ls, "a", 1)); self.assertEqual([l["id"] for l in self.ls], ["b", "a", "c"])
        self.assertFalse(S.move_layer(self.ls, "c", 5)); self.assertTrue(S.move_layer(self.ls, "c", -9)); self.assertEqual(self.ls[0]["id"], "c")
    def test_locked_cannot_be_removed(self):
        S.set_flag(self.ls, "a", "locked", True); self.assertFalse(S.remove_layer(self.ls, "a")); self.assertTrue(S.remove_layer(self.ls, "b"))
    def test_duplicate_gets_new_id_unlocked(self):
        S.set_flag(self.ls, "a", "locked", True); c = S.duplicate_layer(self.ls, "a")
        self.assertNotEqual(c["id"], "a"); self.assertFalse(c["locked"]); self.assertEqual(len(self.ls), 4)
    def test_max_layers(self):
        ls = []
        for _ in range(S.MAX_LAYERS + 5): S.add_layer(ls, {})
        self.assertEqual(len(ls), S.MAX_LAYERS)

class Helpers(unittest.TestCase):
    def test_reveal(self):
        self.assertEqual(S.reveal("مرحبا بكم جميعا", "word", 2), "مرحبا بكم"); self.assertEqual(S.reveal("abc", "typewriter", 2), "ab")
        self.assertEqual(S.reveal_steps("a b c", "word"), 3); self.assertEqual(S.reveal("abc", "typewriter", -4), "")
    def test_ticker_helpers(self):
        l = S.normalize_layer({"kind": "ticker", "items": ["أ", "ب"], "sep": " | "})
        self.assertEqual(S.ticker_text(l), "أ | ب"); self.assertEqual(S.ticker_item(l, 3), "ب"); self.assertEqual(S.ticker_item({"items": []}, 1), "")
    def test_speed(self):
        self.assertAlmostEqual(S.ticker_speed_px(5, 1000), 150.0); self.assertAlmostEqual(S.ticker_speed_px(99, 1000), 300.0)

class Templates(unittest.TestCase):
    def test_all_six_build_valid_json_scenes_with_main_and_news(self):
        self.assertEqual(len(S.TEMPLATES), 6)
        for tid in S.template_ids():
            sc = S.build_template(tid); json.dumps(sc, ensure_ascii=False)
            ids = {l["id"] for l in sc["layers"]}; self.assertTrue({"main", "news"} <= ids, tid)
            for l in sc["layers"]: self.assertTrue(0 <= l["x"] <= 1 and 0 < l["w"] <= 1, (tid, l["id"]))
    def test_values_override_and_ticker_string(self):
        sc = S.build_template("breaking", {"main": "خبر جديد", "ticker": "أ\nب"})
        self.assertEqual(S.find(sc["layers"], "main")["text"], "خبر جديد"); self.assertEqual(S.find(sc["layers"], "news")["items"], ["أ", "ب"])
    def test_unknown_template(self):
        with self.assertRaises(KeyError): S.build_template("zzz")

class CopiesInSync(unittest.TestCase):
    def test_app_copies_match_shared(self):
        base = (ROOT / "shared" / "studio.py").read_text()
        for app in ("sender", "receiver"): self.assertEqual((ROOT / app / "studio.py").read_text(), base)

if __name__ == "__main__": unittest.main()

class LayerCommand(unittest.TestCase):
    def test_valid_and_invalid(self):
        self.assertEqual(S.valid_layer_command({"id": "news", "action": "pause"}), ("news", "pause"))
        for bad in (None, {}, {"id": "", "action": "pause"}, {"id": "a", "action": "explode"}, {"id": "a"}, "x"):
            self.assertIsNone(S.valid_layer_command(bad))

class BleRoundTrip(unittest.TestCase):
    def test_every_template_survives_ble_fragmentation(self):
        sys.path.insert(0, str(ROOT / "shared")); import protocol as P
        for tid in S.template_ids():
            sc = S.build_template(tid); r = P.Reassembler(); out = None
            for f in P.fragment(P.encode("apply_scene", sc), 244): out = r.feed(f) or out
            self.assertEqual(out["d"], json.loads(json.dumps(sc)), tid)
            self.assertEqual(S.normalize_scene(out["d"]), sc, tid)

class MoreCopies(unittest.TestCase):
    def test_layers_view_copies_match(self):
        base = (ROOT / "shared" / "layers_view.py").read_text()
        for app in ("sender", "receiver"): self.assertEqual((ROOT / app / "layers_view.py").read_text(), base)
