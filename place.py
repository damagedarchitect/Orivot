"""Snap history, pivot library, collision-preview helpers, Surface Align, HUD overlays, World Zero, shortcuts info.

Split out of __init__.py in 4.3 (tools/split_init.py)."""

import sys
import bpy
from mathutils import Vector, Matrix
import gpu
from gpu_extras.batch import batch_for_shader
import math
from bpy.app.handlers import persistent
from bpy_extras.view3d_utils import (
    region_2d_to_vector_3d,
    region_2d_to_origin_3d,
    location_3d_to_region_2d,
)

from . import core
from . import gpudraw
from . import tier
try:
    from . import linesnap
except ImportError:
    linesnap = None
try:
    from . import axistransform
except ImportError:
    axistransform = None
try:
    from . import chain
except ImportError:
    chain = None
try:
    from . import collision
except ImportError:
    collision = None
try:
    from . import scenesnap
except ImportError:
    scenesnap = None
try:
    from . import curvepath
except ImportError:
    curvepath = None
try:
    from . import panelscroll
except ImportError:
    panelscroll = None
try:
    from . import fab
except ImportError:
    fab = None
try:
    from . import orient
except ImportError:
    orient = None
from . import common
from . import preview
from . import op_objsnap
from . import support


def _pkg():
    return sys.modules[__package__]


def push_snap_history(obj_name: str, world_pos: Vector) -> None:
    """Record a snap position. Called automatically by _apply_origin() and confirm_snap.
    Suppressed during history navigation and batch operations via _SNAP_RECORDING[0]."""
    if not common._SNAP_RECORDING[0]:
        return
    entry = (obj_name, world_pos.copy())
    if common._SNAP_HISTORY and common._SNAP_HISTORY[-1] == entry:
        return
    common._SNAP_HISTORY.append(entry)
    if len(common._SNAP_HISTORY) > common._SNAP_HISTORY_MAX:
        common._SNAP_HISTORY.pop(0)
    common._SNAP_HISTORY_IDX[0] = len(common._SNAP_HISTORY) - 1


def clear_snap_history() -> None:
    common._SNAP_HISTORY.clear()
    common._SNAP_HISTORY_IDX[0] = 0


def _draw_history_hud():
    """POST_PIXEL: show a small history-position banner for ~2 s after Prev/Next."""
    import time
    try:
        if not common._history_hud_text[0]:
            return
        elapsed = time.monotonic() - common._history_hud_time[0]
        if elapsed > 2.5:
            common._history_hud_text[0] = None
            preview._tag_view3d_redraw()   # force viewport to repaint so text clears immediately
            return
        alpha = max(0.0, 1.0 - (elapsed - 1.5))   # fade last second
        import blf
        ctx    = bpy.context
        region = getattr(ctx, 'region', None)
        if not region:
            return
        blf.size(0, 18)
        blf.color(0, 0.95, 0.72, 0.18, alpha)
        blf.position(0, 18, region.height - 46, 0)
        blf.draw(0, common._history_hud_text[0])
    except Exception as _exc:
        support.note(_exc)


def _draw_mode_indicator():
    """POST_PIXEL: small corner overlay showing current snap mode & orientation."""
    try:
        ctx   = bpy.context
        scene = ctx.scene
        if not getattr(scene, 'orivot_show_mode_indicator', False):
            return
        region = getattr(ctx, 'region', None)
        if not region:
            return
        src   = getattr(scene, 'orivot_snap_source',         'MESH')
        ori   = getattr(scene, 'orivot_preview_orientation', 'LOCAL')
        lx    = getattr(scene, 'orivot_lock_x', False)
        ly    = getattr(scene, 'orivot_lock_y', False)
        lz    = getattr(scene, 'orivot_lock_z', False)
        locks = ''.join([('X' if lx else ''), ('Y' if ly else ''), ('Z' if lz else '')])
        lock_str = f"  Lock:{locks}" if locks else ""
        import blf
        blf.size(0, 13)
        blf.color(0, 0.85, 0.85, 0.85, 0.65)
        blf.position(0, 12, 12 + 32, 0)
        blf.draw(0, f"Orivot  Source:{src}  Orient:{ori}{lock_str}")
    except Exception as _exc:
        support.note(_exc)


class ORIVOT_OT_show_shortcuts_info(bpy.types.Operator):
    """Orivot keyboard shortcuts:

Alt + Q                    →  Orivot pie menu
Alt + Click                →  Quick surface snap
Alt + Shift + Click        →  Quick vertex snap
Alt + Ctrl + Click         →  Quick face-centre snap

While Surface Snap is active:
  Shift                    →  Face centre (Red)
  Ctrl                     →  Grid snap (Orange)
  Alt                      →  Normal offset (Green)
  X / Y / Z               →  Lock to world axis
  Type digits + Enter      →  Exact normal offset distance
  Backspace                →  Clear typed digits

Edit Mode  ·  Line Snap (one vertex selected):
Alt + Shift + G            →  Snap vertex ON the active stored line
Alt + Shift + H            →  Snap vertex PARALLEL to the active stored line
Alt + Shift + L            →  Pick the active line by clicking it
Alt + Shift + I            →  Quick intersect (same object, Shift-click order)

Edit Mode  ·  Axis Transform (selected geometry):
Alt + Shift + R            →  Rotate about the axis
Alt + Shift + S            →  Shear along the axis

While Axis Transform is running:
  X / Y / Z                →  Global axis (press again: local)
  L  /  Tab (Shift+Tab)    →  Active stored line  /  next (previous) line
  Ctrl + X / Y / Z         →  Shear reference direction      V  →  Auto
  P                        →  Cycle pivot
  Type digits              →  Exact angle       Ctrl  →  Snap
  R / S                    →  Switch rotate / shear
  Enter / Click            →  Confirm            Esc  →  Cancel

While Line Snap is running:
  1 / 2 / 3                →  ON / PARALLEL / POINTS
  Tab (Shift+Tab)          →  Next (previous) active line
  A                        →  Show / hide the working-area markers
  Enter / Click            →  Confirm            Esc  →  Cancel"""
    bl_idname  = "orivot.show_shortcuts_info"
    bl_label   = "Keyboard Shortcuts"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        return {'FINISHED'}


# The tooltip lists only the shortcuts this edition has.
_doc = ORIVOT_OT_show_shortcuts_info.__doc__
_doc = _doc[:_doc.index("\n\nEdit Mode  \u00b7  Line Snap")]
_doc = _doc[:_doc.index("\nAlt + Click")]
ORIVOT_OT_show_shortcuts_info.bl_description = _doc
del _doc


class ORIVOT_OT_snap_to_world_zero(bpy.types.Operator):
    """Move this object's origin to (0, 0, 0) — the scene / world centre."""
    bl_idname  = "orivot.snap_to_world_zero"
    bl_label   = "Origin to World Zero"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.active_object and
                context.active_object.type in common.GEOMETRY_TYPES and
                not context.active_object.library)

    def execute(self, context):
        obj = context.active_object
        common._record_history(obj)
        common._apply_origin(obj, Vector((0.0, 0.0, 0.0)), context)
        self.report({'INFO'}, f"✓ Origin → World Zero (0,0,0)  [{obj.name}]")
        preview._tag_view3d_redraw()
        return {'FINISHED'}


