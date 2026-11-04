"""Receiver v3: pure white until Sender sends an explicit command. Approved content persists.
Understands: hello, apply_scene, apply_design, apply_playlist, store_project, play_project,
clear, hide, restore, reload, next, prev, emergency, emergency_off, ping.
Media arrives over Wi-Fi (mediaserver.py); BLE carries the commands."""
import json, os, threading, uuid
from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, PushMatrix, PopMatrix, Rotate
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.utils import get_color_from_hex as H
from protocol import Reassembler, encode, fragment, shape, to_bytes, dyn_text
import mediaserver
import studio as S
import secure_flow as SF
from devinfo import battery_from, status_line
from layers_view import LayersView
from library import LibraryIndex
from commands import parse as parse_command, help_text as command_help
from playback import scene_media, media_ended, clamp_volume

PORT = 8765

FONT = next((p for p in ("fonts/Amiri-Regular.ttf", "fonts/NotoNaskhArabic-Regular.ttf") if os.path.exists(p)), "fonts/NotoNaskhArabic-Regular.ttf")
F = {"font_name": FONT} if os.path.exists(FONT) else {}
BUNDLED = {n: p for n, p in (("Amiri", "fonts/Amiri-Regular.ttf"), ("Noto Naskh", "fonts/NotoNaskhArabic-Regular.ttf")) if os.path.exists(p)}
PERMS = ["android.permission.BLUETOOTH_CONNECT", "android.permission.BLUETOOTH_ADVERTISE",
         "android.permission.BLUETOOTH_SCAN", "android.permission.ACCESS_FINE_LOCATION",
         "android.permission.READ_MEDIA_IMAGES", "android.permission.READ_MEDIA_VIDEO",
         "android.permission.READ_MEDIA_AUDIO", "android.permission.READ_EXTERNAL_STORAGE"]

def lab(text, size, color, **kw):
    return Label(text=shape(text), font_size=size, color=H(color), **F, **kw)

def clamp_speed(v):
    try: return max(1, min(10, int(v)))
    except (TypeError, ValueError): return 5

def set_brightness(level):
    """level 0.0-1.0 sets the app window brightness; a negative value restores the system setting."""
    try:
        from android.runnable import run_on_ui_thread
        from jnius import autoclass
        @run_on_ui_thread
        def go():
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            lp = act.getWindow().getAttributes()
            lp.screenBrightness = float(level) if level >= 0 else -1.0
            act.getWindow().setAttributes(lp)
        go()
    except Exception as e:
        print("brightness:", e)

TRANSITIONS = ("none", "fade", "slide", "slide_up")

def keep_awake():
    try:
        from android.runnable import run_on_ui_thread
        from jnius import autoclass
        @run_on_ui_thread
        def go():
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            w = act.getWindow(); w.addFlags(128)
            w.getDecorView().setSystemUiVisibility(5894)
        go()
    except Exception as e:
        print("keep_awake:", e)

class Stage(FloatLayout):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        with self.canvas.before:
            self.c = Color(1, 1, 1, 1)
            self.r = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._u, size=self._u)
        self._evs = []; self._fx = []; self.lbl = None; self.lv = None

    def _u(self, *a): self.r.pos, self.r.size = self.pos, self.size

    def _sched(self, fn, dt, once=False, fx=False):
        ev = (Clock.schedule_once if once else Clock.schedule_interval)(fn, dt)
        (self._fx if fx else self._evs).append(ev); return ev

    def _clear_fx(self):
        for e in self._fx: e.cancel()
        self._fx = []
        if self.lbl: Animation.cancel_all(self.lbl); self.lbl.opacity = 1

    def stop(self):
        if self.lv: self.lv.stop()
        self._clear_fx()
        for e in self._evs: e.cancel()
        self._evs = []
        self.app.stop_media()

    def render(self, c, animate=True):
        self.stop(); self.clear_widgets(); self.lbl = None; self.lv = None
        Animation.cancel_all(self); self.opacity = 1; self.pos = (0, 0)
        if not c:
            self.c.rgba = (1, 1, 1, 1); return
        (self.scene if c["kind"] == "scene" else self.design)(c["d"])
        if animate: self.transition_in(self.app.settings.get("transition", "none"))

    def transition_in(self, mode):
        if mode == "fade":
            self.opacity = 0; Animation(opacity=1, duration=0.5).start(self)
        elif mode == "slide":
            self.x = self.width; Animation(x=0, duration=0.4, t="out_quad").start(self)
        elif mode == "slide_up":
            self.y = -self.height; Animation(y=0, duration=0.4, t="out_quad").start(self)

    # ---------- scene: background + image/video + audio + animated text ----------
    def scene(self, sc):
        self.c.rgba = H(sc.get("bg", "#FFFFFF"))
        t = sc.get("text") or {}
        msgs = [m for m in t.get("msgs", []) if str(m).strip()]
        v, a = sc.get("visual"), sc.get("audio")
        vpath = self.app.media_path(v) if v else None
        # Videos selected from the Receiver gallery are played from their original
        # content:// URI. Images are cached locally because Kivy Image needs a file path.
        video = bool(v) and v.get("kind") == "video" and (v.get("src") == "gallery" or bool(vpath))
        if vpath and v.get("kind") == "image":
            fit = v.get("fit") if v.get("fit") in ("contain", "cover", "fill", "scale-down") else "contain"
            self.add_widget(Image(source=vpath, fit_mode=fit, size_hint=(1, 1)))
        if video:
            self.app.play_video_media(v, bool(v.get("loop", True)), str(msgs[0]) if msgs else "",
                                      t.get("color", "#FFFFFF"), int(t.get("size", 48)))
        if a:
            self.app.play_audio_media(a, bool(a.get("loop", True)))
        if msgs and not video: self.text_layer(t, msgs)
        if sc.get("layers"):                       # V8: independent text / ticker / box layers on top
            self.lv = LayersView(font=FONT, fonts=BUNDLED)
            self.add_widget(self.lv)
            self.lv.set_layers(S.normalize_scene(sc)["layers"])

    def text_layer(self, t, msgs):
        mode = t.get("mode", "static"); speed = clamp_speed(t.get("speed", 5))
        size = str(t.get("size", 48)) + "sp"; color = t.get("color", "#000000")
        align = t.get("align", "center")
        if mode in ("ticker_h", "ticker_v"):
            txt = ("     ".join(map(str, msgs))) if mode == "ticker_h" else "\n\n".join(map(str, msgs))
            self._sched(lambda dt: self.ticker(txt, size, color, align, mode, t.get("tdir", "r2l"), speed), 0.2, once=True)
            return
        # Optional normalized placement sent by Sender's touch-drag preview.
        # Defaults preserve the original centered full-screen layout for old scenes.
        x = max(0.0, min(1.0, float(t.get("x", 0.0))))
        y = max(0.0, min(1.0, float(t.get("y", 0.0))))
        w = max(0.10, min(1.0 - x, float(t.get("w", 1.0))))
        h = max(0.10, min(1.0 - y, float(t.get("h", 1.0))))
        l = lab("", size, color, size_hint=(w, h), pos_hint={"x": x, "y": y},
                halign=align, valign="middle")
        l.bind(size=lambda i, v: setattr(i, "text_size", (v[0] * 0.92, v[1] * 0.92)))
        self.add_widget(l); self.lbl = l
        st = {"i": 0}
        def show(dt=0):
            self._clear_fx()
            self.effect(l, str(msgs[st["i"] % len(msgs)]), mode, speed)
        show()
        if len(msgs) > 1:
            hold = max(2, int(t.get("hold", 5) or 5))
            def nxt(dt): st["i"] += 1; show()
            self._sched(nxt, hold)

    def effect(self, l, txt, mode, speed):
        l.text = shape(txt)
        if mode == "blink":
            self._sched(lambda dt: setattr(l, "opacity", 0 if l.opacity > 0.5 else 1), 1.1 - speed * 0.1, fx=True)
        elif mode == "typewriter":
            st = {"n": 0}; l.text = ""
            def step(dt):
                st["n"] = min(st["n"] + 1, len(txt)); l.text = shape(txt[:st["n"]])
            self._sched(step, 0.6 / speed, fx=True)
        elif mode == "fade":
            l.opacity = 0; Animation(opacity=1.0, duration=3.0 / speed).start(l)
        elif mode == "fade_loop":
            d = 3.0 / speed
            a = Animation(opacity=0.0, duration=d) + Animation(opacity=1.0, duration=d); a.repeat = True; a.start(l)

    def ticker(self, txt, size, color, align, mode, tdir, speed):
        v = 40.0 * speed
        if mode == "ticker_h":
            l = lab(txt, size, color, size_hint=(None, None)); l.texture_update(); l.size = l.texture_size
            self.add_widget(l)
            left = tdir == "r2l"
            l.x = self.right if left else self.x - l.width
            def step(dt):
                l.center_y = self.center_y
                if left:
                    l.x -= v * dt
                    if l.right < self.x: l.x = self.right
                else:
                    l.x += v * dt
                    if l.x > self.right: l.x = self.x - l.width
            self._sched(step, 1 / 60.0)
        else:
            l = lab(txt, size, color, size_hint=(None, None), halign=align)
            l.text_size = (self.width * 0.92, None); l.texture_update(); l.size = l.texture_size
            self.add_widget(l); l.center_x = self.center_x; l.y = self.y - l.height
            def step(dt):
                l.center_x = self.center_x; l.y += v * dt
                if l.y > self.top: l.y = self.y - l.height
            self._sched(step, 1 / 60.0)

    # ---------- designed screen ----------
    def _el_label(self, e, frac, shadow=False):
        op = max(0.05, min(1.0, float(e.get("opacity", 1.0))))
        fg = list(H(e.get("fg", "#000000"))); fg[3] = op
        pos = {"x": e["x"], "y": e["y"]}
        if shadow:
            fg = [0, 0, 0, 0.55 * op]; pos = {"x": e["x"] + 0.004, "y": e["y"] - 0.004}
        kw = {}
        if not shadow and int(e.get("outline", 0) or 0) > 0:
            kw = {"outline_width": int(e["outline"]), "outline_color": list(H(e.get("outline_color", "#000000")))}
        l = Label(text=shape(e.get("text", "")), font_size=20, color=fg, **F, **kw,
                  size_hint=(e["w"], e["h"]), pos_hint=pos, halign="center", valign="middle")
        l.font_size = frac * max(self.height, 1)
        self.bind(height=lambda i, v, l=l, frac=frac: setattr(l, "font_size", frac * v))
        l.bind(size=lambda i, v: setattr(i, "text_size", v))
        with l.canvas.before:
            PushMatrix()
            rot = Rotate(angle=float(e.get("rotation", 0)), origin=l.center)
        l.bind(center=lambda i, v, rot=rot: setattr(rot, "origin", v))
        with l.canvas.after:
            PopMatrix()
        if e.get("bg") and not shadow:
            with l.canvas.before:
                bgc = list(H(e["bg"])); bgc[3] = max(0.05, min(1.0, float(e.get("bg_opacity", 1.0))))
                Color(*bgc); rr = Rectangle(pos=l.pos, size=l.size)
            l.bind(pos=lambda i, v, rr=rr: setattr(rr, "pos", v), size=lambda i, v, rr=rr: setattr(rr, "size", v))
        return l

    def design(self, d):
        self.c.rgba = H(d.get("bg", "#FFFFFF")); dyn = []
        for e in d.get("els", []):
            if e.get("hidden"):
                continue
            frac = float(e.get("size", 0.05))
            for shadow in ((True, False) if e.get("shadow") else (False,)):
                l = self._el_label(e, frac, shadow)
                if dyn_text(e) is not None: dyn.append((l, e))
                self.add_widget(l)
        def tick(dt):
            for l, e in dyn: l.text = shape(dyn_text(e))
        if dyn: tick(0); self._sched(tick, 1.0)

class ReceiverApp(App):
    def build(self):
        Window.clearcolor = (1, 1, 1, 1)
        self.stage = Stage(self)
        self.rdir = os.path.join(self.user_data_dir, "received"); os.makedirs(self.rdir, exist_ok=True)
        self.store = os.path.join(self.user_data_dir, "approved.json")
        self.pstore = os.path.join(self.user_data_dir, "projects.json")
        self.tfile = os.path.join(self.user_data_dir, "token.txt")
        self.library = LibraryIndex(os.path.join(self.user_data_dir, "library.sqlite3"))
        self.token = self._token()
        self.rid = self._rid()
        self.sec = SF.ReceiverSecurity(os.path.join(self.user_data_dir, "secure.json"), self.rid)
        self.overlay = None; self._pair_ev = None
        self.seen = set(); self.ra = Reassembler(); self.ble = None; self.mh = None; self.act = None
        self.base = None; self.projects = {}; self.hidden = False; self.emerg = None
        self.idx = 0; self._pl = None; self._em = None
        self.sfile = os.path.join(self.user_data_dir, "settings.json")
        try:
            with open(self.sfile, encoding="utf-8") as f: self.settings = json.load(f)
        except Exception: self.settings = {}
        try:
            with open(self.store, encoding="utf-8") as f:
                data = json.load(f)
            self.base = data.get("content"); self.seen = set(data.get("seen", []))
        except Exception: pass
        try:
            with open(self.pstore, encoding="utf-8") as f: self.projects = json.load(f)
        except Exception: pass
        Clock.schedule_once(lambda dt: self.refresh(), 0.6)
        return self.stage

    def _rid(self):
        f = os.path.join(self.user_data_dir, "rid.txt")
        try:
            with open(f) as fh:
                v = fh.read().strip()
                if v: return v
        except Exception: pass
        v = uuid.uuid4().hex[:8]
        try:
            with open(f, "w") as fh: fh.write(v)
        except Exception: pass
        return v

    def _token(self):
        try:
            with open(self.tfile) as f: return f.read().strip() or self._new_token()
        except Exception: return self._new_token()
    def _new_token(self):
        t = uuid.uuid4().hex[:10]
        try:
            with open(self.tfile, "w") as f: f.write(t)
        except Exception: pass
        return t

    # ---------- lifecycle ----------
    def on_start(self):
        keep_awake()
        if self.settings.get("brightness") is not None: set_brightness(self.settings["brightness"])
        try:
            from jnius import autoclass
            self.act = autoclass("org.kivy.android.PythonActivity").mActivity
            self.mh = autoclass("org.bleremote.MediaHelper")
        except Exception as e: print("jnius:", e)
        try:
            mediaserver.start(PORT, self.token, self.rdir,
                              lambda: str(self.mh.listMedia(self.act)),
                              lambda uri: (lambda b: bytes((x & 0xFF) for x in b) if b else None)(self.mh.thumb(self.act, uri, 256)))
        except Exception as e: print("http server:", e)
        try:
            from android.permissions import request_permissions
            request_permissions(PERMS, lambda p, g: Clock.schedule_once(self.start_ble, 0))
        except Exception: self.start_ble()

    def on_pause(self): return True
    def on_resume(self):
        keep_awake()
        if self.settings.get("brightness") is not None: set_brightness(self.settings["brightness"])

    def save_settings(self):
        try:
            with open(self.sfile, "w", encoding="utf-8") as f: json.dump(self.settings, f)
        except Exception as e: print("settings:", e)

    def start_ble(self, *a):
        if self.ble: return
        try:
            from jnius import autoclass
            self.ble = autoclass("org.bleremote.BleServer")(self.act)
            self.ble.start()
            Clock.schedule_interval(self.poll, 0.05)
            # Permissions have been requested before this callback; index on a worker thread.
            threading.Thread(target=self.refresh_library_index, daemon=True).start()
        except Exception as e: print("BLE start failed:", e)

    # ---------- media helpers ----------
    def media_path(self, m):
        if not m: return None
        p = os.path.join(self.rdir, os.path.basename(str(m.get("name", ""))))
        return p if os.path.isfile(p) else None
    def play_video_media(self, media, loop, text, color, size):
        if not self.mh: return
        try:
            c = 0xFF000000 | int(color.lstrip("#")[:6], 16)
            if c > 0x7FFFFFFF: c -= 1 << 32
            sp = int(max(14, size * 0.6))
            if media.get("src") == "gallery" and media.get("uri"):
                self.mh.playVideoUri(self.act, media["uri"], loop, text, c, sp)
            else:
                path = self.media_path(media)
                if path: self.mh.playVideo(self.act, path, loop, text, c, sp)
        except Exception as e: print("video:", e)
    def play_audio_media(self, media, loop):
        if not self.mh: return
        try:
            if media.get("src") == "gallery" and media.get("uri"):
                ok = self.mh.playAudioUri(self.act, media["uri"], loop)
                if not ok:
                    # Fallback for providers that do not support direct MediaPlayer access.
                    name = str(self.mh.copyUri(self.act, media["uri"], self.rdir))
                    if name: self.mh.playAudio(os.path.join(self.rdir, name), loop)
            else:
                path = self.media_path(media)
                if path: self.mh.playAudio(path, loop)
        except Exception as e: print("audio:", e)
    def stop_media(self):
        if self.mh:
            try: self.mh.stopAudio(); self.mh.stopVideo(self.act)
            except Exception: pass

    def prepare(self, content, done):
        """Use Receiver gallery URIs directly for audio/video; cache images for Kivy."""
        d = content["d"]
        scenes = [d] if content["kind"] == "scene" else (d.get("scenes", []) if content["kind"] == "playlist" else [])
        # Keep receiver-gallery audio/video as content URIs: no media upload and
        # no duplicate copy. Cache only images because Kivy's Image widget expects
        # a filesystem path rather than a content:// URI.
        need = [m for s in scenes for k in ("visual", "audio") for m in [s.get(k)]
                if m and m.get("src") == "gallery" and m.get("kind") == "image"]
        if not need or not self.mh: return done(content)
        def run():
            cache = {}
            for m in need:
                u = m.get("uri", "")
                if u not in cache: cache[u] = str(self.mh.copyUri(self.act, u, self.rdir))
                if cache[u]:
                    m["src"] = "upload"; m["name"] = cache[u]
            Clock.schedule_once(lambda dt: done(content), 0)
        threading.Thread(target=run, daemon=True).start()

    # ---------- state ----------
    def current(self):
        if self.emerg: return self.emerg
        if self.hidden: return None
        b = self.base
        if b and b["kind"] == "playlist":
            sc = b["d"].get("scenes", [])
            return {"kind": "scene", "d": sc[self.idx % len(sc)]} if sc else None
        return b

    def refresh(self):
        self.stage.render(self.current())
        self.schedule_next()

    def schedule_next(self):
        if self._pl: self._pl.cancel(); self._pl = None
        b = self.base
        if not (b and b["kind"] == "playlist" and not self.emerg and not self.hidden): return
        scenes = b["d"].get("scenes", [])
        if len(scenes) < 2: return
        if scene_media(scenes[self.idx % len(scenes)]):
            self._pl = Clock.schedule_interval(self.check_media_end, 1.0)     # advance when the clip finishes
        else:
            self._pl = Clock.schedule_once(self.advance, max(2, int(b["d"].get("secs", 10) or 10)))

    def check_media_end(self, dt):
        try: st = json.loads(str(self.mh.status(self.act)))
        except Exception: return
        if media_ended(st): self.advance(0)

    def advance(self, dt):
        self.idx += 1; self.stage.render(self.current()); self.schedule_next()

    def set_base(self, c):
        self.base = c; self.idx = 0; self.hidden = False; self.emerg = None
        self.save(); self.refresh()

    def save(self):
        tmp = self.store + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"content": self.base, "seen": list(self.seen)[-50:]}, f, ensure_ascii=False)
        os.replace(tmp, self.store)

    def save_projects(self):
        with open(self.pstore, "w", encoding="utf-8") as f: json.dump(self.projects, f, ensure_ascii=False)

    # ---------- persistent media library + typed commands ----------
    def refresh_library_index(self):
        try:
            if not self.mh or not self.act: return 0
            raw = str(self.mh.listMedia(self.act))
            items = json.loads(raw or "[]")
            return self.library.refresh(items)
        except Exception as e:
            print("library index:", e)
            return 0

    def run_text_command(self, text):
        cmd = parse_command(text)
        action = cmd.get("action")
        if action == "help": return True, command_help()
        if action == "hide": self.hidden = True; self.refresh(); return True, "تم إخفاء العرض"
        if action == "restore": self.hidden = False; self.refresh(); return True, "تمت استعادة العرض"
        if action == "stop_audio":
            if self.mh:
                try: self.mh.stopAudio()
                except Exception: pass
            return True, "تم إيقاف الصوت"
        if action == "stop_media": self.stop_media(); return True, "تم إيقاف الوسائط"
        if action == "refresh":
            n = self.refresh_library_index()
            return True, "تم تحديث فهرس المكتبة: %d ملف" % n
        if action == "stats":
            st = self.library.stats()
            return True, "المكتبة: %d ملف | صور: %d | فيديو: %d | صوت: %d" % (st['total'], st['image'], st['video'], st['audio'])
        if action == "alias":
            ok = self.library.set_alias(cmd.get('query', ''), cmd.get('alias', ''))
            return ok, ("تم حفظ الاسم البديل" if ok else "لم أجد ملفاً بهذا الاسم")
        rows = self.library.search(cmd.get('query', ''), cmd.get('kind'), newest=bool(cmd.get('newest')), limit=30)
        if action == "search":
            if not rows: return False, "لم يتم العثور على ملفات مطابقة"
            return True, "النتائج: " + "، ".join((r.get('alias') or r['name']) for r in rows[:8])
        if action == "play":
            if not rows: return False, "لم أجد الملف المطلوب. جرّب: تحديث المكتبة"
            item = rows[0]
            media = {"kind": item['kind'], "src": "gallery", "uri": item['uri'],
                     "name": item['name'], "loop": True}
            scene = {"bg": "#000000"}
            if item['kind'] == 'audio': scene['audio'] = media
            else: scene['visual'] = media
            self.prepare({"kind": "scene", "d": scene}, lambda c: self.set_base(c))
            return True, "جاري تشغيل: %s" % (item.get('alias') or item['name'])
        return False, command_help()

    # ---------- BLE ----------
    def ack(self, mid, ok=True, extra=None, secure=False):
        env = self.sec.ack_envelope(mid, {"ok": ok, **(extra or {})}, secure)
        for p in fragment(env, self.ble.chunkSize()):
            self.ble.notifyData(p)

    # ---------- V9: pairing screen + status ----------
    def show_pair(self, sas):
        from kivy.uix.button import Button
        self.hide_pair()
        ov = FloatLayout()
        with ov.canvas.before:
            Color(0, 0, 0, 0.93); r = Rectangle(pos=ov.pos, size=ov.size)
        ov.bind(pos=lambda i, v: setattr(r, "pos", v), size=lambda i, v: setattr(r, "size", v))
        ov.add_widget(lab("رمز الاقتران", "28sp", "#FFFFFF", size_hint=(1, .12), pos_hint={"x": 0, "y": .78}))
        ov.add_widget(lab(sas, "64sp", "#FFD54F", size_hint=(1, .22), pos_hint={"x": 0, "y": .5}))
        ov.add_widget(lab("قارن الرمز مع شاشة المرسل، وإن تطابقا اضغط قبول", "18sp", "#FFFFFF", size_hint=(1, .12), pos_hint={"x": 0, "y": .36}))
        for txt, col, hx, fn in (("قبول", (0, .6, .5, 1), .05, self.pair_accept), ("رفض", (.7, .1, .1, 1), .55, self.pair_decline)):
            b = Button(text=shape(txt), size_hint=(.4, .14), pos_hint={"x": hx, "y": .12}, background_normal="", background_color=col, **F)
            b.bind(on_release=lambda *_, fn=fn: fn()); ov.add_widget(b)
        Window.add_widget(ov); self.overlay = ov
        self._pair_ev = Clock.schedule_once(lambda dt: self.pair_decline(), SF.X.PAIR_WINDOW)

    def hide_pair(self):
        if self._pair_ev: self._pair_ev.cancel(); self._pair_ev = None
        if self.overlay is not None:
            try: Window.remove_widget(self.overlay)
            except Exception: pass
            self.overlay = None

    def pair_accept(self):
        if self.sec.accept():
            Clock.schedule_once(lambda dt: self.hide_pair(), 1.0)       # the sender will now confirm and finish

    def pair_decline(self): self.sec.decline(); self.hide_pair()

    def handle_pair(self, kind, mid, d):
        if kind == "pair_begin":
            ok, body, sas = self.sec.begin(d)
            if ok: self.show_pair(sas)
            return self.ack(mid, ok, body)
        st, body = self.sec.confirm(d)
        if st == "ok":
            self.hide_pair()
            return self.ack(mid, True, {"result": "تم الاقتران", "ip": self._ip(), "port": PORT, "token": self.token, "rid": self.rid}, secure=True)
        if st != "pending": self.hide_pair()
        self.ack(mid, False, body)

    def _ip(self):
        try: return str(self.mh.localIp())
        except Exception: return ""

    def battery(self):
        try:
            from jnius import autoclass
            i = self.act.registerReceiver(None, autoclass("android.content.IntentFilter")(autoclass("android.content.Intent").ACTION_BATTERY_CHANGED))
            return battery_from(i.getIntExtra("level", -1), i.getIntExtra("scale", 100), i.getIntExtra("status", -1))
        except Exception: return {"level": -1, "charging": False}

    def status_text(self):
        import shutil
        try: free = shutil.disk_usage(self.rdir).free
        except Exception: free = 0
        ble = ""
        try: ble = str(self.ble.getState())
        except Exception: pass
        return status_line({"battery": self.battery(), "free": free, "paired": self.sec.paired, "ble": ble})

    def poll(self, dt):
        for _ in range(20):
            raw = self.ble.poll()
            if raw is None: return
            msg = self.ra.feed(to_bytes(raw))
            if msg: self.handle(msg)

    def handle(self, m):
        kind, pl = self.sec.route(m)                     # V9: encryption / pairing gate (open mode = unchanged)
        if kind == "drop": return
        if kind == "plain": return self.ack(m["id"], pl.get("ok", False), {k: v for k, v in pl.items() if k not in ("id", "ok")})
        if kind in ("pair_begin", "pair_confirm"): return self.handle_pair(kind, *pl)
        m, secure = pl
        mid, t, d = m["id"], m["t"], m.get("d", {})
        if not isinstance(d, dict):
            self.ack(mid, False, {"result": "بنية الأمر غير صالحة"}, secure=secure); return
        if mid in self.seen: self.ack(mid, secure=secure); return
        def finish(ok=True, extra=None):
            if ok and t != "hello": self.seen.add(mid)
            self.ack(mid, ok, extra, secure=secure)
        if t == "hello":
            return finish(True, {"ip": self._ip(), "port": PORT, "token": self.token, "rid": self.rid, "paired": self.sec.paired})
        if t == "status":
            return finish(True, {"result": self.status_text()})
        if t == "unpair":
            if not secure: return finish(False, {"result": "يتطلب اتصالاً مشفراً"})
            finish(True, {"result": "تم إلغاء الاقتران"}); self.sec.unpair(); return
        if t == "command":
            ok, result = self.run_text_command(str(d.get("text", "")))
            return finish(ok, {"result": result})
        if t in ("apply_scene", "apply_design", "apply_playlist"):
            kind = {"apply_scene": "scene", "apply_design": "design", "apply_playlist": "playlist"}[t]
            return self.prepare({"kind": kind, "d": d}, lambda c: (self.set_base(c), finish()))
        if t == "store_project":
            def stored(c):
                self.projects[str(d.get("id"))] = {"name": d.get("name", ""), "scenes": c["d"].get("scenes", []),
                                                   "secs": d.get("secs", 10)}
                self.save_projects(); finish()
            return self.prepare({"kind": "playlist", "d": d}, stored)
        if t == "play_project":
            p = self.projects.get(str(d.get("id")))
            if not p: return finish(False)
            self.set_base({"kind": "playlist", "d": {"scenes": p["scenes"], "secs": p["secs"], "loop": True}})
            return finish()
        if t == "media":
            act = str(d.get("action", ""))
            if act not in ("toggle", "pause", "resume", "seek", "volume", "status") or not self.mh:
                return finish(False, {"result": "أمر تشغيل غير معروف"})
            try:
                if act == "status": st = str(self.mh.status(self.act))
                elif act == "volume":
                    v = clamp_volume(d.get("value"))
                    if v is None: return finish(False, {"result": "قيمة الصوت غير صالحة"})
                    st = str(self.mh.control(self.act, act, v))
                else: st = str(self.mh.control(self.act, act, int(d.get("value", 0) or 0)))
            except Exception as e: return finish(False, {"result": str(e)})
            return finish(True, {"media": st})
        if t == "layer":
            cmd = S.valid_layer_command(d)
            lv = getattr(self.stage, "lv", None)
            ok = bool(cmd and lv and lv.control(*cmd))
            return finish(ok, {"result": "تم" if ok else "الطبقة غير موجودة أو الإجراء غير معروف"})
        if t == "brightness":
            try: lv = float(d.get("level", -1))
            except (TypeError, ValueError): return finish(False, {"result": "قيمة غير صالحة"})
            lv = -1.0 if lv < 0 else max(0.02, min(1.0, lv))
            self.settings["brightness"] = lv; self.save_settings(); set_brightness(lv)
            return finish(True, {"result": "السطوع: " + ("تلقائي" if lv < 0 else "%d%%" % round(lv * 100))})
        if t == "transition":
            mode = str(d.get("mode", "none"))
            if mode not in TRANSITIONS: return finish(False, {"result": "انتقال غير معروف"})
            self.settings["transition"] = mode; self.save_settings()
            return finish(True, {"result": "الانتقال: " + mode})
        if t == "clear": self.base = None; self.hidden = False; self.emerg = None; self.save(); self.refresh()
        elif t == "hide": self.hidden = True; self.refresh()
        elif t == "restore": self.hidden = False; self.emerg = None; self.refresh()
        elif t == "reload": self.refresh()
        elif t in ("next", "prev"):
            self.idx += 1 if t == "next" else -1; self.stage.render(self.current()); self.schedule_next()
        elif t == "emergency":
            self.emerg = {"kind": "scene", "d": {"bg": d.get("bg", "#B71C1C"), "text": {
                "msgs": [d.get("text", "")], "color": d.get("color", "#FFFFFF"), "size": d.get("size", 64),
                "mode": "blink", "speed": 5}}}
            self.refresh()
            if self._em: self._em.cancel(); self._em = None
            try: secs = int(d.get("seconds", 0) or 0)
            except (TypeError, ValueError): secs = 0
            if secs > 0: self._em = Clock.schedule_once(lambda dt: self.end_emergency(), secs)
        elif t == "emergency_off": self.end_emergency()
        elif t != "ping": return finish(False)
        finish()

    def end_emergency(self): self.emerg = None; self.refresh()

ReceiverApp().run()
