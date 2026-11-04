import os
import sys
import tempfile
import unittest
from pathlib import Path

# Make tests runnable from the repository root or from this directory.
ROOT = Path(__file__).resolve().parents[1]
RECEIVER = ROOT / "receiver"
if str(RECEIVER) not in sys.path:
    sys.path.insert(0, str(RECEIVER))

from commands import parse
from library import LibraryIndex


class CommandTests(unittest.TestCase):
    def test_arabic_video_command(self):
        self.assertEqual(parse('شغل فيديو الترحيب')['kind'], 'video')
        self.assertEqual(parse('شغل فيديو الترحيب')['query'], 'الترحيب')

    def test_latest_image(self):
        result = parse('اعرض آخر صورة')
        self.assertEqual(result['action'], 'play')
        self.assertEqual(result['kind'], 'image')
        self.assertTrue(result['newest'])

    def test_stats_and_refresh(self):
        self.assertEqual(parse('احصائيات المكتبة')['action'], 'stats')
        self.assertEqual(parse('تحديث المكتبة')['action'], 'refresh')

    def test_alias_command(self):
        result = parse('سم الملف IMG_123.jpg باسم السيارة')
        self.assertEqual(result['action'], 'alias')
        self.assertEqual(result['alias'], 'السيارة')


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), 'library.sqlite3')
        self.db = LibraryIndex(self.path)

    def tearDown(self):
        self.db.close()

    def test_search_alias_and_persistence(self):
        self.db.refresh([
            {'uri': 'content://image/1', 'kind': 'image', 'name': 'IMG سيارة حمراء.jpg', 'date': 10, 'size': 1234},
            {'uri': 'content://video/2', 'kind': 'video', 'name': 'Welcome 2026.mp4', 'date': 20, 'size': 4567},
        ])
        self.assertEqual(len(self.db.search('سياره حمراء', 'image')), 1)
        self.assertTrue(self.db.set_alias('IMG سيارة', 'السيارة'))
        self.assertEqual(len(self.db.search('السيارة')), 1)
        self.assertEqual(self.db.stats()['total'], 2)


if __name__ == '__main__':
    unittest.main()
