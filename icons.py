"""Custom icons (icons/*.png): the red / blue upgrade hearts.

Blender's built-in heart (FUND) has one colour; the editions need two: red for Basic / Pro,
blue for Fabricator. kw("heart_blue") gives the keyword arguments for layout.operator /
label: icon_value=<id> when the image loaded, else the built-in heart, so a missing file
never breaks a panel.
"""

import os

import bpy

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
_pcoll = None
FALLBACK = {"heart_red": 'FUND', "heart_blue": 'FUND'}


def _load():
    global _pcoll
    if _pcoll is not None:
        return _pcoll
    try:
        import bpy.utils.previews
        pc = bpy.utils.previews.new()
        for f in os.listdir(_DIR) if os.path.isdir(_DIR) else ():
            if f.endswith(".png"):
                pc.load(f[:-4], os.path.join(_DIR, f), 'IMAGE')
        _pcoll = pc
    except Exception:
        _pcoll = {}
    return _pcoll


def kw(name):
    pc = _load()
    try:
        if name in pc and pc[name].icon_id:        # 0 = not loaded (e.g. background mode)
            return {"icon_value": pc[name].icon_id}
    except Exception:
        pass
    return {"icon": FALLBACK.get(name, 'NONE')}


def register():
    _load()


def unregister():
    global _pcoll
    if _pcoll:
        try:
            bpy.utils.previews.remove(_pcoll)
        except Exception:
            pass
    _pcoll = None
