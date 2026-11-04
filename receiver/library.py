"""Persistent metadata index for Receiver's MediaStore library.
Stores metadata and content URIs, never duplicates media bytes.
"""
import json
import os
import sqlite3
import time
import threading
import re

def _norm(value):
    table = str.maketrans({'أ':'ا','إ':'ا','آ':'ا','ى':'ي','ة':'ه','ؤ':'و','ئ':'ي'})
    return re.sub(r"\s+", " ", str(value or "").lower().translate(table)).strip()


class LibraryIndex:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.execute("""CREATE TABLE IF NOT EXISTS media (
            uri TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
            date_added INTEGER DEFAULT 0, size INTEGER DEFAULT 0,
            alias TEXT DEFAULT '', tags TEXT DEFAULT '', last_seen INTEGER DEFAULT 0
        )""")
        self.db.execute("CREATE INDEX IF NOT EXISTS media_kind_date ON media(kind, date_added DESC)")
        self.db.commit()

    def refresh(self, items):
        now = int(time.time())
        rows = []
        for item in items:
            uri = str(item.get('uri') or '')
            kind = str(item.get('kind') or '')
            if not uri or kind not in ('image', 'video', 'audio'):
                continue
            rows.append((uri, str(item.get('name') or 'بدون اسم'), kind,
                         int(item.get('date') or 0), int(item.get('size') or 0), now))
        with self.lock, self.db:
            self.db.executemany("""INSERT INTO media(uri,name,kind,date_added,size,last_seen)
                VALUES(?,?,?,?,?,?) ON CONFLICT(uri) DO UPDATE SET
                name=excluded.name, kind=excluded.kind, date_added=excluded.date_added,
                size=CASE WHEN excluded.size>0 THEN excluded.size ELSE media.size END,
                last_seen=excluded.last_seen""", rows)
        return len(rows)

    def search(self, query='', kind=None, limit=50, newest=False):
        sql = "SELECT * FROM media WHERE 1=1"
        args = []
        if kind in ('image', 'video', 'audio'):
            sql += " AND kind=?"; args.append(kind)
        sql += " ORDER BY date_added DESC" if newest else " ORDER BY name COLLATE NOCASE ASC"
        with self.lock:
            candidates = [dict(r) for r in self.db.execute(sql, args).fetchall()]
        terms = [w for w in _norm(query).split() if w not in ('التي', 'الذي', 'تحتوي', 'يحتوي', 'فيها', 'عليها', 'على', 'علي', 'في', 'من', 'عن', 'ملف', 'ملفات')]
        if terms:
            def matches(row):
                hay = _norm(' '.join((row.get('name') or '', row.get('alias') or '', row.get('tags') or '')))
                return all(term in hay for term in terms)
            candidates = [row for row in candidates if matches(row)]
        return candidates[:max(1, min(int(limit), 200))]

    def set_alias(self, query, alias):
        rows = self.search(query, limit=2)
        if not rows:
            return False
        with self.lock, self.db:
            self.db.execute("UPDATE media SET alias=? WHERE uri=?", (alias.strip(), rows[0]['uri']))
        return True

    def stats(self):
        with self.lock:
            rows = self.db.execute("SELECT kind,COUNT(*) AS n FROM media GROUP BY kind").fetchall()
        out = {'image': 0, 'video': 0, 'audio': 0}
        for row in rows: out[row['kind']] = row['n']
        out['total'] = sum(out.values())
        return out

    def close(self):
        self.db.close()
