"""Update check (every edition except the extensions.blender.org build, which the platform
updates). Reads one small JSON file from the public GitHub repo when the user presses
Check, or once at start-up if the user allowed it. Never runs when Blender's "Allow Online
Access" is off (bpy.app.online_access).

latest.json (repo root):  {"version": "4.3.0", "notes": "one line of what is new"}
"""

import time

import bpy

from . import tier
from . import support
from .support import note, version_string

# where the latest version is published (the public Orivot Free repository)
UPDATE_URL = "https://raw.githubusercontent.com/damagedarchitect/Orivot/main/latest.json"
RELEASES_URL = "https://github.com/damagedarchitect/Orivot/releases"
CONTACT_URL = "https://discord.com/users/damagedarchitect"

_update = {"state": "idle", "latest": None, "notes": "", "error": "", "checked": 0.0}

# ──────────────────────────────────────────────────────────────────────────────

def _vtuple(s):
    out = []
    for part in str(s).strip().lstrip("v").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out + [0] * (3 - len(out)))


def parse_latest(data, current):
    """data: the parsed latest.json. -> (newer: bool, version: str, notes: str)"""
    ver = str(data.get("version", "0"))
    notes = str(data.get("notes", ""))[:400]
    return _vtuple(ver) > _vtuple(current), ver, notes


def _fetch(timeout=5.0):
    import json
    import urllib.request
    req = urllib.request.Request(UPDATE_URL, headers={"User-Agent": f"Orivot/{version_string()}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read(65536).decode("utf-8"))


def online_allowed():
    return bool(getattr(bpy.app, "online_access", True))


def check_now():
    """Blocking check (short timeout). Fills _update; returns it."""
    if not online_allowed():
        _update.update(state="offline", error="Online access is off (Preferences › System)")
        return _update
    try:
        data = _fetch()
        newer, ver, notes = parse_latest(data, version_string())
        _update.update(state="newer" if newer else "current", latest=ver, notes=notes,
                       error="", checked=time.time())
    except Exception as e:
        if getattr(e, "code", None) != 404:          # nothing published yet is not a bug
            note(e, "update check")
        _update.update(state="error", error=f"{type(e).__name__}: {e}"[:160], checked=time.time())
    return _update


def _startup_check():
    """Timer: one background check at start-up, only if the user opted in."""
    p = support._prefs()
    if p is None or not getattr(p, "check_updates_on_startup", False) or not online_allowed():
        return None
    import threading
    threading.Thread(target=check_now, daemon=True).start()
    return None


class ORIVOT_OT_check_update(bpy.types.Operator):
    """Look for a newer Orivot version (reads one small file from GitHub). Needs Blender's
    Allow Online Access (Preferences › System › Network)"""
    bl_idname = "orivot.check_update"
    bl_label = "Check for Updates"
    bl_options = {'REGISTER'}

    def execute(self, context):
        u = check_now()
        if u["state"] == "offline":
            self.report({'WARNING'}, "Allow Online Access first: Preferences › System › Network")
            return {'CANCELLED'}
        if u["state"] == "error":
            self.report({'WARNING'}, f"Update check failed: {u['error']}")
            return {'CANCELLED'}
        if u["state"] == "newer":
            self.report({'INFO'}, f"Orivot {u['latest']} is available (you have {version_string()})")
        else:
            self.report({'INFO'}, f"Orivot {version_string()} is the latest version")
        return {'FINISHED'}


class ORIVOT_OT_get_update(bpy.types.Operator):
    """Free: open the GitHub releases page. Paid editions: open Discord to ask for the new
    build (sent to every buyer)"""
    bl_idname = "orivot.get_update"
    bl_label = "Get the Update"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        bpy.ops.wm.url_open(url=(RELEASES_URL))
        return {'FINISHED'}



def draw_button(row, layout):
    row.operator("orivot.check_update", text="Update", icon='FILE_REFRESH')
    if _update["state"] == "newer":
        r = layout.row(align=True)
        r.alert = True
        r.operator("orivot.get_update", text=f"Orivot {_update['latest']} available", icon='IMPORT')


def draw_prefs(prefs, col):
    col.prop(prefs, "check_updates_on_startup")
    if not online_allowed():
        col.label(text="Online access is off in Blender's preferences", icon='INFO')


CLASSES = (ORIVOT_OT_check_update, ORIVOT_OT_get_update)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    tier._ops.update(c.bl_idname for c in CLASSES)
    if not bpy.app.timers.is_registered(_startup_check):
        bpy.app.timers.register(_startup_check, first_interval=3.0)


def unregister():
    if bpy.app.timers.is_registered(_startup_check):
        bpy.app.timers.unregister(_startup_check)
    for c in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(c)
        except Exception as _exc:
            note(_exc)
