import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests")); sys.path.insert(0, str(ROOT / "shared"))
import kivy_stub; kivy_stub.install()
from kivy_stub import Clock
import studio as S, layers_view as LV

def make(layers, w=1000, h=500):
    Clock.reset(); v = LV.LayersView(); v.width, v.height = w, h; v.set_layers(layers); return v

class RenderTests(unittest.TestCase):
    def test_every_template_builds_and_runs_5_seconds(self):
        for tid in S.template_ids():
            v = make(S.build_template(tid)["layers"]); Clock.tick(5.0)
            self.assertEqual(len(v.children), len(v.rt), tid)

    def test_continuous_ticker_scrolls_rtl_wraps_and_pauses(self):
        v = make([{"id": "t", "kind": "ticker", "items": ["a", "b"], "mode": "continuous", "dir": "rtl", "speed": 10}])
        rt = v.rt["t"]; lbl = rt.lbl; lbl.width = 200
        Clock.tick(0.5); x0 = lbl.x; Clock.tick(0.5); self.assertLess(lbl.x, x0)          # moves left
        v.control("t", "pause"); xp = lbl.x; Clock.tick(1.0); self.assertEqual(lbl.x, xp)  # paused
        v.control("t", "resume"); Clock.tick(6.0)                                            # long enough to wrap
        self.assertGreater(lbl.x, -2000); self.assertTrue(lbl.right >= rt.st.x - 1)

    def test_ltr_moves_right(self):
        v = make([{"id": "t", "kind": "ticker", "items": ["a"], "dir": "ltr", "speed": 10}]); lbl = v.rt["t"].lbl; lbl.width = 100; v.rt["t"].st.width = 1000
        Clock.tick(0.5); x0 = lbl.x; Clock.tick(0.5); self.assertGreater(lbl.x, x0)

    def test_sequential_cycles_items(self):
        v = make([{"id": "t", "kind": "ticker", "items": ["one", "two", "three"], "mode": "sequential", "seq_hold": 1.0}])
        seen = {v.rt["t"].lbl.text}
        for _ in range(4): Clock.tick(1.0); seen.add(v.rt["t"].lbl.text)
        self.assertEqual(len(seen), 3)

    def test_sequential_pause_holds_current_item(self):
        v = make([{"id": "t", "kind": "ticker", "items": ["one", "two"], "mode": "sequential", "seq_hold": 1.0}])
        v.control("t", "pause"); t0 = v.rt["t"].lbl.text; Clock.tick(5.0); self.assertEqual(v.rt["t"].lbl.text, t0)

    def test_static_ticker_shows_all_items_joined(self):
        v = make([{"id": "t", "kind": "ticker", "items": ["a", "b"], "mode": "static", "sep": " | "}])
        self.assertIn("|", v.rt["t"].lbl.text)

    def test_typewriter_and_word_reveal_complete(self):
        for kind, expect in (("typewriter", "hello world"), ("word", "hello world")):
            v = make([{"id": "m", "kind": "text", "text": "hello world", "anim_in": kind, "dur": 1.0}]); Clock.tick(3.0)
            self.assertEqual(v.rt["m"].lbl.text, expect, kind)

    def test_layers_are_independent(self):
        v = make([{"id": "m", "kind": "text", "text": "hello world", "anim_in": "typewriter", "dur": 1.0},
                  {"id": "t", "kind": "ticker", "items": ["a"], "speed": 10}])
        v.control("t", "pause"); v.control("t", "hide"); Clock.tick(3.0)
        self.assertEqual(v.rt["m"].lbl.text, "hello world"); self.assertEqual(v.rt["m"].box.opacity, 1.0)   # main untouched
        self.assertEqual(v.rt["t"].box.opacity, 0)

    def test_hide_show_and_restart(self):
        v = make([{"id": "m", "kind": "text", "text": "x", "opacity": 0.7}]); Clock.tick(1.0)
        self.assertTrue(v.control("m", "hide")); self.assertEqual(v.rt["m"].box.opacity, 0)
        self.assertTrue(v.control("m", "show")); self.assertAlmostEqual(v.rt["m"].box.opacity, 0.7)
        self.assertTrue(v.control("m", "restart"))

    def test_bad_control_rejected(self):
        v = make([{"id": "m", "kind": "text", "text": "x"}])
        self.assertFalse(v.control("nope", "pause")); self.assertFalse(v.control("m", "explode"))

    def test_hidden_layer_starts_invisible_and_anim_out_hides(self):
        v = make([{"id": "h", "kind": "text", "text": "x", "hidden": True}]); Clock.tick(1.0); self.assertEqual(v.rt["h"].box.opacity, 0)
        v = make([{"id": "o", "kind": "text", "text": "x", "anim_out": "fade", "hold": 1.0, "dur": 0.5}]); Clock.tick(4.0)
        self.assertEqual(v.rt["o"].box.opacity, 0)

    def test_stop_cancels_all_timers_and_rebuild_replaces(self):
        v = make(S.build_template("news_tv")["layers"]); v.stop(); alive = [j for j in Clock.jobs if not j["dead"]]; self.assertEqual(alive, [])
        v.set_layers(S.build_template("info")["layers"]); self.assertEqual(len(v.children), 3)

    def test_garbage_layers_do_not_crash(self):
        v = make([{"kind": "ticker", "items": None, "speed": "zzz", "anim_in": "spin"}, "junk", {"kind": "box"}]); Clock.tick(2.0)

if __name__ == "__main__": unittest.main()
