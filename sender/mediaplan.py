"""Pure helpers (no Kivy) for browsing the Receiver's own media and building scenes from it.
Files are referenced by their original content URI on the Receiver: nothing is copied to the Sender."""
import re

KINDS = ("image", "video", "audio")

def _norm(s):
    s = str(s or "").lower().translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))
    return re.sub(r"\s+", " ", s).strip()

def filter_items(items, kind, query="", limit=150):
    """Newest first, one kind, every query word must appear in the name."""
    words = _norm(query).split()
    rows = [i for i in items if i.get("kind") == kind and all(w in _norm(i.get("name", "")) for w in words)]
    rows.sort(key=lambda i: -int(i.get("date") or 0))
    return rows[:limit], len(rows)

def scene_for(item, repeat=False, cover=False):
    media = {"kind": item["kind"], "src": "gallery", "uri": item["uri"], "name": item.get("name", ""),
             "loop": True if item["kind"] == "image" else bool(repeat)}
    sc = {"bg": "#000000"}
    if item["kind"] == "image":
        media["fit"] = "cover" if cover else "contain"; sc["visual"] = media
    elif item["kind"] == "video":
        sc["visual"] = media
    else:
        sc["audio"] = media
        sc["text"] = {"msgs": [item.get("name", "")], "color": "#FFFFFF", "size": 40, "mode": "static", "align": "center"}
    return sc

def playlist_payload(items, secs=10, repeat=False, cover=False):
    scenes = [scene_for(i, repeat, cover) for i in items if i.get("kind") in KINDS and i.get("uri")]
    try: secs = max(2, int(secs))
    except (TypeError, ValueError): secs = 10
    return {"scenes": scenes, "secs": secs, "loop": True}

def fmt_time(ms):
    try: s = max(0, int(ms) // 1000)
    except (TypeError, ValueError): s = 0
    return "%d:%02d" % divmod(s, 60)
