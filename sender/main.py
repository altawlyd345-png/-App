"""Launcher: catches startup errors and shows them instead of a blank white screen."""
import traceback
import crashguard
crashguard.install()
try:
    import sender_app          # runs the app on import
except Exception:
    crashguard.show_error("Sender - خطأ عند التشغيل", traceback.format_exc())
