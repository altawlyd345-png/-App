"""V8 layer renderer (Kivy). One implementation for the Receiver screen and the Sender live preview.
Layers come from studio.normalize_scene(); text, ticker (3 modes) and box layers are independent:
each has its own timers, so pausing/hiding one never touches another."""
from kivy.animation import Animation
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, PushMatrix, PopMatrix, Translate, Rotate, Scale
from kivy.properties import NumericProperty
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.stencilview import StencilView
from kivy.utils import get_color_from_hex as H
import studio as S
from protocol import shape


class AnimBox(FloatLayout):
    """Container whose transform (translate px, scale, static rotation) can be animated."""
    tx = NumericProperty(0)
    ty = NumericProperty(0)
    sc = NumericProperty(1)

    def __init__(self, rotation=0.0, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            PushMatrix()
            self._tr = Translate(0, 0)
            self._rt = Rotate(angle=float(rotation), axis=(0, 0, 1), origin=(0, 0))
            self._sc = Scale(1, 1, 1, origin=(0, 0))
        with self.canvas.after:
            PopMatrix()
        self.bind(tx=self._u, ty=self._u, sc=self._u, pos=self._u, size=self._u)

    def _u(self, *a):
        c = self.center
        self._tr.xy = (self.tx, self.ty)
        self._rt.origin = c
        self._sc.origin = c
        self._sc.xyz = (self.sc, self.sc, 1)

    def set_bg(self, hex_color, alpha):
        rgb = list(H(hex_color))[:3]
        with self.canvas.before:
            Color(rgb[0], rgb[1], rgb[2], max(0.0, min(1.0, alpha)))
            r = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=lambda i, v: setattr(r, "pos", v), size=lambda i, v: setattr(r, "size", v))


class RT:
    """Runtime state of one layer."""
    def __init__(self, view, d):
        self.view, self.d = view, d
        self.box = None
        self.lbl = None
        self.st = None
        self.evs = []
        self.paused = bool(d.get("paused"))
        self.hidden = bool(d.get("hidden"))
        self.started = False
        self.seq_i = 0

    def sched(self, fn, dt, once=False):
        ev = (Clock.schedule_once if once else Clock.schedule_interval)(fn, dt)
        self.evs.append(ev)
        return ev

    def stop(self):
        for e in self.evs:
            e.cancel()
        self.evs = []
        if self.box is not None:
            Animation.cancel_all(self.box)
        if self.lbl is not None:
            Animation.cancel_all(self.lbl)

    @property
    def idle(self):
        return self.paused or self.hidden


class LayersView(FloatLayout):
    def __init__(self, font="", fonts=None, **kw):
        super().__init__(**kw)
        self.font = font
        self.fonts = fonts or {}
        self.rt = {}
        self._binds = []

    # ---------- lifecycle ----------
    def stop(self):
        for rt in self.rt.values():
            rt.stop()

    def set_layers(self, layers):
        self.stop()
        for fn in self._binds:
            self.unbind(height=fn)
        self._binds = []
        self.clear_widgets()
        self.rt = {}
        for d in layers:
            d = S.normalize_layer(d)
            rt = RT(self, d)
            self.rt[d["id"]] = rt
            self._build(rt)

    def control(self, lid, action):
        rt = self.rt.get(lid)
        if rt is None or action not in S.LAYER_ACTIONS:
            return False
        if action == "pause":
            rt.paused = True
        elif action == "resume":
            rt.paused = False
        elif action == "hide":
            rt.hidden = True
            rt.box.opacity = 0
        elif action == "show":
            rt.hidden = False
            self.play_in(rt)
        elif action == "restart":
            rt.hidden = False
            rt.paused = False
            rt.started = False
            self.play_in(rt)
        return True

    def status(self):
        return {k: {"paused": r.paused, "hidden": r.hidden} for k, r in self.rt.items()}

    # ---------- building ----------
    def _font(self, d):
        path = self.fonts.get(d.get("font")) or self.font
        return {"font_name": path} if path else {}

    def _fit_font(self, lbl, frac):
        fn = lambda i, v: setattr(lbl, "font_size", max(6.0, frac * v))
        self.bind(height=fn)
        self._binds.append(fn)
        lbl.font_size = max(6.0, frac * max(self.height, 1))

    def _build(self, rt):
        d = rt.d
        box = AnimBox(rotation=d["rotation"], size_hint=(d["w"], d["h"]), pos_hint={"x": d["x"], "y": d["y"]})
        rt.box = box
        if d["kind"] == "box" or d.get("bg"):
            box.set_bg(d.get("bg") or "#000000", d["bg_opacity"])
        if d["kind"] == "text":
            self._text(rt)
        elif d["kind"] == "ticker":
            self._ticker(rt)
        box.opacity = 0 if (rt.hidden or d["anim_in"] != "none") else d["opacity"]
        self.add_widget(box)
        if not rt.hidden:
            rt.sched(lambda dt: self.play_in(rt), 0.15, once=True)

    def _text(self, rt):
        d = rt.d
        full = d["text"]
        lbl = Label(text=shape(full), color=H(d["color"]), halign=d["align"], valign="middle",
                    size_hint=(1, 1), **self._font(d))
        lbl.bind(size=lambda i, v: setattr(i, "text_size", (v[0] * 0.96, v[1])))
        self._fit_font(lbl, d["size"])
        rt.lbl = lbl
        rt.box.add_widget(lbl)

    def _ticker(self, rt):
        d = rt.d
        st = StencilView(size_hint=(1, 1))
        rt.st = st
        rt.box.add_widget(st)
        items = d["items"] or [""]
        common = dict(color=H(d["color"]), **self._font(d))
        if d["mode"] == "continuous":
            lbl = Label(text=shape(S.ticker_text(d) or " "), size_hint=(None, None), halign="center",
                        valign="middle", **common)
            lbl.bind(texture_size=lbl.setter("size"))
            self._fit_font(lbl, d["size"])
            st.add_widget(lbl)
            rt.lbl = lbl
            rt.sched(lambda dt: self._scroll(rt, dt), 1 / 60.0)
        else:
            text = shape(S.ticker_item(d, 0)) if d["mode"] == "sequential" else shape(S.ticker_text(d) or " ")
            lbl = Label(text=text, halign=d["align"], valign="middle", size_hint=(1, 1), **common)
            lbl.bind(size=lambda i, v: setattr(i, "text_size", (v[0] * 0.96, v[1])))
            self._fit_font(lbl, d["size"])
            st.add_widget(lbl)
            rt.lbl = lbl
            if d["mode"] == "sequential" and len(items) > 1:
                rt.sched(lambda dt: self._next_item(rt), d["seq_hold"])

    # ---------- ticker motion ----------
    def _scroll(self, rt, dt):
        if rt.idle or rt.lbl is None:
            return
        d, st, lbl = rt.d, rt.st, rt.lbl
        lbl.center_y = st.center_y
        left = d["dir"] == "rtl"
        if not rt.started:
            lbl.x = st.right if left else st.x - lbl.width
            rt.started = True
            return
        v = S.ticker_speed_px(d["speed"], max(self.width, 1)) * dt
        if left:
            lbl.x -= v
            if lbl.right < st.x:
                lbl.x = st.right
        else:
            lbl.x += v
            if lbl.x > st.right:
                lbl.x = st.x - lbl.width

    def _next_item(self, rt):
        if rt.idle:
            return
        rt.seq_i += 1
        rt.lbl.text = shape(S.ticker_item(rt.d, rt.seq_i))
        rt.lbl.opacity = 0
        Animation(opacity=1, duration=0.35).start(rt.lbl)

    # ---------- entrance / exit animations ----------
    def play_in(self, rt):
        if rt.hidden:                      # hidden after the entrance was scheduled -> stay hidden
            return
        d, b = rt.d, rt.box
        a, dur, op = d["anim_in"], d["dur"], d["opacity"]
        W, Hh = max(self.width, 1), max(self.height, 1)
        Animation.cancel_all(b)
        b.tx = b.ty = 0
        b.sc = 1
        b.opacity = op
        if a == "fade":
            b.opacity = 0
            Animation(opacity=op, duration=dur).start(b)
        elif a == "slide_right":
            b.tx = -W
            Animation(tx=0, duration=dur, t="out_quad").start(b)
        elif a == "slide_left":
            b.tx = W
            Animation(tx=0, duration=dur, t="out_quad").start(b)
        elif a == "zoom_in":
            b.sc, b.opacity = 0.1, 0
            Animation(sc=1, opacity=op, duration=dur, t="out_back").start(b)
        elif a == "zoom_out":
            b.sc, b.opacity = 2.5, 0
            Animation(sc=1, opacity=op, duration=dur, t="out_quad").start(b)
        elif a == "bounce":
            b.ty = Hh * 0.6
            Animation(ty=0, duration=dur, t="out_bounce").start(b)
        elif a in ("typewriter", "word") and d["kind"] == "text":
            self._reveal(rt, a)
        if d["hold"] > 0 and d["anim_out"] != "none":
            rt.sched(lambda dt: self.play_out(rt), d["hold"] + dur, once=True)

    def _reveal(self, rt, kind):
        full = rt.d["text"]
        steps = S.reveal_steps(full, kind)
        if steps <= 0:
            return
        rt.lbl.text = ""
        n = {"i": 0}
        interval = max(0.03, rt.d["dur"] / steps)

        def step(dt):
            if rt.hidden:
                return None
            if rt.paused:
                return None
            n["i"] += 1
            rt.lbl.text = shape(S.reveal(full, kind, n["i"]))
            return False if n["i"] >= steps else None
        rt.sched(step, interval)

    def play_out(self, rt):
        d, b = rt.d, rt.box
        a, dur = d["anim_out"], d["dur"]
        W = max(self.width, 1)
        if a == "fade":
            anim = Animation(opacity=0, duration=dur)
        elif a == "slide_left":
            anim = Animation(tx=-W, duration=dur, t="in_quad")
        elif a == "slide_right":
            anim = Animation(tx=W, duration=dur, t="in_quad")
        elif a == "zoom_out":
            anim = Animation(sc=0.05, opacity=0, duration=dur)
        else:
            return
        anim.bind(on_complete=lambda *_: setattr(b, "opacity", 0))
        anim.start(b)
