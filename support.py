"""Support: error log and "Report a Problem" (every edition). Update check: updater.py.

Error log
    Orivot has many `except Exception:` blocks that keep a draw handler or a timer alive
    when one object is odd (deleted mid-draw, linked data, a modifier stack that fails to
    evaluate). Since 4.3 each of them calls note(): the error is kept in a small in-memory
    ring (the last 60 distinct ones) and, if the preferences ask for it, printed to the
    console and appended to a log file. Behaviour is unchanged: the block still swallows
    the error exactly as before.

Report a Problem
    Copies Blender / add-on / OS versions, the edition, the scene's unit settings and the
    recent errors to the clipboard, ready to paste in a Discord message.

The update check lives in updater.py so the extensions.blender.org build (which gets
updates from the platform) can ship without it.
"""

import os
import sys
import time
import traceback

import bpy

from . import tier

_RING_MAX = 60
_ring = []                 # [(time, where, "Type: message", short traceback)]
_seen = {}                 # (file, line, type) -> count


# ──────────────────────────────────────────────────────────────────────────────
# error log
# ──────────────────────────────────────────────────────────────────────────────

def _prefs():
    try:
        return bpy.context.preferences.addons[__package__].preferences
    except Exception:
        return None


def log_path():
    """<Blender user config>/orivot_log.txt (the folder holding userpref.blend)."""
    try:
        base = bpy.utils.user_resource('CONFIG')
    except Exception:
        base = os.path.expanduser("~")
    return os.path.join(base, "orivot_log.txt")


def note(exc=None, where=""):
    """Record an exception that a broad `except` swallowed. Never raises."""
    try:
        if exc is None:
            exc = sys.exc_info()[1]
        if exc is None:
            return
        tb = exc.__traceback__
        t = tb
        while t is not None and t.tb_next is not None:
            t = t.tb_next
        key = ((t.tb_frame.f_code.co_filename, t.tb_lineno) if t is not None else (where, 0),
               type(exc).__name__)
        n = _seen.get(key, 0) + 1
        _seen[key] = n
        if n > 1:                       # the same failure again (e.g. every redraw): cheap exit
            return
        frames = traceback.extract_tb(tb) if tb is not None else []
        last = frames[-1] if frames else None
        loc = f"{os.path.basename(last.filename)}:{last.lineno} in {last.name}" if last else where
        msg = f"{type(exc).__name__}: {exc}"
        short = " <- ".join(f"{os.path.basename(f.filename)}:{f.lineno}" for f in reversed(frames[-4:]))
        _ring.append((time.time(), loc, msg[:300], short))
        del _ring[:-_RING_MAX]
        p = _prefs()
        if p is not None and getattr(p, "log_verbose", False):
            print(f"[{tier.NAME}] swallowed {msg} at {loc}")
        if p is not None and getattr(p, "log_to_file", False):
            with open(log_path(), "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {tier.NAME}  {loc}  {msg}\n"
                         f"    {short}\n")
    except Exception:
        pass


def recent(n=30):
    return list(_ring[-n:])


def clear():
    _ring.clear()
    _seen.clear()


def version_string():
    """The add-on version: blender_manifest.toml (extensions: Blender drops bl_info from the
    module), else bl_info."""
    import os
    import re
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_manifest.toml")
        with open(path, encoding="utf-8") as fh:
            m = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"', fh.read())
        if m:
            return m.group(1)
    except OSError:
        pass
    try:
        mod = sys.modules[__package__]
        return ".".join(str(x) for x in mod.bl_info["version"])
    except Exception:
        return "?"


def report_text(context):
    import platform
    sc = context.scene
    us = sc.unit_settings
    lines = [
        f"Orivot problem report — {tier.NAME} {version_string()}",
        f"Blender {bpy.app.version_string} ({bpy.app.build_hash.decode() if isinstance(bpy.app.build_hash, bytes) else bpy.app.build_hash})",
        f"OS {platform.system()} {platform.release()} · Python {platform.python_version()}",
        f"GPU backend {getattr(bpy.context.preferences.system, 'gpu_backend', '?')}",
        f"Mode {context.mode} · selected {len(context.selected_objects)} · "
        f"active {getattr(context.active_object, 'type', None)}",
        f"Units {us.system} / {us.length_unit} · scale {us.scale_length:g}",
        "",
        "Recent swallowed errors (newest last):",
    ]
    errs = recent()
    if not errs:
        lines.append("  none")
    for t, loc, msg, short in errs:
        lines.append(f"  {time.strftime('%H:%M:%S', time.localtime(t))}  {loc}  {msg}")
        lines.append(f"      {short}")
    lines += ["", "What I did / what I expected:", "  "]
    return "\n".join(lines)


class ORIVOT_OT_report_problem(bpy.types.Operator):
    """Copy a short problem report (versions, edition, units and the most recent caught
    errors) to the clipboard, ready to paste into a Discord message"""
    bl_idname = "orivot.report_problem"
    bl_label = "Report a Problem"
    bl_options = {'REGISTER'}

    def execute(self, context):
        text = report_text(context)
        context.window_manager.clipboard = text
        n = len(recent())
        self.report({'INFO'}, f"Problem report copied ({n} recent error(s)). Paste it in a "
                              f"message with a screenshot")
        return {'FINISHED'}


class ORIVOT_OT_open_log(bpy.types.Operator):
    """Open the Orivot log file (only written when 'Write Log File' is on in the add-on
    preferences)"""
    bl_idname = "orivot.open_log"
    bl_label = "Open Log File"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return os.path.exists(log_path())

    def execute(self, context):
        bpy.ops.wm.path_open(filepath=log_path())
        return {'FINISHED'}


def _updater():
    try:
        from . import updater
        return updater
    except ImportError:
        return None


def draw_settings_rows(layout):
    """The Settings panel row: Report a Problem + Check for Updates (and its result)."""
    row = layout.row(align=True)
    row.operator("orivot.report_problem", text="Report", icon='ERROR')
    up = _updater()
    if up is not None:
        up.draw_button(row, layout)


def draw_prefs(prefs, layout):
    box = layout.box()
    box.label(text="Support", icon='HELP')
    col = box.column(align=True)
    col.prop(prefs, "log_verbose")
    row = col.row(align=True)
    row.prop(prefs, "log_to_file")
    row.operator("orivot.open_log", text="", icon='FILEBROWSER')
    up = _updater()
    if up is not None:
        up.draw_prefs(prefs, col)


CLASSES = (ORIVOT_OT_report_problem, ORIVOT_OT_open_log)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    tier._ops.update(c.bl_idname for c in CLASSES)
    up = _updater()
    if up is not None:
        up.register()


def unregister():
    up = _updater()
    if up is not None:
        up.unregister()
    for c in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(c)
        except Exception:
            pass
