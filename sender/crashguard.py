"""Crash guard (Sender + Receiver).
1) Python errors inside Kivy callbacks are logged and the app KEEPS RUNNING (no silent exit).
2) Errors at import / startup are shown ON SCREEN (with the log path) instead of a blank screen.
Log file: <app user_data_dir>/crash.log  (also printed to logcat with the tag 'python')."""
import os, sys, threading, time, traceback

_state = {"path": None, "last": "", "t": 0.0, "n": 0}


def log_path():
    if _state["path"]:
        return _state["path"]
    for base in (os.environ.get("ANDROID_PRIVATE"), os.environ.get("ANDROID_ARGUMENT"), os.getcwd(), "/tmp"):
        if base and os.path.isdir(base):
            _state["path"] = os.path.join(base, "crash.log")
            return _state["path"]
    return None


def record(text):
    """Write an error once (identical repeats within 30 s are dropped to avoid log spam)."""
    now = time.time()
    if text == _state["last"] and now - _state["t"] < 30:
        return
    _state["last"], _state["t"] = text, now
    _state["n"] += 1
    try:
        print("CRASHGUARD:\n" + text)
    except Exception:
        pass
    p = log_path()
    if not p:
        return
    try:
        if os.path.exists(p) and os.path.getsize(p) > 200000:
            os.remove(p)
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n==== %s ====\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except Exception:
        pass


def install():
    """Keep the Kivy main loop alive when a callback raises."""
    try:
        from kivy.base import ExceptionHandler, ExceptionManager

        class Guard(ExceptionHandler):
            def handle_exception(self, inst):
                if isinstance(inst, (SystemExit, KeyboardInterrupt)):
                    return ExceptionManager.RAISE
                record("".join(traceback.format_exception(type(inst), inst, inst.__traceback__)))
                return ExceptionManager.PASS

        ExceptionManager.add_handler(Guard())
    except Exception as e:
        print("crashguard.install:", e)

    def _thread_hook(args):
        record("thread error:\n" + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
    try:
        threading.excepthook = _thread_hook
    except Exception:
        pass


def show_error(title, tb):
    """Open a tiny Kivy app that prints the error, so a startup failure is readable."""
    record(tb)
    try:
        from kivy.app import App
        from kivy.core.window import Window
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.scrollview import ScrollView

        class ErrorApp(App):
            def build(self):
                Window.clearcolor = (0.1, 0.0, 0.0, 1)
                root = BoxLayout(orientation="vertical", padding=12, spacing=8)
                root.add_widget(Label(text=title, size_hint_y=None, height=60, color=(1, .8, .2, 1), font_size="20sp"))
                sv = ScrollView()
                lab = Label(text=tb + "\n\nLog: %s" % log_path(), color=(1, 1, 1, 1), font_size="12sp",
                            size_hint_y=None, halign="left", valign="top")
                lab.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
                lab.bind(texture_size=lambda i, s: setattr(i, "height", s[1]))
                sv.add_widget(lab); root.add_widget(sv)
                return root
        ErrorApp().run()
    except Exception:
        traceback.print_exc()
