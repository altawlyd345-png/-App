"""Minimal fake Kivy so layers_view.py logic can be exercised without a device."""
import sys, types

class _Ctx:
    def __enter__(self): return self
    def __exit__(self, *a): return False

class Canvas:
    before = _Ctx(); after = _Ctx()
    def __init__(self): self.before = _Ctx(); self.after = _Ctx()

class Clock:
    jobs = []
    @classmethod
    def schedule_once(cls, fn, dt=0): j = {"fn": fn, "dt": dt, "once": True, "dead": False, "t": 0.0}; cls.jobs.append(j); return _Job(j)
    @classmethod
    def schedule_interval(cls, fn, dt): j = {"fn": fn, "dt": dt, "once": False, "dead": False, "t": 0.0}; cls.jobs.append(j); return _Job(j)
    @classmethod
    def tick(cls, seconds, step=None):
        """Advance fake time; every job fires when its own clock reaches dt."""
        step = step or 1 / 60.0; t = 0.0
        while t < seconds - 1e-9:
            t += step
            for j in list(cls.jobs):
                if j["dead"]: continue
                j["t"] += step
                if j["t"] + 1e-9 >= j["dt"]:
                    j["t"] = 0.0
                    r = j["fn"](step)
                    if j["once"] or r is False: j["dead"] = True
    @classmethod
    def reset(cls): cls.jobs = []

class _Job:
    def __init__(self, j): self.j = j
    def cancel(self): self.j["dead"] = True

class Animation:
    def __init__(self, **kw): self.kw = {k: v for k, v in kw.items() if k not in ("duration", "t")}; self.cb = []
    def bind(self, **kw): self.cb += list(kw.values())
    def start(self, w):
        for k, v in self.kw.items(): setattr(w, k, v)
        for c in self.cb: c(self, w)
    @classmethod
    def cancel_all(cls, w, *a): pass

class NumericProperty:
    def __init__(self, v=0): self.v = v
    def __set_name__(self, o, n): self.n = "_p_" + n
    def __get__(self, o, t=None): return self if o is None else getattr(o, self.n, self.v)
    def __set__(self, o, v):
        setattr(o, self.n, v)

class Widget:
    opacity = 1.0
    def __init__(self, **kw):
        self.children = []; self.canvas = Canvas(); self.x = 0.0; self.y = 0.0; self.width = 100.0; self.height = 100.0
        self.size_hint = kw.pop("size_hint", (1, 1)); self.pos_hint = kw.pop("pos_hint", {})
        self.text = kw.pop("text", ""); self.font_size = kw.pop("font_size", 14); self.color = kw.pop("color", None)
        for k, v in kw.items(): setattr(self, k, v)
        self.opacity = 1.0
    @property
    def pos(self): return (self.x, self.y)
    @pos.setter
    def pos(self, v): self.x, self.y = v
    @property
    def size(self): return (self.width, self.height)
    @size.setter
    def size(self, v): self.width, self.height = v
    @property
    def right(self): return self.x + self.width
    @right.setter
    def right(self, v): self.x = v - self.width
    @property
    def center_y(self): return self.y + self.height / 2
    @center_y.setter
    def center_y(self, v): self.y = v - self.height / 2
    @property
    def center(self): return (self.x + self.width / 2, self.y + self.height / 2)
    def bind(self, **kw): pass
    def unbind(self, **kw): pass
    def setter(self, name): return lambda i, v: setattr(self, name, v)
    def add_widget(self, w): self.children.append(w)
    def clear_widgets(self): self.children = []

class _Inst:
    def __init__(self, *a, **kw): self.a = a; self.__dict__.update(kw)

def install():
    def mod(name, **attrs):
        m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m; return m
    mod("kivy"); mod("kivy.uix")
    mod("kivy.animation", Animation=Animation); mod("kivy.clock", Clock=Clock)
    mod("kivy.graphics", Color=_Inst, Rectangle=_Inst, PushMatrix=_Inst, PopMatrix=_Inst, Translate=_Inst, Rotate=_Inst, Scale=_Inst)
    mod("kivy.properties", NumericProperty=NumericProperty)
    mod("kivy.uix.floatlayout", FloatLayout=Widget); mod("kivy.uix.label", Label=Widget); mod("kivy.uix.stencilview", StencilView=Widget)
    def h(s): s = s.lstrip("#"); return [int(s[i:i + 2], 16) / 255 for i in (0, 2, 4)] + [1.0]
    mod("kivy.utils", get_color_from_hex=h)
