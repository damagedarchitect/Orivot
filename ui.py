"""Orivot sidebar layout (N-panel tab "Orivot").

Two tool groups, each a native panel with collapsible sub-panels that show only in the
mode where they work:

  Origin Snaps   moves the ORIGIN only; the geometry never moves
  Object Snaps   moves / rotates whole OBJECTS (Object Mode) or geometry (Edit Mode)
  Fabrication    cut files, cut lists, flat-pack, mates, datums
  Settings       preview & display, saved configurations

Every sub-panel has a ? button in its header: it opens an animated explanation inside the
panel (see help.py). Panels are native Blender panels: Ctrl-click a header to collapse all
others, drag headers to reorder.
"""

import math
import sys

import bpy
from mathutils import Vector

from . import help as _help
from . import tier

CATEGORY = "Orivot"


def _pkg():
    return sys.modules[__package__]


def _mesh_active(context):
    o = context.active_object
    return o is not None and o.type == 'MESH'


# ──────────────────────────────────────────────────────────────────────────────
# Base classes
# ──────────────────────────────────────────────────────────────────────────────

class _Panel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY
    help_id = None
    modes = None            # None = any mode, else a set of context.mode values

    @classmethod
    def poll(cls, context):
        return cls.modes is None or context.mode in cls.modes

    def draw_header_preset(self, context):
        if self.help_id:
            _help.header_button(self.layout, context, self.help_id)

    def draw(self, context):
        if self.help_id:
            _help.draw_inline(self.layout, context, self.help_id)
        self.body(context)

    def body(self, context):
        pass


_OBJ = {'OBJECT'}
_EDIT = {'EDIT_MESH'}
_BOTH = {'OBJECT', 'EDIT_MESH'}


# ══════════════════════════════════════════════════════════════════════════════
# ORIGIN SNAPS
# ══════════════════════════════════════════════════════════════════════════════

class VIEW3D_PT_orivot_origin(_Panel, bpy.types.Panel):
    bl_label = "Origin Snaps"
    bl_idname = "VIEW3D_PT_orivot_origin"
    bl_order = 0
    help_id = "origin"

    def draw_header(self, context):
        self.layout.label(text="", icon='OBJECT_ORIGIN')

    def body(self, context):
        layout = self.layout
        scene = context.scene
        obj = context.active_object
        if context.mode not in _BOTH:
            layout.label(text="Object Mode or mesh Edit Mode", icon='INFO')
            return
        if context.mode == 'EDIT_MESH':
            r = layout.row()
            r.label(text="Edit Mode origin tools: Orivot Basic", icon='EDITMODE_HLT')
            return
        box = layout.box()
        hdr = box.row(align=True)
        hdr.label(text="Moves the origin — geometry stays", icon='INFO')
        hdr.operator("wm.call_menu_pie", text="", icon='MESH_ICOSPHERE',
                     emboss=False).name = 'VIEW3D_MT_orivot_pie'
        row = box.row(align=True)
        row.prop(scene, "orivot_snap_source", text="")
        row.prop(scene, "orivot_preview_orientation", text="")
        row = box.row(align=True)
        row.label(text="Front:", icon='ORIENTATION_LOCAL')
        row.prop(scene, "orivot_front_axis", text="")
        return


class VIEW3D_PT_orivot_quick(_Panel, bpy.types.Panel):
    bl_label = "Quick Snap"
    bl_parent_id = "VIEW3D_PT_orivot_origin"
    help_id = "quick"
    modes = _OBJ

    def body(self, context):
        layout = self.layout
        scene = context.scene
        obj = context.active_object
        col = layout.column(align=True)
        row = col.row(align=True)
        row.scale_y = 1.15
        row.operator("orivot.set_origin_extreme_full", text="3D Cursor", icon='CURSOR').mode = 'CURSOR'
        row.operator("orivot.snap_to_world_zero", text="World Zero", icon='WORLD')
        return


def _op(row, text, mode):
    row.operator("orivot.set_origin_extreme_full", text=text).mode = mode


class VIEW3D_PT_orivot_points(_Panel, bpy.types.Panel):
    bl_label = "Snap Points"
    bl_parent_id = "VIEW3D_PT_orivot_origin"
    help_id = "points"
    modes = _OBJ

    def body(self, context):
        layout = self.layout
        scene = context.scene
        # the buttons act on every selected mesh, so a curve or empty that happens to be
        # active (e.g. picked last for Along Curve) must not hide them
        if not (_mesh_active(context) or any(o.type == 'MESH' for o in context.selected_objects)):
            layout.label(text="Select a mesh object", icon='INFO')
            return
        flip = scene.orivot_flip_left_right
        L, R = ("-X", "+X") if flip else ("+X", "-X")

        def section(prop, title):
            on = getattr(scene, prop)
            r = layout.row(align=True)
            r.alignment = 'LEFT'
            r.prop(scene, prop, text=title, icon='DISCLOSURE_TRI_DOWN' if on else 'DISCLOSURE_TRI_RIGHT',
                   emboss=False)
            return layout.column(align=True) if on else None

        col = section("orivot_show_faces", "Faces (extreme sides)")
        if col:
            r = col.row(align=True); _op(r, "Top (+Z)", 'FACE_TOP'); _op(r, "Bottom (-Z)", 'FACE_BOTTOM')
            r = col.row(align=True); _op(r, "Front (+Y)", 'FACE_FRONT'); _op(r, "Back (-Y)", 'FACE_BACK')
            r = col.row(align=True); _op(r, f"Left ({L})", 'FACE_LEFT'); _op(r, f"Right ({R})", 'FACE_RIGHT')
        col = section("orivot_show_vertices", "Corners")
        if col:
            for top, z in (("Top", "+Z"), ("Bottom", "-Z")):
                t = top[0]
                r = col.row(align=True)
                _op(r, f"{top} L-Front", f'VERT_{t}LF'); _op(r, f"{top} R-Front", f'VERT_{t}RF')
                r = col.row(align=True)
                _op(r, f"{top} L-Back", f'VERT_{t}LB'); _op(r, f"{top} R-Back", f'VERT_{t}RB')
            col.label(text=f"Left = {L}, Front = +Y", icon='INFO')
        col = section("orivot_show_edges", "Edge Midpoints")
        if col:
            col.label(text="Top ring:")
            r = col.row(align=True); _op(r, "Left", 'EDGE_TOP_LEFT'); _op(r, "Right", 'EDGE_TOP_RIGHT')
            _op(r, "Front", 'EDGE_TOP_FRONT'); _op(r, "Back", 'EDGE_TOP_BACK')
            col.label(text="Bottom ring:")
            r = col.row(align=True); _op(r, "Left", 'EDGE_BOT_LEFT'); _op(r, "Right", 'EDGE_BOT_RIGHT')
            _op(r, "Front", 'EDGE_BOT_FRONT'); _op(r, "Back", 'EDGE_BOT_BACK')
            col.label(text="Vertical edges:")
            r = col.row(align=True); _op(r, "Front L", 'EDGE_FRONT_LEFT'); _op(r, "Front R", 'EDGE_FRONT_RIGHT')
            r = col.row(align=True); _op(r, "Back L", 'EDGE_BACK_LEFT'); _op(r, "Back R", 'EDGE_BACK_RIGHT')
        col = section("orivot_show_centers", "Face Centers")
        if col:
            r = col.row(align=True); _op(r, "Top", 'CENTER_TOP'); _op(r, "Bottom", 'CENTER_BOTTOM')
            r = col.row(align=True); _op(r, "Front", 'CENTER_FRONT'); _op(r, "Back", 'CENTER_BACK')
            r = col.row(align=True); _op(r, f"Left ({L})", 'CENTER_LEFT'); _op(r, f"Right ({R})", 'CENTER_RIGHT')
        col = section("orivot_show_global_centers",
                      ("Object Centers"))
        if col:
            r = col.row(align=True)
            _op(r, "Geometry", 'CENTER_GEOMETRY'); _op(r, "BBox", 'CENTER_BBOX'); _op(r, "Mass", 'CENTER_MASS')
            return


# ══════════════════════════════════════════════════════════════════════════════
# OBJECT SNAPS
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

class VIEW3D_PT_orivot_settings(_Panel, bpy.types.Panel):
    bl_label = "Settings"
    bl_idname = "VIEW3D_PT_orivot_settings"
    bl_order = 3
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='PREFERENCES')

    def body(self, context):
        r = self.layout.row(align=True)
        r.operator("orivot.show_shortcuts_info", text="Shortcuts", icon='EVENT_ALT')
        r.operator("preferences.addon_show", text="Defaults", icon='PREFERENCES').module = __package__
        try:
            prefs = context.preferences.addons[__package__].preferences
            self.layout.prop(prefs, "show_help_buttons", icon='QUESTION')
        except Exception:
            pass
        col = self.layout.column(align=True)
        col.prop(context.scene, "orivot_flip_left_right", text="Swap Left / Right labels")
        col.prop(context.scene, "orivot_show_mode_indicator", text="Mode indicator in viewport")


class VIEW3D_PT_orivot_upgrade(_Panel, bpy.types.Panel):
    """Free / Basic only: what the next edition adds, and where to get it."""
    bl_label = "More Tools"
    bl_idname = "VIEW3D_PT_orivot_upgrade"
    bl_order = 4
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.label(text="", icon='PLUS')

    def body(self, context):
        col = self.layout.column(align=True)
        col.label(text="Orivot Basic adds:", icon='ADD')
        for t in ("Surface / Vertex snap and Alt+click", "Clickable bounding-box handles",
                  "Live preview of the next snap", "Multi-Object, Offset & Freeze",
                  "Copy / Paste origin, Mirror Plane", "Edit Mode selection snaps, history"):
            col.label(text="   " + t)
        col.operator("orivot.open_upgrade", text="Get Orivot Basic", icon='URL').edition = 'BASIC'
        col.separator()
        col.label(text="Orivot Pro adds:", icon='ADD')
        for t in ("Along Curve, Origin Axes, Pivot Library", "Object Snaps: snap, drop, align, rotate",
                  "Line Snap and Axis Transform (Edit Mode)", "Collision check, Chain / Distribute",
                  "Saved Configurations, CSV export", "Fabrication: CNC cut files, nesting"):
            col.label(text="   " + t)
        col.operator("orivot.open_upgrade", text="Get Orivot Pro", icon='URL').edition = 'PRO'


ORIGIN_PANELS = (VIEW3D_PT_orivot_origin, VIEW3D_PT_orivot_quick, VIEW3D_PT_orivot_points)
OBJECT_PANELS = ()
SETTINGS_PANELS = (VIEW3D_PT_orivot_settings,)

# What each edition shows (see tier.py). Order is the sidebar order.
_FREE = {VIEW3D_PT_orivot_origin, VIEW3D_PT_orivot_quick, VIEW3D_PT_orivot_points,
         VIEW3D_PT_orivot_settings}
_BASIC = _FREE | set()
_ALL = ORIGIN_PANELS + OBJECT_PANELS + SETTINGS_PANELS
CLASSES = tuple(c for c in _ALL if c in ((_FREE))) + (VIEW3D_PT_orivot_upgrade,)


def attach_help():
    """Give the panels that live in other modules the same ? button and help box."""
    P = _pkg()
    pairs = []
    if getattr(P, "linesnap", None) is not None:
        pairs.append((P.linesnap.VIEW3D_PT_orivot_linesnap, "line_snap"))
    if getattr(P, "axistransform", None) is not None:
        pairs.append((P.axistransform.VIEW3D_PT_orivot_axis, "axis_transform"))
    if getattr(P, "fab", None) is not None:
        ops = P.fab.ops
        pairs += [(ops.VIEW3D_PT_orivot_fab, "fab"),
                  (ops.VIEW3D_PT_orivot_fab_production, "fab_sheet"),
                  (ops.VIEW3D_PT_orivot_fab_output, "fab_output"),
                  (ops.VIEW3D_PT_orivot_fab_assembly, "fab_assembly"),
                  (ops.VIEW3D_PT_orivot_fab_datums, "fab_datums")]
    for cls, topic in pairs:
        _help.attach(cls, topic)


def register():
    attach_help()
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(c)
        except Exception:
            pass
