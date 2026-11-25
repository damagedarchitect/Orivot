"""Object menu entries (Set Origin submenus) and auto-show timer.

Split out of __init__.py in 4.3 (tools/split_init.py)."""

import sys
import bpy
from mathutils import Vector, Matrix
from gpu_extras.batch import batch_for_shader
from bpy.app.handlers import persistent
from bpy_extras.view3d_utils import (
    region_2d_to_vector_3d,
    region_2d_to_origin_3d,
    location_3d_to_region_2d,
)

from . import tier
from . import state
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
from . import support


def _pkg():
    return sys.modules[__package__]


# ---------------- Menus ----------------
def auto_show_preview_timer():
    """One-shot timer behind 'Auto-show on hover': turn the preview on for the active
    object when a Set Origin submenu opens. (Referenced since 3.x but never defined —
    opening the submenu with the option on raised NameError.)"""
    state._auto_show_timer = None
    try:
        scene = bpy.context.scene
        obj = bpy.context.active_object
        if obj is None or obj.type not in common.GEOMETRY_TYPES:
            return None
        if not scene.orivot_show_preview:
            scene.orivot_show_preview = True       # update callback builds the preview
        else:
            preview.create_or_update_preview(obj)
        preview._tag_view3d_redraw()
    except Exception as e:
        support.note(e)
        print(f"[Orivot] auto-show preview failed: {e}")
    return None


def menu_draw_handler(self, context):
    """Auto-show preview when hovering submenu (if enabled)"""
    return
    


def _snap_items(layout, scene, modes):
    """One menu entry per snap mode, labelled with the sides and the axes they are on for
    the current Front Face Axis (4.3.5: Blender's front is -Y). None = separator."""
    from . import common
    for mode in modes:
        if mode is None:
            layout.separator()
            continue
        words = " ".join(s.title() for s in common.mode_sides(mode))
        layout.operator("orivot.set_origin_extreme_full",
                        text=f"{words} ({common.mode_axis_text(mode, scene)})").mode = mode


_SIDES6 = ('TOP', 'BOTTOM', 'LEFT', 'RIGHT', 'FRONT', 'BACK')


class VIEW3D_MT_set_origin_faces(bpy.types.Menu):
    bl_label = "Faces (Geometry)"

    def draw(self, context):
        menu_draw_handler(self, context)
        _snap_items(self.layout, context.scene, [f"FACE_{s}" for s in _SIDES6])


class VIEW3D_MT_set_origin_vertices(bpy.types.Menu):
    bl_label = "Vertices (Corners)"

    def draw(self, context):
        menu_draw_handler(self, context)
        _snap_items(self.layout, context.scene,
                    ['VERT_TLF', 'VERT_TRF', 'VERT_TLB', 'VERT_TRB', None,
                     'VERT_BLF', 'VERT_BRF', 'VERT_BLB', 'VERT_BRB'])


class VIEW3D_MT_set_origin_edges(bpy.types.Menu):
    bl_label = "Edge Midpoints (12)"

    def draw(self, context):
        from . import common
        menu_draw_handler(self, context)
        layout = self.layout
        scene = context.scene
        ax = common.side_labels(scene)
        layout.label(text=f"Top ring ({ax['TOP']})")
        _snap_items(layout, scene, ['EDGE_TOP_LEFT', 'EDGE_TOP_RIGHT', 'EDGE_TOP_FRONT', 'EDGE_TOP_BACK'])
        layout.separator()
        layout.label(text=f"Bottom ring ({ax['BOTTOM']})")
        _snap_items(layout, scene, ['EDGE_BOT_LEFT', 'EDGE_BOT_RIGHT', 'EDGE_BOT_FRONT', 'EDGE_BOT_BACK'])
        layout.separator()
        layout.label(text="Middle edges")
        _snap_items(layout, scene, ['EDGE_FRONT_LEFT', 'EDGE_FRONT_RIGHT', 'EDGE_BACK_LEFT', 'EDGE_BACK_RIGHT'])


class VIEW3D_MT_set_origin_centers(bpy.types.Menu):
    bl_label = "Centers (Face Centers)"

    def draw(self, context):
        menu_draw_handler(self, context)
        _snap_items(self.layout, context.scene, [f"CENTER_{s}" for s in _SIDES6])


class VIEW3D_MT_set_origin_main(bpy.types.Menu):
    bl_label = "Set Origin to..."

    def draw(self, context):
        menu_draw_handler(self, context)
        layout = self.layout

        # Snap to 3D Cursor — keeps workflow inside Orivot without a Blender menu detour
        layout.operator("orivot.set_origin_extreme_full",
                        text="Snap to 3D Cursor", icon='CURSOR').mode = 'CURSOR'
        layout.separator()

        layout.menu("VIEW3D_MT_set_origin_faces")
        layout.menu("VIEW3D_MT_set_origin_vertices")
        layout.menu("VIEW3D_MT_set_origin_edges")
        layout.menu("VIEW3D_MT_set_origin_centers")


