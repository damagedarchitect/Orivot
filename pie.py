"""The Alt+Q pie menu and its customisable action registry.

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


def _pkg():
    return sys.modules[__package__]


# ── Orivot Pro Pie Menu — customizable action registry ──────────────────────────
# Each entry: (identifier, label, description, icon, enum_number).
# Used both as the EnumProperty items for the 8 slot preferences and as the
# dispatch key when drawing the pie itself, so the two never drift apart.
ORIVOT_PIE_ACTIONS = [
    ('LEFT',              "Left (+X)",         "Snap origin to the -X extreme face",                    'TRIA_LEFT',      1),
    ('RIGHT',             "Right (-X)",        "Snap origin to the +X extreme face",                    'TRIA_RIGHT',     2),
    ('BOTTOM',            "Bottom (-Z)",       "Snap origin to the bottom extreme face",                'TRIA_DOWN',      3),
    ('TOP',                "Top (+Z)",         "Snap origin to the top extreme face",                   'TRIA_UP',        4),
    ('BACK',               "Back (-Y)",        "Snap origin to the back extreme face",                  'BACK',           5),
    ('FRONT',              "Front (+Y)",       "Snap origin to the front extreme face",                 'FORWARD',        6),
    ('SURFACE_SNAP',       "Surface Snap",     "Interactively snap origin to a clicked surface point",  'PIVOT_CURSOR',   7),
    ('VERTEX_SNAP',        "Vertex Snap",      "Drag across the mesh to snap origin to the nearest vertex", 'VERTEXSEL',  8),
    ('CENTER_GEOMETRY',    "Center Geometry",  "Snap origin to the geometric center",                   'PIVOT_MEDIAN',   9),
    ('CENTER_BBOX',        "Center BBox",      "Snap origin to the bounding box center",                'PIVOT_BOUNDBOX',10),
    ('CENTER_MASS',        "Center Mass",      "Snap origin to the center of mass",                     'MOD_PHYSICS',   11),
    ('GLOBAL_CENTERS',     "Global Centers (Geo / BBox / Mass)",
                           "Stack the Geometry, BBox and Mass center buttons in one pie slot",           'PIVOT_BOUNDBOX',12),
    ('CLICK_BBOX_HANDLE',  "Click BBox Handle","Click a viewport bounding-box handle to snap origin there", 'SNAP_ON',    13),
    ('COPY_ORIGIN',        "Copy Origin",      "Copy this object's origin to the Orivot clipboard",      'COPYDOWN',      14),
    ('PASTE_ORIGIN',       "Paste Origin",     "Paste the copied origin onto selected objects",         'PASTEDOWN',     15),
    ('ORIGIN_TOOLS',       "Origin Tools (Copy / Paste / BBox Handle)",
                           "Stack the Copy Origin, Paste Origin and Click BBox Handle buttons in one pie slot", 'COPYDOWN', 16),
    ('EDITMODE_SNAP',      "Edit Mode Snap",   "Snap origin to the bbox extreme of the Edit Mode selection", 'SNAP_ON',  17),
    ('OBJECT_SNAP_INSTANT',"Snap to Object",   "Snap selected object(s) to the active target object",   'SNAP_ON',       18),
    ('PLACE_ON_SURFACE',   "Place on Surface", "Interactively place source object(s) on target's surface", 'CURSOR',     19),
    ('SNAP_TO_CURVE',      "Snap to Curve",    "Snap origin to a position along a selected curve",       'CURVE_DATA',    20),
    ('WORLD_ZERO',         "World Zero",       "Snap origin to world (0, 0, 0)",                        'WORLD',         21),
    ('SNAP_TO_GRID',       "Snap to Grid",     "Snap origin to the nearest world grid intersection",    'SNAP_GRID',     22),
    ('SYMMETRY_AUTO',      "Mirror Plane (Auto)",  "Centre the origin on every axis the mesh is mirror-symmetric on", 'MOD_MIRROR',    23),
    ('OBJECT_TO_CURSOR',   "Object to Cursor", "Move the selection so its chosen handle sits on the 3D cursor", 'ORIENTATION_CURSOR', 25),
    ('CURSOR_TO_BOX',      "Cursor to Box Point", "Put the 3D cursor on a bounding-box point of the active object", 'PIVOT_CURSOR', 26),
    ('DROP_TO_BED',        "Drop to Bed",      "Rest the selection on Z = 0 (print bed / floor)",         'TRIA_DOWN_BAR', 27),
    ('DROP_TO_LEVEL',      "Drop to Level",    "Rest the selection on the Orivot level below it",         'ANCHOR_BOTTOM', 28),
    ('SNAP_TO_GRIDLINES',  "Snap to Gridlines","Snap the selection to the nearest Orivot gridline intersection", 'MESH_GRID', 29),
    ('NONE',               "— Empty —",        "Leave this pie position empty",                         'BLANK1',        24),
]


# Default layout: the six directional faces keep their original priority
# positions; Global Centers (Geometry + BBox + Mass together) takes the SW
# slot in place of the old lone "Center Geo" button so BBox and Mass get
# first-class pie access too, and Surface Snap keeps SE.
ORIVOT_PIE_DEFAULTS = ('LEFT', 'RIGHT', 'BOTTOM', 'TOP', 'BACK', 'FRONT',
                       'GLOBAL_CENTERS', 'SURFACE_SNAP')  # W E S N NW NE SW SE


# Editions: Free offers the snap points, centres and World Zero; Basic adds its
# interactive and origin tools; the object tools are Pro.
_PIE_BASIC = {'SURFACE_SNAP', 'VERTEX_SNAP', 'CLICK_BBOX_HANDLE', 'COPY_ORIGIN',
              'PASTE_ORIGIN', 'ORIGIN_TOOLS', 'EDITMODE_SNAP', 'SNAP_TO_GRID', 'SYMMETRY_AUTO',
              'OBJECT_TO_CURSOR', 'CURSOR_TO_BOX', 'DROP_TO_BED'}


_PIE_PRO = {'OBJECT_SNAP_INSTANT', 'PLACE_ON_SURFACE', 'SNAP_TO_CURVE', 'DROP_TO_LEVEL',
            'SNAP_TO_GRIDLINES'}


ORIVOT_PIE_ACTIONS = [a for a in ORIVOT_PIE_ACTIONS
                      if (((a[0] not in _PIE_BASIC))) and (((a[0] not in _PIE_PRO)))]


ORIVOT_PIE_DEFAULTS = ORIVOT_PIE_DEFAULTS[:7] + ('WORLD_ZERO',)


_EXTREME = "orivot.set_origin_extreme_full"

# Single-button actions: id -> (operator, properties, label, icon). The pie, the
# Run Action operator (hotkeys) and the tests all read this one table.
ACTION_OPS = {
    'LEFT':                (_EXTREME, {'mode': 'FACE_LEFT'},   "Left (+X)",   'TRIA_LEFT'),
    'RIGHT':               (_EXTREME, {'mode': 'FACE_RIGHT'},  "Right (-X)",  'TRIA_RIGHT'),
    'BOTTOM':              (_EXTREME, {'mode': 'FACE_BOTTOM'}, "Bottom (-Z)", 'TRIA_DOWN'),
    'TOP':                 (_EXTREME, {'mode': 'FACE_TOP'},    "Top (+Z)",    'TRIA_UP'),
    'BACK':                (_EXTREME, {'mode': 'FACE_BACK'},   "Back (-Y)",   'BACK'),
    'FRONT':               (_EXTREME, {'mode': 'FACE_FRONT'},  "Front (+Y)",  'FORWARD'),
    'CENTER_GEOMETRY':     (_EXTREME, {'mode': 'CENTER_GEOMETRY'}, "Center Geometry", 'PIVOT_MEDIAN'),
    'CENTER_BBOX':         (_EXTREME, {'mode': 'CENTER_BBOX'}, "Center BBox", 'PIVOT_BOUNDBOX'),
    'CENTER_MASS':         (_EXTREME, {'mode': 'CENTER_MASS'}, "Center Mass", 'MOD_PHYSICS'),
    'SURFACE_SNAP':        ("orivot.surface_snap_origin", {}, "Surface Snap", 'PIVOT_CURSOR'),
    'VERTEX_SNAP':         ("orivot.vertex_snap_origin", {}, "Vertex Snap", 'VERTEXSEL'),
    'CLICK_BBOX_HANDLE':   ("orivot.click_bbox_handle", {}, "Click BBox Handle", 'SNAP_ON'),
    'COPY_ORIGIN':         ("orivot.copy_origin", {}, "Copy Origin", 'COPYDOWN'),
    'PASTE_ORIGIN':        ("orivot.paste_origin", {}, "Paste Origin", 'PASTEDOWN'),
    'EDITMODE_SNAP':       ("orivot.editmode_snap", {}, "Edit Mode Snap", 'SNAP_ON'),
    'OBJECT_SNAP_INSTANT': ("orivot.object_snap_instant", {}, "Snap to Object", 'SNAP_ON'),
    'PLACE_ON_SURFACE':    ("orivot.place_on_surface", {}, "Place on Surface", 'CURSOR'),
    'SNAP_TO_CURVE':       ("orivot.snap_to_curve", {}, "Snap to Curve", 'CURVE_DATA'),
    'WORLD_ZERO':          ("orivot.snap_to_world_zero", {}, "World Zero", 'WORLD'),
    'SNAP_TO_GRID':        ("orivot.snap_to_grid", {}, "Snap to Grid", 'SNAP_GRID'),
    'SYMMETRY_AUTO':       ("orivot.symmetry_origin", {'axis': 'AUTO'}, "Mirror Plane (Auto)", 'MOD_MIRROR'),
    'OBJECT_TO_CURSOR':    ("orivot.object_to_cursor", {}, "Object to Cursor", 'ORIENTATION_CURSOR'),
    'CURSOR_TO_BOX':       ("orivot.cursor_to_point", {'target': 'BOX'}, "Cursor to Box Point", 'PIVOT_CURSOR'),
    'DROP_TO_BED':         ("orivot_fab.drop_to_bed", {}, "Drop to Bed", 'TRIA_DOWN_BAR'),
    'DROP_TO_LEVEL':       ("orivot.drop_to_level", {}, "Drop to Level", 'ANCHOR_BOTTOM'),
    'SNAP_TO_GRIDLINES':   ("orivot.snap_to_gridlines", {}, "Snap to Gridlines", 'MESH_GRID'),
}
_AVAILABLE = {a[0] for a in ORIVOT_PIE_ACTIONS}
ACTION_OPS = {k: v for k, v in ACTION_OPS.items() if k in _AVAILABLE}


def _orivot_pie_draw_action(layout, action, prefs):
    """Draw one pie-menu action into `layout` (a pie slot or a column)."""
    op_id = _EXTREME

    if action == 'NONE':
        return
    entry = ACTION_OPS.get(action)
    if entry is not None:
        idname, props, text, icon = entry
        op = layout.operator(idname, text=text, icon=icon)
        for k, v in props.items():
            setattr(op, k, v)
        return
    if action == 'GLOBAL_CENTERS':
        col = layout.column(align=True)
        col.label(text="Global Centers", icon='PIVOT_BOUNDBOX')
        show_geo  = getattr(prefs, 'pie_gc_show_geometry', True) if prefs else True
        show_bbox = getattr(prefs, 'pie_gc_show_bbox',     True) if prefs else True
        show_mass = getattr(prefs, 'pie_gc_show_mass',     True) if prefs else True
        if show_geo:
            col.operator(op_id, text="Geometry", icon='PIVOT_MEDIAN').mode = 'CENTER_GEOMETRY'
        if show_bbox:
            col.operator(op_id, text="BBox", icon='PIVOT_BOUNDBOX').mode = 'CENTER_BBOX'
        if show_mass:
            col.operator(op_id, text="Mass", icon='MOD_PHYSICS').mode = 'CENTER_MASS'
    elif action == 'ORIGIN_TOOLS':
        col = layout.column(align=True)
        col.label(text="Origin Tools", icon='COPYDOWN')
        show_copy   = getattr(prefs, 'pie_ot_show_copy',   True) if prefs else True
        show_paste  = getattr(prefs, 'pie_ot_show_paste',  True) if prefs else True
        show_handle = getattr(prefs, 'pie_ot_show_handle', True) if prefs else True
        if show_copy:
            col.operator("orivot.copy_origin", text="Copy", icon='COPYDOWN')
        if show_paste:
            col.operator("orivot.paste_origin", text="Paste", icon='PASTEDOWN')
        if show_handle:
            col.operator("orivot.click_bbox_handle", text="BBox Handle", icon='SNAP_ON')


def _orivot_get_prefs(context):
    try:
        return context.preferences.addons[__package__].preferences
    except (KeyError, AttributeError):
        return None


class VIEW3D_MT_orivot_pie(bpy.types.Menu):
    """Orivot Pro quick-access pie menu (Alt+Q in 3D View).
    Fully customizable: reassign any of the 8 positions, and choose which
    buttons appear in the Global Centers slot, from Preferences."""
    bl_label = tier.NAME

    def draw(self, context):
        layout = self.layout
        pie    = layout.menu_pie()
        prefs  = _orivot_get_prefs(context)

        if prefs is not None:
            slots = (prefs.pie_slot_w, prefs.pie_slot_e, prefs.pie_slot_s, prefs.pie_slot_n,
                      prefs.pie_slot_nw, prefs.pie_slot_ne, prefs.pie_slot_sw, prefs.pie_slot_se)
        else:
            slots = ORIVOT_PIE_DEFAULTS

        for action in slots:
            if action == 'NONE':
                pie.separator()
            else:
                _orivot_pie_draw_action(pie, action, prefs)




_ACTION_ITEMS = [(a[0], a[1], a[2], a[3], a[4]) for a in ORIVOT_PIE_ACTIONS if a[0] in ACTION_OPS]


class ORIVOT_OT_run_action(bpy.types.Operator):
    """Run one Orivot pie action. Bind it to any key in Preferences ▸ Keymap (or the
    Orivot add-on preferences ▸ Shortcuts) to reach an action without the pie"""
    bl_idname = "orivot.run_action"
    bl_label = "Orivot Action"
    bl_options = {'INTERNAL'}

    action: bpy.props.EnumProperty(name="Action", items=_ACTION_ITEMS)

    @classmethod
    def description(cls, context, props):
        e = ACTION_OPS.get(props.action) if props else None
        return f"Orivot: {e[2]}" if e else cls.__doc__

    def invoke(self, context, event):
        return self._run('INVOKE_DEFAULT')

    def execute(self, context):
        return self._run('EXEC_DEFAULT')

    def _run(self, how):
        idname, props, text, _icon = ACTION_OPS[self.action]
        mod, name = idname.split(".")
        op = getattr(getattr(bpy.ops, mod), name)
        if not op.poll():
            self.report({'WARNING'}, f"{text}: not available here (check the selection / mode)")
            return {'CANCELLED'}
        try:
            r = op(how, **props)
        except RuntimeError as e:
            self.report({'WARNING'}, f"{text}: {e}")
            return {'CANCELLED'}
        # The called operator owns its undo step (and its modal handler, if it is an
        # interactive tool), so the wrapper just reports whether it started.
        return {'FINISHED'} if r & {'FINISHED', 'RUNNING_MODAL'} else {'CANCELLED'}


def register_action_keymaps(km, out):
    """One inactive 'Orivot Action' entry per action, so each can be switched on and given
    a key in Preferences ▸ Keymap (or the add-on preferences ▸ Shortcuts). They are
    created at register time so the user's key choices persist (Blender stores them as
    edits of these entries)."""
    for action in ACTION_OPS:
        kmi = km.keymap_items.new(ORIVOT_OT_run_action.bl_idname, 'NONE', 'PRESS')
        kmi.properties.action = action
        kmi.active = False
        out.append((km, kmi))
