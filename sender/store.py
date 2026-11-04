import json, os, time, uuid

DEFAULT = {"memos": [], "pages": [], "templates": [], "playlists": [],
           "schedules": [], "projects": [], "media": [], "scenes": [], "log": [], "settings": {}}

class Store:
    def __init__(self, path):
        self.path = path
        self.d = json.loads(json.dumps(DEFAULT))
        try:
            with open(path, encoding="utf-8") as f:
                self.d.update(json.load(f))
        except Exception:
            pass

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.d, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def items(self, col, q=""):
        q = q.strip().lower()
        out = [i for i in self.d[col] if not q or q in json.dumps(i, ensure_ascii=False).lower()]
        return sorted(out, key=lambda i: (not i.get("fav"), i.get("name", "")))

    def put(self, col, item):
        item = dict(item)
        item.setdefault("id", uuid.uuid4().hex[:8])
        item["ts"] = int(time.time())
        lst = self.d[col]
        for n, o in enumerate(lst):
            if o["id"] == item["id"]:
                lst[n] = item; break
        else:
            lst.append(item)
        self.save(); return item

    def delete(self, col, id_):
        self.d[col] = [i for i in self.d[col] if i["id"] != id_]
        self.save()

    def log(self, text):
        self.d["log"].append({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "m": text})
        self.d["log"] = self.d["log"][-300:]
        self.save()

    def export_to(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in self.d.items() if k != "log"}, f, ensure_ascii=False)

    def import_from(self, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for k in DEFAULT:
            if k in data and k != "log":
                self.d[k] = data[k]
        self.save()
