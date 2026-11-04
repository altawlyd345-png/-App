"""BLE Remote V8 — scene-layer model (pure Python, no Kivy).
A V8 scene is a V7 scene plus an optional "layers" list drawn on top of the V7 background/media/text.
Coordinates are normalised to the screen: x,y = lower-left corner, w,h = size, all in 0..1.
Kinds: text | ticker | box.  Old scenes (no "layers") render exactly as before."""
import copy, re, uuid

IN_ANIMS = ("none", "fade", "slide_right", "slide_left", "zoom_in", "zoom_out", "typewriter", "word", "bounce")
OUT_ANIMS = ("none", "fade", "slide_right", "slide_left", "zoom_out")
TICKER_MODES = ("continuous", "sequential", "static")
TICKER_DIRS = ("rtl", "ltr")          # rtl: text travels from the right edge to the left edge
ALIGNS = ("right", "center", "left")
KINDS = ("text", "ticker", "box")
LAYER_ACTIONS = ("pause", "resume", "hide", "show", "restart")
MAX_LAYERS, MAX_ITEMS, MAX_ITEM_LEN = 30, 50, 300

BASE = {"id": "", "name": "", "kind": "text", "x": 0.1, "y": 0.4, "w": 0.8, "h": 0.2, "rotation": 0.0,
        "opacity": 1.0, "hidden": False, "locked": False,
        "anim_in": "none", "anim_out": "none", "dur": 0.6, "hold": 0.0}
TEXT = {"text": "", "size": 0.08, "color": "#FFFFFF", "bg": "", "bg_opacity": 1.0, "align": "center", "font": ""}
TICKER = {"items": [], "sep": "  ✦  ", "mode": "continuous", "dir": "rtl", "speed": 5, "seq_hold": 4.0,
          "size": 0.05, "color": "#FFFFFF", "bg": "#B71C1C", "bg_opacity": 1.0, "align": "center", "font": "",
          "paused": False}
BOX = {"bg": "#000000", "bg_opacity": 0.5}
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

def _num(v, lo, hi, default):
    try: v = float(v)
    except (TypeError, ValueError): return default
    if v != v: return default                      # NaN
    return max(lo, min(hi, v))

def _color(v, default):
    return v.upper() if isinstance(v, str) and _COLOR.match(v) else default

def _choice(v, allowed, default):
    return v if v in allowed else default

def new_id(prefix="L"):
    return "%s%s" % (prefix, uuid.uuid4().hex[:6])

def normalize_layer(d):
    """Return a clean, fully-defaulted copy of a layer (never raises on bad input)."""
    d = d if isinstance(d, dict) else {}
    kind = _choice(d.get("kind"), KINDS, "text")
    out = copy.deepcopy(BASE); out.update(copy.deepcopy({"text": TEXT, "ticker": TICKER, "box": BOX}[kind]))
    out["kind"] = kind
    out["id"] = str(d.get("id") or new_id())[:24]
    out["name"] = str(d.get("name", ""))[:60]
    out["w"] = _num(d.get("w"), 0.02, 1.0, out["w"]); out["h"] = _num(d.get("h"), 0.02, 1.0, out["h"])
    out["x"] = _num(d.get("x"), -0.5, 1.0, out["x"]); out["y"] = _num(d.get("y"), -0.5, 1.0, out["y"])
    out["rotation"] = _num(d.get("rotation"), -360, 360, 0.0)
    out["opacity"] = _num(d.get("opacity"), 0.0, 1.0, 1.0)
    out["hidden"] = bool(d.get("hidden", False)); out["locked"] = bool(d.get("locked", False))
    out["anim_in"] = _choice(d.get("anim_in"), IN_ANIMS, "none"); out["anim_out"] = _choice(d.get("anim_out"), OUT_ANIMS, "none")
    out["dur"] = _num(d.get("dur"), 0.1, 5.0, 0.6); out["hold"] = _num(d.get("hold"), 0.0, 3600.0, 0.0)
    if kind in ("text", "ticker"):
        out["size"] = _num(d.get("size"), 0.01, 0.5, out["size"])
        out["color"] = _color(d.get("color"), out["color"])
        out["align"] = _choice(d.get("align"), ALIGNS, "center"); out["font"] = str(d.get("font", ""))[:60]
    if kind in ("text", "ticker", "box"):
        bg = d.get("bg", out["bg"]) if "bg" in d else out["bg"]
        out["bg"] = "" if bg in ("", None) else _color(bg, out["bg"])
        out["bg_opacity"] = _num(d.get("bg_opacity"), 0.0, 1.0, out["bg_opacity"])
    if kind == "text":
        out["text"] = str(d.get("text", ""))[:2000]
    elif kind == "ticker":
        raw = d.get("items", []); raw = raw if isinstance(raw, (list, tuple)) else str(raw).splitlines()
        out["items"] = [str(i).strip()[:MAX_ITEM_LEN] for i in raw if str(i).strip()][:MAX_ITEMS]
        out["sep"] = str(d.get("sep", out["sep"]))[:12]
        out["mode"] = _choice(d.get("mode"), TICKER_MODES, "continuous"); out["dir"] = _choice(d.get("dir"), TICKER_DIRS, "rtl")
        out["speed"] = int(_num(d.get("speed"), 1, 10, 5)); out["seq_hold"] = _num(d.get("seq_hold"), 1.0, 120.0, 4.0)
        out["paused"] = bool(d.get("paused", False))
    return out

def normalize_scene(sc):
    """Copy of a scene whose 'layers' (if any) are cleaned; every V7 key is left untouched."""
    sc = copy.deepcopy(sc if isinstance(sc, dict) else {})
    if "layers" in sc:
        raw = sc["layers"] if isinstance(sc["layers"], list) else []
        seen, layers = set(), []
        for d in raw[:MAX_LAYERS]:
            if not isinstance(d, dict): continue
            l = normalize_layer(d)
            while l["id"] in seen: l["id"] = new_id()
            seen.add(l["id"]); layers.append(l)
        sc["layers"] = layers
    return sc

# ---------- layer list operations (bottom of the list = drawn first = back) ----------
def find(layers, lid):
    return next((l for l in layers if l.get("id") == lid), None)

def add_layer(layers, d):
    l = normalize_layer(d)
    while find(layers, l["id"]): l["id"] = new_id()
    if len(layers) < MAX_LAYERS: layers.append(l)
    return l

def remove_layer(layers, lid):
    l = find(layers, lid)
    if l and not l.get("locked"): layers.remove(l); return True
    return False

def duplicate_layer(layers, lid):
    l = find(layers, lid)
    if not l or len(layers) >= MAX_LAYERS: return None
    c = copy.deepcopy(l); c["id"] = new_id(); c["name"] = (l.get("name") or l["id"]) + " (نسخة)"; c["locked"] = False
    c["x"] = min(1.0, c["x"] + 0.03); c["y"] = max(-0.5, c["y"] - 0.03)
    layers.insert(layers.index(l) + 1, c); return c

def move_layer(layers, lid, delta):
    """delta>0 brings forward (towards the front), delta<0 sends back."""
    l = find(layers, lid)
    if not l: return False
    i = layers.index(l); j = max(0, min(len(layers) - 1, i + int(delta)))
    if i == j: return False
    layers.insert(j, layers.pop(i)); return True

def set_flag(layers, lid, flag, value):
    l = find(layers, lid)
    if l and flag in ("hidden", "locked", "paused"): l[flag] = bool(value); return True
    return False

# ---------- text helpers used by the renderer ----------
def ticker_text(layer):
    return layer["sep"].join(layer.get("items", []))

def ticker_item(layer, i):
    items = layer.get("items", [])
    return items[i % len(items)] if items else ""

def ticker_speed_px(speed, screen_w):
    """Pixels per second: speed 1..10 -> 3%..30% of the screen width per second."""
    return float(screen_w) * 0.03 * max(1, min(10, int(speed)))

def reveal_steps(text, kind):
    return len(text) if kind == "typewriter" else len(text.split())

def reveal(text, kind, n):
    if kind == "typewriter": return text[:max(0, n)]
    return " ".join(text.split()[:max(0, n)])

# ---------- ready-made templates ----------
def _L(**k): return k

def _news_tv(v):
    return {"bg": "#0B1F3A", "layers": [
        _L(id="head", kind="box", x=0, y=0.84, w=1, h=0.16, bg="#1565C0", bg_opacity=1, name="شريط العنوان"),
        _L(id="title", kind="text", x=0.04, y=0.85, w=0.92, h=0.14, text=v["title"], size=0.07, anim_in="slide_right", name="العنوان"),
        _L(id="main", kind="text", x=0.06, y=0.22, w=0.88, h=0.55, text=v["main"], size=0.075, anim_in="fade", hold=0, name="النص الرئيسي"),
        _L(id="band", kind="box", x=0, y=0.02, w=1, h=0.1, bg="#C62828", bg_opacity=1, name="خلفية الشريط"),
        _L(id="news", kind="ticker", x=0, y=0.02, w=1, h=0.1, items=v["ticker"], size=0.05, bg="", name="شريط الأخبار")]}

def _breaking(v):
    return {"bg": "#B71C1C", "layers": [
        _L(id="tag", kind="text", x=0.05, y=0.72, w=0.9, h=0.22, text=v["title"], size=0.14, anim_in="zoom_in", name="عاجل"),
        _L(id="main", kind="text", x=0.06, y=0.3, w=0.88, h=0.4, text=v["main"], size=0.08, anim_in="bounce", name="الخبر"),
        _L(id="band", kind="box", x=0, y=0.02, w=1, h=0.11, bg="#FDD835", bg_opacity=1, name="خلفية الشريط"),
        _L(id="news", kind="ticker", x=0, y=0.02, w=1, h=0.11, items=v["ticker"], size=0.055, color="#000000", bg="", name="شريط الأخبار")]}

def _ads(v):
    return {"bg": "#101010", "layers": [
        _L(id="title", kind="text", x=0.05, y=0.58, w=0.9, h=0.3, text=v["title"], size=0.11, color="#FDD835", anim_in="zoom_in", name="العنوان"),
        _L(id="main", kind="text", x=0.08, y=0.34, w=0.84, h=0.2, text=v["main"], size=0.06, anim_in="fade", name="الوصف"),
        _L(id="badge", kind="box", x=0.3, y=0.16, w=0.4, h=0.14, bg="#D32F2F", bg_opacity=1, name="شارة السعر"),
        _L(id="price", kind="text", x=0.3, y=0.16, w=0.4, h=0.14, text=v["sub"], size=0.08, anim_in="bounce", name="السعر"),
        _L(id="news", kind="ticker", x=0, y=0.02, w=1, h=0.08, mode="sequential", items=v["ticker"], size=0.045, bg="#1565C0", name="العروض")]}

def _conference(v):
    return {"bg": "#0D47A1", "layers": [
        _L(id="title", kind="text", x=0.05, y=0.6, w=0.9, h=0.28, text=v["title"], size=0.09, anim_in="fade", name="عنوان الجلسة"),
        _L(id="main", kind="text", x=0.05, y=0.42, w=0.9, h=0.15, text=v["main"], size=0.06, color="#BBDEFB", anim_in="slide_left", name="المتحدث"),
        _L(id="sub", kind="text", x=0.05, y=0.28, w=0.9, h=0.1, text=v["sub"], size=0.045, color="#FFFFFF", name="الوقت والقاعة"),
        _L(id="news", kind="ticker", x=0, y=0.02, w=1, h=0.08, mode="static", items=v["ticker"], size=0.04, bg="#08306B", name="الشريط")]}

def _event(v):
    return {"bg": "#4A148C", "layers": [
        _L(id="main", kind="text", x=0.05, y=0.45, w=0.9, h=0.4, text=v["main"], size=0.1, color="#FFD54F", anim_in="word", dur=2.0, name="التهنئة"),
        _L(id="title", kind="text", x=0.05, y=0.3, w=0.9, h=0.13, text=v["title"], size=0.06, anim_in="fade", name="العنوان الفرعي"),
        _L(id="sub", kind="text", x=0.05, y=0.16, w=0.9, h=0.1, text=v["sub"], size=0.045, color="#E1BEE7", name="التاريخ"),
        _L(id="news", kind="ticker", x=0, y=0.02, w=1, h=0.07, items=v["ticker"], size=0.04, bg="#311B92", name="الشريط")]}

def _info(v):
    return {"bg": "#263238", "layers": [
        _L(id="title", kind="text", x=0.05, y=0.78, w=0.9, h=0.16, text=v["title"], size=0.075, color="#80CBC4", anim_in="slide_right", name="العنوان"),
        _L(id="main", kind="text", x=0.06, y=0.25, w=0.88, h=0.5, text=v["main"], size=0.06, align="right", anim_in="typewriter", dur=3.0, name="المعلومة"),
        _L(id="news", kind="ticker", x=0, y=0.02, w=1, h=0.08, mode="sequential", items=v["ticker"], size=0.045, bg="#00695C", name="الشريط")]}

TEMPLATES = [
    {"id": "news_tv", "name": "الأخبار التلفزيونية", "build": _news_tv,
     "defaults": {"title": "نشرة الأخبار", "main": "اكتب الخبر الرئيسي هنا", "sub": "", "ticker": ["الخبر الأول", "الخبر الثاني", "الخبر الثالث"]}},
    {"id": "breaking", "name": "الأخبار العاجلة", "build": _breaking,
     "defaults": {"title": "عاجل", "main": "اكتب نص الخبر العاجل هنا", "sub": "", "ticker": ["تفاصيل إضافية قريباً"]}},
    {"id": "ads", "name": "الإعلانات التجارية", "build": _ads,
     "defaults": {"title": "عرض خاص", "main": "وصف المنتج أو العرض", "sub": "99 ريال", "ticker": ["خصم 30% لمدة محدودة", "توصيل مجاني"]}},
    {"id": "conference", "name": "المؤتمرات", "build": _conference,
     "defaults": {"title": "عنوان الجلسة", "main": "اسم المتحدث", "sub": "القاعة الرئيسية — 10:00 صباحاً", "ticker": ["مرحباً بكم في المؤتمر"]}},
    {"id": "event", "name": "المناسبات", "build": _event,
     "defaults": {"title": "بمناسبة عيد الفطر المبارك", "main": "كل عام وأنتم بخير", "sub": "1447 هـ", "ticker": ["نتمنى لكم أوقاتاً سعيدة"]}},
    {"id": "info", "name": "المعلومات العامة", "build": _info,
     "defaults": {"title": "هل تعلم؟", "main": "اكتب المعلومة هنا", "sub": "", "ticker": ["معلومة سريعة ١", "معلومة سريعة ٢"]}},
]

def template_ids(): return [t["id"] for t in TEMPLATES]

def build_template(tid, values=None):
    """Scene (already normalised) for template `tid`; `values` overrides title/main/sub/ticker."""
    t = next((t for t in TEMPLATES if t["id"] == tid), None)
    if t is None: raise KeyError(tid)
    v = copy.deepcopy(t["defaults"]); v.update({k: x for k, x in (values or {}).items() if x not in (None, "")})
    if isinstance(v["ticker"], str): v["ticker"] = [s for s in v["ticker"].splitlines() if s.strip()]
    sc = t["build"](v); sc["tpl"] = tid
    return normalize_scene(sc)

def valid_layer_command(d):
    """(id, action) for a well-formed {"id","action"} layer command, else None."""
    if not isinstance(d, dict): return None
    lid, act = str(d.get("id", ""))[:24], d.get("action")
    return (lid, act) if lid and act in LAYER_ACTIONS else None
