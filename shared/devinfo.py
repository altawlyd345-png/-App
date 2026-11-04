"""Receiver status helpers (pure Python)."""

def battery_from(level, scale, status):
    """-> {"level": 0-100 or -1, "charging": bool} from Android BatteryManager extras."""
    try:
        level, scale = int(level), int(scale)
    except (TypeError, ValueError):
        return {"level": -1, "charging": False}
    pct = round(100 * level / scale) if level >= 0 and scale > 0 else -1
    return {"level": max(-1, min(100, pct)), "charging": status in (2, 5)}      # CHARGING, FULL

def human_bytes(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return "%d %s" % (n, u) if u == "B" else "%.1f %s" % (n, u)
        n /= 1024

def status_line(info):
    b = info.get("battery", {}); lvl = b.get("level", -1)
    parts = ["البطارية: " + ("غير معروفة" if lvl < 0 else "%d%%%s" % (lvl, " (تشحن)" if b.get("charging") else ""))]
    if info.get("free"): parts.append("المساحة المتاحة: " + human_bytes(info["free"]))
    parts.append("الاتصال: " + ("مقترن ومشفّر ✔" if info.get("paired") else "غير مقترن (مفتوح)"))
    if info.get("ble"): parts.append("البلوتوث: " + str(info["ble"]))
    return "  |  ".join(parts)
