"""Viewport bounding-box handles: the click modal, its timers and undo hook.

Split out of op_tools.py in 4.3.0 (tools/split_ops.py)."""

import bpy
from mathutils import Vector
import gpu
from bpy.app.handlers import persistent
from bpy_extras.view3d_utils import location_3d_to_region_2d
from . import state
from . import common
from . import preview


_handle_mode = {"running": False, "stop": False}


# The one-shot handle tool (pie menu) draws its own handles. Only the CURRENT one may draw:
# if its modal dies without _finish (file load, window closed, add-on reload), the leftover
# draw callback sees it is no longer the owner and stays silent instead of drawing forever.
_handle_oneshot = {"owner": None, "handler": None}


def _drop_oneshot_handle_draw():
    """Remove a one-shot handle overlay whose tool ended without cleaning up."""
    h = _handle_oneshot["handler"]
    _handle_oneshot["owner"] = _handle_oneshot["handler"] = None
    if h is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(h, 'WINDOW')
        except Exception as _exc:
            support.note(_exc)


def _start_handle_mode():
    """Timer: start the persistent handle-snap modal in a real 3D Viewport region.
    (Operators must not be called from a property update callback.)"""
    try:
        ctx = bpy.context
        if not getattr(ctx.scene, 'orivot_show_viewport_handles', False) or _handle_mode["running"]:
            return None
        preview.ensure_handle_draw()                 # file load / add-on enable with Handles saved on
        for win in ctx.window_manager.windows:
            for area in win.screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                if region is None:
                    continue
                with ctx.temp_override(window=win, area=area, region=region):
                    if bpy.ops.orivot.click_bbox_handle.poll():
                        bpy.ops.orivot.click_bbox_handle('INVOKE_DEFAULT', persistent=True)
                    else:
                        # no active mesh yet: try again shortly (Handles stays on)
                        return 0.5
                return None
    except Exception as e:
        support.note(e)
        print(f"[Orivot] could not start handle snapping: {e}")
    return None


@persistent
def _handles_after_undo(scene, *_):
    """Ctrl+Z / Ctrl+Shift+Z can switch Handles back on without running its click tool
    (up to 4.2.3 they were then drawn but did nothing): restart it when that happens."""
    try:
        sc = bpy.context.scene
        if getattr(sc, 'orivot_show_viewport_handles', False) and not _handle_mode["running"]:
            _handle_mode["stop"] = False
            preview.ensure_handle_draw()
            if not bpy.app.timers.is_registered(_start_handle_mode):
                bpy.app.timers.register(_start_handle_mode, first_interval=0.0)
    except Exception as _exc:
        support.note(_exc)


def _handles_toggle_update(self, context):
    """Handles ON  -> snapping is live immediately (no extra button).
    Handles OFF -> the running modal sees the flag and ends on its next event."""
    if self.orivot_show_viewport_handles:
        _handle_mode["stop"] = False
        preview.ensure_handle_draw()                 # visible even with Preview off
        if not bpy.app.timers.is_registered(_start_handle_mode):
            bpy.app.timers.register(_start_handle_mode, first_interval=0.0)
    preview._tag_view3d_redraw()


from . import support
