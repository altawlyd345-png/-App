"""Pure helpers (no Kivy) for playlist advancing on the Receiver."""

def scene_media(scene):
    """Video/audio entries of a scene that play once (loop False)."""
    return [m for m in (scene.get("visual"), scene.get("audio"))
            if m and m.get("kind") in ("video", "audio") and not m.get("loop", True)]

def media_ended(st):
    """True when the active video/audio has played to its end (status dict from MediaHelper.status)."""
    if not isinstance(st, dict) or st.get("kind") not in ("video", "audio"): return False
    dur, pos = int(st.get("dur") or 0), int(st.get("pos") or 0)
    return dur > 0 and not st.get("playing") and pos >= dur - 800

def clamp_volume(v):
    try: return max(0, min(100, int(v)))
    except (TypeError, ValueError): return None
