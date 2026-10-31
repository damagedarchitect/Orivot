"""Add-on preferences and the property groups they use.

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

from . import configs as _configs
from . import tier
from . import support
from . import icons
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
from . import pie
from . import op_tools


def _pkg():
    return sys.modules[__package__]


class OriginMOCustomObject(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(
        name="Object",
        type=bpy.types.Object,
        description="Mesh object to affect"
    )


# ---------------- Registration ----------------
class OrivotAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    # ---- Highlight ----
    default_highlight_color: bpy.props.FloatVectorProperty(
        name="Highlight Color",
        subtype='COLOR',
        default=(1.0, 0.0, 0.0),
        min=0.0, max=1.0,
        description="Default color for the face highlight quad"
    )
    default_highlight_alpha: bpy.props.FloatProperty(
        name="Transparency",
        default=0.35,
        min=0.0, max=1.0,
        description="Default opacity of the face highlight quad"
    )
    default_face_offset: bpy.props.FloatProperty(
        name="Face Offset",
        default=0.001,
        min=0.0, max=0.1,
        step=0.01, precision=3,
        description="Default push distance to prevent z-fighting with the mesh surface (metres)"
    )

    # ---- Arrow ----
    default_arrow_scale: bpy.props.FloatProperty(
        name="Arrow Scale",
        default=0.4,
        min=0.01, max=3.0,
        step=1, precision=2,
        description="Default arrow length as a ratio of the object's bounding box "
                    "max dimension (0.4 = 40% of the largest side). Scales with object size."
    )

    # ---- Snap ----
    default_snap_source: bpy.props.EnumProperty(
        name="Snap Source",
        items=[
            ('MESH', "Mesh (Geometry)", "Snap to evaluated mesh geometry"),
            ('BBOX', "Bounding Box",    "Snap to object bounding box"),
        ],
        default='MESH',
        description="Default geometry source used for snapping"
    )
    default_orientation: bpy.props.EnumProperty(
        name="Orientation",
        items=[
            ('LOCAL',  "Local",  "Preview aligned to object's local axes"),
            ('GLOBAL', "Global", "Preview aligned to world axes"),
        ],
        default='LOCAL',
        description="Default preview orientation mode"
    )
    default_front_axis: bpy.props.EnumProperty(
        name="Front Face Axis",
        items=[
            ('LOCAL_Y_POS', "+Y  (Blender Default)", "Local +Y is front"),
            ('LOCAL_Y_NEG', "−Y",                    "Local −Y is front"),
            ('LOCAL_X_POS', "+X  (UE5 Default)",     "Local +X is front"),
            ('LOCAL_X_NEG', "−X",                    "Local −X is front"),
            ('LOCAL_Z_POS', "+Z  (Top)",              "Local +Z is front"),
            ('LOCAL_Z_NEG', "−Z  (Bottom)",           "Local −Z is front"),
        ],
        default='LOCAL_Y_POS',
        description="Default front-face axis designation"
    )

    # ---- Behaviour ----
    default_auto_recalc: bpy.props.BoolProperty(
        name="Auto-Update Preview",
        default=True,
        description="Automatically refresh preview when the object changes"
    )
    default_auto_show_on_hover: bpy.props.BoolProperty(
        name="Auto-Show on Menu Hover",
        default=True,
        description="Automatically show preview when hovering over Orivot menus"
    )
    default_show_bbox_wireframe: bpy.props.BoolProperty(
        name="Show BBox Wireframe",
        default=True,
        description="Show wireframe cube in BBox mode"
    )
    default_hide_arrow_when_muted: bpy.props.BoolProperty(
        name="Hide Arrow When Muted",
        default=True,
        description="Hide the arrow when a preview is muted"
    )
    show_shortcuts: bpy.props.BoolProperty(
        name="Shortcuts", default=False,
        description="Show every Orivot hotkey, including the pie actions you can bind to a key")
    show_help_buttons: bpy.props.BoolProperty(
        name="Help Buttons (?)",
        default=True,
        description="Show a ? button in every Orivot panel header. It opens a short looping "
                    "animation and a few lines explaining that panel's tools"
    )
    remember_panel_scroll: bpy.props.BoolProperty(
        name="Remember Panel Scroll",
        default=True,
        description="Remember where the Orivot sidebar tab was scrolled to in each "
                    "mode (Object / Edit) and restore it when you switch modes"
    )

    fab_heart_seen: bpy.props.BoolProperty(
        name="Fabricator Heart Seen", default=False, options={'HIDDEN'},
        description="Pro: the blue heart in the sidebar was clicked once and stays hidden")

    # ---- Support (4.3) ----
    log_verbose: bpy.props.BoolProperty(
        name="Print Caught Errors",
        default=False,
        description="Print each error Orivot catches and skips (once per place) to the system "
                    "console. Useful when something silently does nothing")
    log_to_file: bpy.props.BoolProperty(
        name="Write Log File",
        default=False,
        description="Also append caught errors to orivot_log.txt in Blender's config folder")

    configs         : bpy.props.CollectionProperty(type=_configs.OrivotConfig)
    named_groups    : bpy.props.CollectionProperty(type=op_tools.OrivotProNamedGroup)

    # ---- Pie Menu (Alt+Q) — fully customizable, Orivot Pro only ----
    pie_slot_w  : bpy.props.EnumProperty(name="West",      items=pie.ORIVOT_PIE_ACTIONS, default='LEFT',
        description="Action shown on the West (left) position of the pie menu")
    pie_slot_e  : bpy.props.EnumProperty(name="East",      items=pie.ORIVOT_PIE_ACTIONS, default='RIGHT',
        description="Action shown on the East (right) position of the pie menu")
    pie_slot_s  : bpy.props.EnumProperty(name="South",     items=pie.ORIVOT_PIE_ACTIONS, default='BOTTOM',
        description="Action shown on the South (bottom) position of the pie menu")
    pie_slot_n  : bpy.props.EnumProperty(name="North",     items=pie.ORIVOT_PIE_ACTIONS, default='TOP',
        description="Action shown on the North (top) position of the pie menu")
    pie_slot_nw : bpy.props.EnumProperty(name="Northwest", items=pie.ORIVOT_PIE_ACTIONS, default='BACK',
        description="Action shown on the Northwest position of the pie menu")
    pie_slot_ne : bpy.props.EnumProperty(name="Northeast", items=pie.ORIVOT_PIE_ACTIONS, default='FRONT',
        description="Action shown on the Northeast position of the pie menu")
    pie_slot_sw : bpy.props.EnumProperty(name="Southwest", items=pie.ORIVOT_PIE_ACTIONS, default='GLOBAL_CENTERS',
        description="Action shown on the Southwest position of the pie menu")
    pie_slot_se : bpy.props.EnumProperty(name="Southeast", items=pie.ORIVOT_PIE_ACTIONS, default=pie.ORIVOT_PIE_DEFAULTS[7],
        description="Action shown on the Southeast position of the pie menu")

    pie_gc_show_geometry : bpy.props.BoolProperty(name="Geometry", default=True,
        description="Include the Center Geometry button in the Global Centers pie slot")
    pie_gc_show_bbox     : bpy.props.BoolProperty(name="BBox",     default=True,
        description="Include the Center BBox button in the Global Centers pie slot")
    pie_gc_show_mass     : bpy.props.BoolProperty(name="Mass",     default=True,
        description="Include the Center Mass button in the Global Centers pie slot")

    pie_ot_show_copy     : bpy.props.BoolProperty(name="Copy",        default=True,
        description="Include the Copy Origin button in the Origin Tools pie slot")
    pie_ot_show_paste    : bpy.props.BoolProperty(name="Paste",       default=True,
        description="Include the Paste Origin button in the Origin Tools pie slot")
    pie_ot_show_handle   : bpy.props.BoolProperty(name="BBox Handle", default=True,
        description="Include the Click BBox Handle button in the Origin Tools pie slot")

    def draw(self, context):
        layout = self.layout

        # ---- Highlight / Arrow: the preview is a Basic / Pro tool ----

        # ---- Snap section ----
        box = layout.box()
        box.label(text="Snap Defaults", icon='SNAP_ON')
        row = box.row(align=True)
        row.prop(self, "default_snap_source",  text="Snap Source")
        row.prop(self, "default_orientation",  text="Orientation")
        box.prop(self, "default_front_axis",   text="Front Face Axis")

        # ---- Behaviour section ----
        box = layout.box()
        box.label(text="Behaviour Defaults", icon='SETTINGS')
        col = box.column(align=True)
        col.prop(self, "remember_panel_scroll")
        col.prop(self, "show_help_buttons")

        # ---- Pie Menu (Alt+Q) — Orivot Pro only ----
        box = layout.box()
        box.label(text="Pie Menu (Alt+Q)", icon='MESH_ICOSPHERE')
        box.label(text="Assign an action to each of the 8 pie positions.", icon='INFO')

        grid = box.grid_flow(row_major=True, columns=3, align=True)
        grid.prop(self, "pie_slot_nw", text="")
        grid.prop(self, "pie_slot_n",  text="")
        grid.prop(self, "pie_slot_ne", text="")
        grid.prop(self, "pie_slot_w",  text="")
        grid.label(text="", icon='MESH_ICOSPHERE')
        grid.prop(self, "pie_slot_e",  text="")
        grid.prop(self, "pie_slot_sw", text="")
        grid.prop(self, "pie_slot_s",  text="")
        grid.prop(self, "pie_slot_se", text="")

        sub = box.box()
        sub.label(text="Global Centers slot contents", icon='PIVOT_BOUNDBOX')
        row = sub.row(align=True)
        row.prop(self, "pie_gc_show_geometry", toggle=True)
        row.prop(self, "pie_gc_show_bbox",     toggle=True)
        row.prop(self, "pie_gc_show_mass",     toggle=True)


        box.operator("orivot.reset_pie_defaults", icon='LOOP_BACK')

        draw_shortcuts(self, context, layout)

        support.draw_prefs(self, layout)

        # Pro: the Fabricator link lives here for good (the sidebar heart shows only once)

    def _draw_preview_defaults(self, layout):
        box = layout.box()
        box.label(text="Highlight Defaults", icon='OVERLAY')
        row = box.row(align=True)
        row.prop(self, "default_highlight_color", text="Color")
        row = box.row(align=True)
        row.prop(self, "default_highlight_alpha", text="Transparency", slider=True)
        row.prop(self, "default_face_offset",     text="Face Offset",  slider=True)
        box = layout.box()
        box.label(text="Arrow Defaults", icon='EMPTY_SINGLE_ARROW')
        box.prop(self, "default_arrow_scale", text="Arrow Scale", slider=True)

        # ---- Apply button ----
        layout.separator()
        layout.operator("orivot.apply_preference_defaults",
                        text="Apply Defaults to Current Scene",
                        icon='CHECKMARK')


class ORIVOT_OT_apply_preference_defaults(bpy.types.Operator):
    """Push addon preference defaults into the current scene's Orivot properties"""
    bl_idname = "orivot.apply_preference_defaults"
    bl_label = "Apply Orivot Defaults"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        scene = context.scene

        scene.orivot_preview_color       = prefs.default_highlight_color
        scene.orivot_preview_alpha       = prefs.default_highlight_alpha
        scene.orivot_face_offset         = prefs.default_face_offset
        scene.orivot_arrow_scale         = prefs.default_arrow_scale
        scene.orivot_snap_source         = prefs.default_snap_source
        scene.orivot_preview_orientation = prefs.default_orientation
        scene.orivot_front_axis          = prefs.default_front_axis
        scene.orivot_snap_auto_recalc    = prefs.default_auto_recalc
        scene.orivot_auto_show_on_hover  = prefs.default_auto_show_on_hover
        scene.orivot_show_bbox_wireframe = prefs.default_show_bbox_wireframe
        scene.orivot_hide_arrow_when_muted = prefs.default_hide_arrow_when_muted

        self.report({'INFO'}, "Orivot: preference defaults applied to scene")
        return {'FINISHED'}


class ORIVOT_OT_reset_pie_defaults(bpy.types.Operator):
    """Reset the Orivot pie menu (Alt+Q) layout to its default configuration"""
    bl_idname  = "orivot.reset_pie_defaults"
    bl_label   = "Reset Pie Menu Layout"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        (prefs.pie_slot_w, prefs.pie_slot_e, prefs.pie_slot_s, prefs.pie_slot_n,
         prefs.pie_slot_nw, prefs.pie_slot_ne, prefs.pie_slot_sw, prefs.pie_slot_se) = pie.ORIVOT_PIE_DEFAULTS
        prefs.pie_gc_show_geometry = True
        prefs.pie_gc_show_bbox     = True
        prefs.pie_gc_show_mass     = True
        prefs.pie_ot_show_copy     = True
        prefs.pie_ot_show_paste    = True
        prefs.pie_ot_show_handle   = True
        self.report({'INFO'}, "Orivot: pie menu layout reset to defaults")
        return {'FINISHED'}




# ── Shortcuts: the add-on's own keymap entries, editable in place ─────────────

_KEYMAPS = ('3D View', 'Mesh')


def orivot_keymap_items(kc):
    """[(km, kmi)] of every Orivot entry in keyconfig `kc` (user or addon)."""
    out = []
    for name in _KEYMAPS:
        km = kc.keymaps.get(name) if kc else None
        if km is None:
            continue
        for kmi in km.keymap_items:
            if kmi.idname.startswith(("orivot.", "orivot_fab.")) or (
                    kmi.idname == 'wm.call_menu_pie'
                    and getattr(kmi.properties, "name", "") == 'VIEW3D_MT_orivot_pie'):
                out.append((km, kmi))
    return out


def draw_shortcuts(prefs, context, layout):
    box = layout.box()
    row = box.row()
    row.prop(prefs, "show_shortcuts", icon='TRIA_DOWN' if prefs.show_shortcuts else 'TRIA_RIGHT',
             emboss=False)
    if not prefs.show_shortcuts:
        return
    box.label(text="Tick an action and click its key field to bind it. Pie actions start "
                   "unbound.", icon='INFO')
    kc = context.window_manager.keyconfigs.user
    items = orivot_keymap_items(kc)
    bound = [x for x in items if x[1].active and x[1].type != 'NONE']
    free = [x for x in items if x not in bound]
    order = {a: i for i, a in enumerate(pie.ACTION_OPS)}
    free.sort(key=lambda x: order.get(getattr(x[1].properties, "action", ""), -1)
              if x[1].idname == pie.ORIVOT_OT_run_action.bl_idname else -1)
    col = box.column()
    for km, kmi in bound:
        _kmi_row(col, km, kmi)
    if free:
        col.separator()
        col.label(text="Unbound — tick to enable, then set a key")
        for km, kmi in free:
            _kmi_row(col, km, kmi)


def kmi_label(kmi):
    if kmi.idname == pie.ORIVOT_OT_run_action.bl_idname:
        e = pie.ACTION_OPS.get(kmi.properties.action)
        return f"Pie action: {e[2]}" if e else kmi.name
    if kmi.idname == 'wm.call_menu_pie':
        return "Orivot pie menu"
    return kmi.name


def _kmi_row(col, km, kmi):
    row = col.row(align=True)
    row.context_pointer_set("keymap", km)
    row.prop(kmi, "active", text="")
    sub = row.row(align=True)
    sub.active = kmi.active
    sub.label(text=kmi_label(kmi) + ("" if km.name == '3D View' else f"  ({km.name})"))
    sub.prop(kmi, "type", text="", full_event=True)
    if kmi.is_user_modified:
        row.operator("preferences.keyitem_restore", text="", icon='BACK').item_id = kmi.id
