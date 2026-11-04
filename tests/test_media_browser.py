import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "receiver", ROOT / "sender"):
    if str(p) not in sys.path: sys.path.insert(0, str(p))
import mediaplan, playback

ITEMS = [
    {"uri": "content://i/1", "kind": "image", "name": "IMG سيارة حمراء.jpg", "date": 10},
    {"uri": "content://i/2", "kind": "image", "name": "beach.jpg", "date": 30},
    {"uri": "content://v/1", "kind": "video", "name": "Welcome.mp4", "date": 20},
    {"uri": "content://a/1", "kind": "audio", "name": "نشيد.mp3", "date": 5},
]

class BrowserTests(unittest.TestCase):
    def test_filter_kind_query_and_order(self):
        rows, n = mediaplan.filter_items(ITEMS, "image")
        self.assertEqual([r["name"] for r in rows], ["beach.jpg", "IMG سيارة حمراء.jpg"]); self.assertEqual(n, 2)
        rows, _ = mediaplan.filter_items(ITEMS, "image", "سياره")
        self.assertEqual(len(rows), 1)
        self.assertEqual(mediaplan.filter_items(ITEMS, "video", "nothing")[0], [])

    def test_scene_uses_original_uri_not_a_copy(self):
        sc = mediaplan.scene_for(ITEMS[2], repeat=False)
        self.assertEqual(sc["visual"]["src"], "gallery"); self.assertEqual(sc["visual"]["uri"], "content://v/1")
        self.assertFalse(sc["visual"]["loop"])
        au = mediaplan.scene_for(ITEMS[3], repeat=True)
        self.assertTrue(au["audio"]["loop"]); self.assertEqual(au["text"]["msgs"], ["نشيد.mp3"])
        self.assertEqual(mediaplan.scene_for(ITEMS[0], cover=True)["visual"]["fit"], "cover")

    def test_playlist_payload(self):
        p = mediaplan.playlist_payload(ITEMS, secs="abc")
        self.assertEqual(len(p["scenes"]), 4); self.assertEqual(p["secs"], 10)
        self.assertEqual(mediaplan.playlist_payload(ITEMS, secs=1)["secs"], 2)

    def test_fmt_time(self):
        self.assertEqual(mediaplan.fmt_time(75000), "1:15"); self.assertEqual(mediaplan.fmt_time(None), "0:00")

class PlaybackTests(unittest.TestCase):
    def test_media_ended(self):
        self.assertTrue(playback.media_ended({"kind": "video", "playing": False, "pos": 9900, "dur": 10000}))
        self.assertFalse(playback.media_ended({"kind": "video", "playing": True, "pos": 9900, "dur": 10000}))
        self.assertFalse(playback.media_ended({"kind": "audio", "playing": False, "pos": 0, "dur": 0}))   # still preparing
        self.assertFalse(playback.media_ended({"kind": "none"}))
    def test_scene_media_only_non_looping(self):
        self.assertEqual(len(playback.scene_media(mediaplan.scene_for(ITEMS[2]))), 1)
        self.assertEqual(playback.scene_media(mediaplan.scene_for(ITEMS[2], repeat=True)), [])
        self.assertEqual(playback.scene_media(mediaplan.scene_for(ITEMS[0])), [])
    def test_volume_clamp(self):
        self.assertEqual(playback.clamp_volume(150), 100); self.assertEqual(playback.clamp_volume(-5), 0); self.assertIsNone(playback.clamp_volume("x"))

if __name__ == "__main__": unittest.main()
