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
    


class VIEW3D_MT_set_origin_faces(bpy.types.Menu):
    bl_label = "Faces (Geometry)"

    def draw(self, context):
        menu_draw_handler(self, context)
        layout = self.layout
        scene = context.scene

        layout.operator("orivot.set_origin_extreme_full", text="Top (+Z)").mode = 'FACE_TOP'
        layout.operator("orivot.set_origin_extreme_full", text="Bottom (-Z)").mode = 'FACE_BOTTOM'

        if scene.orivot_flip_left_right:
            layout.operator("orivot.set_origin_extreme_full", text="Left (+X)").mode = 'FACE_LEFT'
            layout.operator("orivot.set_origin_extreme_full", text="Right (-X)").mode = 'FACE_RIGHT'
        else:
            layout.operator("orivot.set_origin_extreme_full", text="Left (-X)").mode = 'FACE_LEFT'
            layout.operator("orivot.set_origin_extreme_full", text="Right (+X)").mode = 'FACE_RIGHT'

        layout.operator("orivot.set_origin_extreme_full", text="Front (+Y)").mode = 'FACE_FRONT'
        layout.operator("orivot.set_origin_extreme_full", text="Back (-Y)").mode = 'FACE_BACK'


class VIEW3D_MT_set_origin_vertices(bpy.types.Menu):
    bl_label = "Vertices (Corners)"

    def draw(self, context):
        menu_draw_handler(self, context)
        layout = self.layout
        scene = context.scene

        if scene.orivot_flip_left_right:
            layout.operator("orivot.set_origin_extreme_full", text="Top Left Front (+X+Y+Z)").mode = 'VERT_TLF'
            layout.operator("orivot.set_origin_extreme_full", text="Top Right Front (-X+Y+Z)").mode = 'VERT_TRF'
            layout.operator("orivot.set_origin_extreme_full", text="Top Left Back (+X-Y+Z)").mode = 'VERT_TLB'
            layout.operator("orivot.set_origin_extreme_full", text="Top Right Back (-X-Y+Z)").mode = 'VERT_TRB'
            layout.separator()
            layout.operator("orivot.set_origin_extreme_full", text="Bottom Left Front (+X+Y-Z)").mode = 'VERT_BLF'
            layout.operator("orivot.set_origin_extreme_full", text="Bottom Right Front (-X+Y-Z)").mode = 'VERT_BRF'
            layout.operator("orivot.set_origin_extreme_full", text="Bottom Left Back (+X-Y-Z)").mode = 'VERT_BLB'
            layout.operator("orivot.set_origin_extreme_full", text="Bottom Right Back (-X-Y-Z)").mode = 'VERT_BRB'
        else:
            layout.operator("orivot.set_origin_extreme_full", text="Top Left Front (-X+Y+Z)").mode = 'VERT_TLF'
            layout.operator("orivot.set_origin_extreme_full", text="Top Right Front (+X+Y+Z)").mode = 'VERT_TRF'
            layout.operator("orivot.set_origin_extreme_full", text="Top Left Back (-X-Y+Z)").mode = 'VERT_TLB'
            layout.operator("orivot.set_origin_extreme_full", text="Top Right Back (+X-Y+Z)").mode = 'VERT_TRB'
            layout.separator()
            layout.operator("orivot.set_origin_extreme_full", text="Bottom Left Front (-X+Y-Z)").mode = 'VERT_BLF'
            layout.operator("orivot.set_origin_extreme_full", text="Bottom Right Front (+X+Y-Z)").mode = 'VERT_BRF'
            layout.operator("orivot.set_origin_extreme_full", text="Bottom Left Back (-X-Y-Z)").mode = 'VERT_BLB'
            layout.operator("orivot.set_origin_extreme_full", text="Bottom Right Back (+X-Y-Z)").mode = 'VERT_BRB'


class VIEW3D_MT_set_origin_edges(bpy.types.Menu):
    bl_label = "Edge Midpoints (12)"

    def draw(self, context):
        menu_draw_handler(self, context)
        layout = self.layout
        scene = context.scene

        layout.label(text="Top ring (+Z)")
        if scene.orivot_flip_left_right:
            layout.operator("orivot.set_origin_extreme_full", text="Top Left (+X)").mode = 'EDGE_TOP_LEFT'
            layout.operator("orivot.set_origin_extreme_full", text="Top Right (-X)").mode = 'EDGE_TOP_RIGHT'
        else:
            layout.operator("orivot.set_origin_extreme_full", text="Top Left (-X)").mode = 'EDGE_TOP_LEFT'
            layout.operator("orivot.set_origin_extreme_full", text="Top Right (+X)").mode = 'EDGE_TOP_RIGHT'

        layout.operator("orivot.set_origin_extreme_full", text="Top Front (+Y)").mode = 'EDGE_TOP_FRONT'
        layout.operator("orivot.set_origin_extreme_full", text="Top Back (-Y)").mode = 'EDGE_TOP_BACK'
        layout.separator()

        layout.label(text="Bottom ring (-Z)")
        if scene.orivot_flip_left_right:
            layout.operator("orivot.set_origin_extreme_full", text="Bottom Left (+X)").mode = 'EDGE_BOT_LEFT'
            layout.operator("orivot.set_origin_extreme_full", text="Bottom Right (-X)").mode = 'EDGE_BOT_RIGHT'
        else:
            layout.operator("orivot.set_origin_extreme_full", text="Bottom Left (-X)").mode = 'EDGE_BOT_LEFT'
            layout.operator("orivot.set_origin_extreme_full", text="Bottom Right (+X)").mode = 'EDGE_BOT_RIGHT'

        layout.operator("orivot.set_origin_extreme_full", text="Bottom Front (+Y)").mode = 'EDGE_BOT_FRONT'
        layout.operator("orivot.set_origin_extreme_full", text="Bottom Back (-Y)").mode = 'EDGE_BOT_BACK'
        layout.separator()

        layout.label(text="Middle edges")
        if scene.orivot_flip_left_right:
            layout.operator("orivot.set_origin_extreme_full", text="Front Left (+X+Y)").mode = 'EDGE_FRONT_LEFT'
            layout.operator("orivot.set_origin_extreme_full", text="Front Right (-X+Y)").mode = 'EDGE_FRONT_RIGHT'
            layout.operator("orivot.set_origin_extreme_full", text="Back Left (+X-Y)").mode = 'EDGE_BACK_LEFT'
            layout.operator("orivot.set_origin_extreme_full", text="Back Right (-X-Y)").mode = 'EDGE_BACK_RIGHT'
        else:
            layout.operator("orivot.set_origin_extreme_full", text="Front Left (-X+Y)").mode = 'EDGE_FRONT_LEFT'
            layout.operator("orivot.set_origin_extreme_full", text="Front Right (+X+Y)").mode = 'EDGE_FRONT_RIGHT'
            layout.operator("orivot.set_origin_extreme_full", text="Back Left (-X-Y)").mode = 'EDGE_BACK_LEFT'
            layout.operator("orivot.set_origin_extreme_full", text="Back Right (+X-Y)").mode = 'EDGE_BACK_RIGHT'


class VIEW3D_MT_set_origin_centers(bpy.types.Menu):
    bl_label = "Centers (Face Centers)"

    def draw(self, context):
        menu_draw_handler(self, context)
        layout = self.layout
        scene = context.scene

        layout.operator("orivot.set_origin_extreme_full", text="Top (+Z)").mode = 'CENTER_TOP'
        layout.operator("orivot.set_origin_extreme_full", text="Bottom (-Z)").mode = 'CENTER_BOTTOM'

        if scene.orivot_flip_left_right:
            layout.operator("orivot.set_origin_extreme_full", text="Left (+X)").mode = 'CENTER_LEFT'
            layout.operator("orivot.set_origin_extreme_full", text="Right (-X)").mode = 'CENTER_RIGHT'
        else:
            layout.operator("orivot.set_origin_extreme_full", text="Left (-X)").mode = 'CENTER_LEFT'
            layout.operator("orivot.set_origin_extreme_full", text="Right (+X)").mode = 'CENTER_RIGHT'

        layout.operator("orivot.set_origin_extreme_full", text="Front (+Y)").mode = 'CENTER_FRONT'
        layout.operator("orivot.set_origin_extreme_full", text="Back (-Y)").mode = 'CENTER_BACK'


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


