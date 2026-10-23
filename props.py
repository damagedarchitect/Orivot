"""Scene properties every edition registers (moved out of register()).

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
from . import op_tools
from . import prefs
from . import support


def _pkg():
    return sys.modules[__package__]


def _register_props():
    """Scene properties of every edition (moved out of register())."""
    # Add warning dismissal property
    bpy.types.Scene.orivot_dismissed_bbox_warning = bpy.props.BoolProperty(
        name="Dismissed BBox Warning",
        default=False,
        description="User has seen the default cube bbox warning"
    )
    # UI collapse states
    
    bpy.types.Scene.orivot_show_faces = bpy.props.BoolProperty(
        name="Show Faces",
        default=True,
        description="Show/hide face snap buttons"
    )
    
    bpy.types.Scene.orivot_show_vertices = bpy.props.BoolProperty(
        name="Show Vertices",
        default=False,
        description="Show/hide vertex snap buttons"
    )
    
    bpy.types.Scene.orivot_show_edges = bpy.props.BoolProperty(
        name="Show Edges",
        default=False,
        description="Show/hide edge snap buttons"
    )
    
    bpy.types.Scene.orivot_show_centers = bpy.props.BoolProperty(
        name="Show Centers",
        default=False,
        description="Show/hide center snap buttons"
    )
    
    bpy.types.Scene.orivot_show_global_centers = bpy.props.BoolProperty(
        name="Show Global Centers",
        default=False,
        description="Show/hide global center snap buttons (Geometry, BBox, Mass)"
    )
    # UI Collapse ends here

    bpy.types.Scene.orivot_show_preview = bpy.props.BoolProperty(
        name="Show Origin Preview",
        default=False
    )
    bpy.types.Scene.orivot_preview_color = bpy.props.FloatVectorProperty(
        name="Highlight Color",
        subtype='COLOR',
        default=(1.0, 0.0, 0.0),
        min=0.0,
        max=1.0
    )
    bpy.types.Scene.orivot_preview_alpha = bpy.props.FloatProperty(
        name="Highlight Alpha",
        default=0.35,
        min=0.0,
        max=1.0
    )
    bpy.types.Scene.orivot_snap_source = bpy.props.EnumProperty(
        name="Snap Source",
        items=[
            ('MESH',   "Mesh (Geometry)", "Snap to evaluated mesh geometry extremes"),
            ('BBOX',   "Bounding Box",    "Snap to object bounding box extremes"),
            ('CURSOR', "3D Cursor",       "Move the origin to the 3D Cursor position (ignores geometry)"),
        ],
        default='MESH',
        update=preview.origin_snap_source_update
    )

    # ── Axis Lock ──────────────────────────────────────────────────────────────
    bpy.types.Scene.orivot_lock_x = bpy.props.BoolProperty(
        name="Lock X", default=False,
        description="Freeze X: snaps and offsets never move the origin along X. World X in "
                    "Direct mode and Offset/World; the object's local X in Offset/Local"
    )
    bpy.types.Scene.orivot_lock_y = bpy.props.BoolProperty(
        name="Lock Y", default=False,
        description="Freeze Y: snaps and offsets never move the origin along Y. World Y in "
                    "Direct mode and Offset/World; the object's local Y in Offset/Local"
    )
    bpy.types.Scene.orivot_lock_z = bpy.props.BoolProperty(
        name="Lock Z", default=False,
        description="Freeze Z: snaps and offsets never move the origin along Z. World Z in "
                    "Direct mode and Offset/World; the object's local Z in Offset/Local"
    )

    # ── Numeric Offset ─────────────────────────────────────────────────────────
    bpy.types.Scene.orivot_offset_x = bpy.props.FloatProperty(
        name="X Offset", default=0.0, unit='LENGTH', step=1, precision=4,
        description="World-space X offset — drag to move origin live when Live Offset is enabled",
        update=common._live_offset_update_x
    )
    bpy.types.Scene.orivot_offset_y = bpy.props.FloatProperty(
        name="Y Offset", default=0.0, unit='LENGTH', step=1, precision=4,
        description="World-space Y offset — drag to move origin live when Live Offset is enabled",
        update=common._live_offset_update_y
    )
    bpy.types.Scene.orivot_offset_z = bpy.props.FloatProperty(
        name="Z Offset", default=0.0, unit='LENGTH', step=1, precision=4,
        description="World-space Z offset — drag to move origin live when Live Offset is enabled",
        update=common._live_offset_update_z
    )
    bpy.types.Scene.orivot_live_offset = bpy.props.BoolProperty(
        name="Live Offset",
        default=True,
        description="When enabled, dragging the offset fields moves the origin in real time"
    )
    # Feature 3: object-space offset
    bpy.types.Scene.orivot_offset_space = bpy.props.EnumProperty(
        name="Offset Space",
        items=[
            ('WORLD', "World", "Offset X/Y/Z are in world space"),
            ('LOCAL', "Local", "Offset X/Y/Z are along the object's own local axes"),
        ],
        default='WORLD',
        description="Coordinate space for the numeric offset fields"
    )
    bpy.types.Scene.orivot_copy_mode = bpy.props.EnumProperty(
        name="Copy Mode",
        items=[
            ('WORLD', "World",
             "Copy the absolute world position of the origin. "
             "Pasting places every target object\'s origin at that exact world coordinate"),
            ('DELTA', "Delta",
             "Copy the offset between this object\'s bounding box center and its origin. "
             "Pasting applies the same relative offset to each target object\'s own bbox center"),
        ],
        default='WORLD',
        description="Controls what Copy Origin stores and how Paste Origin applies it"
    )
    bpy.types.Scene.orivot_offset_mode = bpy.props.EnumProperty(
        name="Offset Mode",
        items=[
            ('OFFSET', "Offset",
             "Fields are a delta added on top of the last snap point. "
             "Snap a face, then nudge the origin away from it"),
            ('DIRECT', "Direct",
             "Fields ARE the world position. Drag to place the origin at "
             "exact world coordinates — no geometry snapping required"),
        ],
        default='OFFSET',
        update=common._offset_mode_update,
        description="Controls what the X/Y/Z fields represent"
    )

    # ── Edit Mode + History section visibility ─────────────────────────────────
    # Pro feature section visibility
    bpy.types.Scene.orivot_show_named_groups = bpy.props.BoolProperty(name="Show Named Groups",       default=False)

    # ── Object Snap Tools ─────────────────────────────────────────────────────
    bpy.types.Scene.orivot_obj_snap_source_type = bpy.props.EnumProperty(
        name="Source Snap Type",
        description="Which point on the source object acts as the snap handle",
        items=[
            ('CLOSEST',       "Closest Point",  "Closest surface point on source toward target. "
                                                "Place by Hover: the point that touches the surface under the cursor"),
            ('ORIGIN',        "Origin",          "Source object's origin point"),
            ('BBOX_CENTER',   "BBox Center",     "Center of source object's bounding box"),
            ('VERTEX',        "Closest Vertex",  "Closest vertex on source toward target"),
            ('EDGE_MIDPOINT', "Edge Midpoint",   "Closest edge midpoint on source toward target"),
            ('FACE_CENTER',   "Face Center",     "Closest face center on source toward target"),
        ],
        default='CLOSEST',
    )
    bpy.types.Scene.orivot_obj_snap_target_type = bpy.props.EnumProperty(
        name="Target Snap Type",
        description="Which element on the target object to land on",
        items=[
            ('FACE',          "Surface (Face)", "Snap to nearest surface point on target"),
            ('VERTEX',        "Vertex",         "Snap to nearest vertex on target"),
            ('EDGE_MIDPOINT', "Edge Midpoint",  "Snap to nearest edge midpoint on target"),
            ('FACE_CENTER',   "Face Center",    "Snap to nearest face center on target"),
            ('ORIGIN',        "Object Origin",  "Snap to target object's origin"),
        ],
        default='FACE',
    )
    bpy.types.Scene.orivot_obj_snap_align_rotation = bpy.props.BoolProperty(
        name="Align Rotation to Normal",
        default=False,
        description=(
            "Turn each source object so its local +Z (its up) follows the target surface normal, "
            "keeping its spin, then rest it on the surface"
        )
    )
    bpy.types.Scene.orivot_obj_snap_as_group = bpy.props.BoolProperty(
        name="Snap as Group",
        default=False,
        description=(
            "Move all source objects by the same delta (derived from the first source). "
            "Preserves relative positions between sources — useful for placing assemblies"
        )
    )

    # ── Tier 1/2/3 additions ──────────────────────────────────────────────────
    bpy.types.Scene.orivot_normal_offset = bpy.props.FloatProperty(
        name="Normal Offset",
        default=0.0,
        step=1,
        precision=4,
        unit='LENGTH',
        description=(
            "Offset to apply along the stored snap normal. "
            "Available after any Face, Surface, or Face-Center snap"
        )
    )
    bpy.types.Scene.orivot_show_viewport_handles = bpy.props.BoolProperty(
        name="Show Viewport Handles",
        default=False,
        description="Show snap handles on the active object's bounding box. While on, click a "
                    "handle to move the origin there; Esc or clicking again turns them off",
        update=op_tools._handles_toggle_update,
    )
    bpy.types.Scene.orivot_handles_stay_on = bpy.props.BoolProperty(
        name="Keep Handles On",
        default=False,
        description="Keep the handles on after a snap, to snap several objects in a row. "
                    "Off: they turn off after each snap so the new origin is visible",
    )
    bpy.types.Scene.orivot_handles_snap_type = bpy.props.EnumProperty(
        name="Handle Type",
        items=[
            ('ALL',           "All",          "Show face centers, corners, and edge midpoints"),
            ('FACE_CENTERS',  "Face Centers", "6 face-center dots only"),
            ('CORNERS',       "Corners",      "8 corner dots only"),
            ('EDGE_MIDPOINTS',"Edge Mids",    "12 edge-midpoint dots only"),
            ('BBOX_CENTER',   "BBox Center",  "Single dot at bounding box center"),
        ],
        default='FACE_CENTERS',
        description="Which handle dots to show and snap to"
    )
    bpy.types.Scene.orivot_snap_auto_recalc = bpy.props.BoolProperty(
        name="Auto-Update Preview",  # ← Shorter, clearer name
        default=True,
        description="Automatically refresh the face highlight and arrow when the object or scene changes. Disable for better performance with heavy meshes or large object counts"
    )
    bpy.types.Scene.orivot_keep_preview_persistent = bpy.props.BoolProperty(
        name="Keep Preview Persistent",
        default=False,
        description="Keep face highlight and arrow visible for all selected objects simultaneously, even when switching selection",
        update=preview.keep_persistent_update
    )
    bpy.types.Scene.orivot_preview_orientation = bpy.props.EnumProperty(
        name="Preview Orientation",
        items=[
            ('LOCAL', "Local", "Preview aligned to object's local axes"),
            ('GLOBAL', "Global", "Preview aligned to world axes")
        ],
        default='LOCAL',
        description="Orientation mode for preview highlight and arrow",
        update=preview.origin_preview_orientation_update
    )
    bpy.types.Scene.orivot_arrow_scale = bpy.props.FloatProperty(
        name="Arrow Scale",
        default=0.4,
        min=0.01,
        max=3.0,
        step=1,
        precision=2,
        description="Arrow length as a ratio of the object's bounding box max dimension. "
                    "0.4 = 40% of the largest bbox side. Scales automatically with object size.",
        update=preview.origin_arrow_scale_update
    )
    bpy.types.Scene.orivot_arrow_color = bpy.props.FloatVectorProperty(
        name="Arrow Color",
        subtype='COLOR',
        default=(0.0, 0.0, 0.0),
        min=0.0,
        max=1.0,
        description="Global direction-arrow color used in single-object mode "
                    "(default black). In Multi-Object mode each arrow uses its "
                    "object's quad color.",
        update=preview.origin_arrow_scale_update
    )
    bpy.types.Scene.orivot_arrow_show_stroke = bpy.props.BoolProperty(
        name="Arrow Stroke",
        default=False,
        description="Draw an outline/halo behind the arrows. OFF by default — "
                    "enabling it adds one extra draw call (better performance off)",
        update=preview.origin_arrow_scale_update
    )
    bpy.types.Scene.orivot_arrow_stroke_color = bpy.props.FloatVectorProperty(
        name="Stroke Color",
        subtype='COLOR',
        default=(1.0, 1.0, 1.0),
        min=0.0, max=1.0,
        description="Color of the optional arrow stroke/halo",
        update=preview.origin_arrow_scale_update
    )
    bpy.types.Scene.orivot_arrow_stroke_width = bpy.props.FloatProperty(
        name="Stroke Width",
        default=3.0,
        min=1.0, max=12.0,
        step=10, precision=1,
        description="Thickness of the optional arrow stroke",
        update=preview.origin_arrow_scale_update
    )
    bpy.types.Scene.orivot_arrow_stroke_opacity = bpy.props.FloatProperty(
        name="Stroke Opacity",
        default=0.5,
        min=0.0, max=1.0,
        step=5, precision=2,
        description="Opacity of the optional arrow stroke",
        update=preview.origin_arrow_scale_update
    )
    bpy.types.Scene.orivot_handle_size = bpy.props.FloatProperty(
        name="Handle Size",
        default=8.5,
        min=4.0,
        max=24.0,
        step=0.5,
        precision=1,
        description="Pixel radius of the viewport bbox handle shapes (diamonds, squares, triangles). "
                    "Size is in screen pixels — consistent regardless of zoom or object distance."
    )
    bpy.types.Scene.orivot_face_offset = bpy.props.FloatProperty(
        name="Face Highlight Offset",
        default=0.001,
        min=0.0,
        max=0.1,
        step=0.01,
        precision=3,
        description="Offset the face highlight quad away from the mesh surface to prevent z-fighting. Increase if you see flickering. Range: 0 – 0.1 m",
        update=preview.origin_arrow_scale_update  # Reuse same update callback to refresh preview
    )
    bpy.types.Scene.orivot_auto_show_on_hover = bpy.props.BoolProperty(
        name="Auto-Show Preview on Menu Hover",
        default=True,
        description="Automatically show preview when hovering over addon menus"
    )
    bpy.types.Scene.orivot_show_bbox_wireframe = bpy.props.BoolProperty(
        name="Show BBox Wireframe",
        default=True,
        description="Show wireframe cube for bounding boxes in Multi-Object + BBox mode (both Individual and Combined)"
    )
    # Computed proxy: Multi-Object PREVIEW is derived from the live selection.
    # A get/set proxy means every existing reader gets the correct value while
    # any legacy writes are harmless no-ops — no flag can be mutated from a
    # depsgraph callback, which was the root cause of the instability.
    def _mom_get(self):
        return preview.mom_preview_active(self)

    def _mom_set(self, value):
        # Derived — ignore writes intentionally.
        return None

    bpy.types.Scene.orivot_multi_object_preview = bpy.props.BoolProperty(
        name="Multi-Object Preview",
        description="(Automatic) Active when preview is on and 2+ objects are selected",
        get=_mom_get,
        set=_mom_set,
    )
    bpy.types.Scene.orivot_flip_left_right = bpy.props.BoolProperty(
        name="Flip Left/Right",
        default=False,
        description="Swap the Left and Right labels on snap buttons to match your personal perspective (object-relative vs viewport-relative)",
        update=preview.origin_flip_left_right_update
    )
    bpy.types.Scene.orivot_hide_arrow_when_muted = bpy.props.BoolProperty(
        name="Hide Arrow When Muted",
        default=True,
        description="Hide the arrow when preview is muted"
    )
    bpy.types.Scene.orivot_front_axis = bpy.props.EnumProperty(
        name="Front Face Axis",
        description=(
            "Override which local axis is treated as 'front' for the highlight quad and arrow. "
            "Does not modify the mesh or rotation — only affects the preview visualization. "
            "Use this to homogenize arrow direction across objects with different orientations, "
            "or to match export conventions (e.g. UE5 uses +X as forward)"
        ),
        items=[
            ('LOCAL_Y_POS', "+Y  (Blender Default)",  "Local +Y is front — Blender's default forward axis"),
            ('LOCAL_Y_NEG', "−Y",                     "Local −Y is front"),
            ('LOCAL_X_POS', "+X  (UE5 Default)",      "Local +X is front — matches Unreal Engine's forward axis"),
            ('LOCAL_X_NEG', "−X",                     "Local −X is front"),
            ('LOCAL_Z_POS', "+Z  (Top)",               "Local +Z is front — top face"),
            ('LOCAL_Z_NEG', "−Z  (Bottom)",            "Local −Z is front — bottom face"),
        ],
        default='LOCAL_Y_POS',
        update=preview.origin_preview_orientation_update  # reuse — triggers preview refresh
    )

    # Multi-Object Mode properties
    bpy.types.Scene.orivot_mo_snap_mode = bpy.props.EnumProperty(
        name="Snap Mode",
        items=[
            ('INDIVIDUAL', "Independent Objects", "Each object snaps to its own geometry extreme independently"),
            ('COMBINED', "Combined Group", "All objects snap to the shared extreme of the entire group")
        ],
        default='INDIVIDUAL',
        description="How snapping behaves with multiple objects"
    )
    # NOTE: orivot_multi_object_preview already defined at line 3344 - duplicate removed
    bpy.types.Scene.orivot_mo_affect_target = bpy.props.EnumProperty(
        name="Affect Target",
        items=[
            ('ALL_SELECTED', "All Selected", "Affect all selected objects"),
            ('CUSTOM_OBJECTS', "Custom Objects", "Affect objects from custom list"),
            ('COLLECTION', "Collection", "Affect objects from selected collection")
        ],
        default='ALL_SELECTED',
        description="Which objects to affect when snapping"
    )

    bpy.types.Scene.orivot_mo_custom_objects = bpy.props.CollectionProperty(
        type=prefs.OriginMOCustomObject,
        name="Custom Objects",
        description="List of objects to affect"
    )

    bpy.types.Scene.orivot_mo_target_collection = bpy.props.PointerProperty(
        name="Target Collection",
        type=bpy.types.Collection,
        description="Collection to affect"
    )
    bpy.types.Scene.orivot_mo_global_color = bpy.props.FloatVectorProperty(
        name="Multi-Object Global Color",
        subtype='COLOR',
        default=(1.0, 0.0, 0.0),
        min=0.0,
        max=1.0,
        description="Color to apply to all selected objects in Multi-Object mode"
    )


    # ── Orivot Place Phase 2 scene properties ──────────────────────────────────
    bpy.types.Scene.orivot_align_axis = bpy.props.EnumProperty(
        name="Align Axis",
        description="Local axis that will face the surface normal after Surface Align",
        items=[('+Z',"+Z (Up)",""),('-Z',"−Z (Down)",""),
               ('+Y',"+Y (Forward)",""),('-Y',"−Y (Back)",""),
               ('+X',"+X (Right)",""),('-X',"−X (Left)","")],
        default='+Z',
    )
    bpy.types.Scene.orivot_configs = bpy.props.CollectionProperty(
        type=_configs.OrivotConfig, name="Saved Configurations",
        description="Configurations saved in this .blend (Settings \u203a Saved Configurations)")
    # ── Orivot Place Phase 3 scene properties ──────────────────────────────────
    bpy.types.Scene.orivot_grid_step = bpy.props.FloatProperty(
        name="Grid Step", default=0.25, min=0.001, max=100.0,
        step=1, precision=4, unit='LENGTH',
        description="Grid resolution for Ctrl mode of Surface Snap",
    )
    bpy.types.Scene.orivot_chain_step_x = bpy.props.FloatProperty(
        name="Chain Step X", default=0.0, unit='LENGTH', step=1, precision=4)
    bpy.types.Scene.orivot_chain_step_y = bpy.props.FloatProperty(
        name="Chain Step Y", default=0.0, unit='LENGTH', step=1, precision=4)
    bpy.types.Scene.orivot_chain_step_z = bpy.props.FloatProperty(
        name="Chain Step Z", default=1.0, unit='LENGTH', step=1, precision=4)

    # F6: Viewport mode indicator toggle
    bpy.types.Scene.orivot_show_mode_indicator = bpy.props.BoolProperty(
        name="Show Mode Indicator",
        description="Show a small corner overlay with current snap source and orientation",
        default=False,
    )


def _unregister_props():
    props_to_delete = [
        "orivot_show_preview",
        "orivot_dismissed_bbox_warning",
        "orivot_show_faces",
        "orivot_show_vertices",
        "orivot_show_edges",
        "orivot_show_centers",
        "orivot_show_global_centers",
        "orivot_preview_color",
        "orivot_preview_alpha",
        "orivot_snap_source",
        "orivot_keep_preview_persistent",
        "orivot_arrow_scale",
        "orivot_arrow_color",
        "orivot_arrow_show_stroke",
        "orivot_arrow_stroke_color",
        "orivot_arrow_stroke_width",
        "orivot_arrow_stroke_opacity",
        "orivot_handle_size",
        "orivot_face_offset",
        "orivot_snap_auto_recalc",
        "orivot_auto_show_on_hover",
        "orivot_show_bbox_wireframe",
        "orivot_preview_orientation",
        "orivot_multi_object_preview",
        "orivot_flip_left_right",
        "orivot_hide_arrow_when_muted",
        "orivot_mo_snap_mode",
        "orivot_mo_affect_target",
        "orivot_mo_custom_objects",
        "orivot_mo_target_collection",
        "orivot_mo_global_color",
        "orivot_front_axis",
        "orivot_lock_x",
        "orivot_lock_y",
        "orivot_lock_z",
        "orivot_offset_x",
        "orivot_offset_y",
        "orivot_offset_z",
        "orivot_copy_mode",
        "orivot_live_offset",
        "orivot_offset_mode",
        "orivot_offset_space",
        "orivot_show_named_groups",
        "orivot_obj_snap_source_type",
        "orivot_obj_snap_target_type",
        "orivot_obj_snap_align_rotation",
        "orivot_obj_snap_as_group",
        "orivot_normal_offset",
        "orivot_show_viewport_handles",
        "orivot_handles_stay_on",
        "orivot_handles_snap_type",
        # Orivot Place Phase 2
        "orivot_align_axis",
        "orivot_configs",
        # Orivot Place Phase 3 + v3.1 additions
        "orivot_grid_step",
        "orivot_chain_step_x",
        "orivot_chain_step_y",
        "orivot_chain_step_z",
        "orivot_show_mode_indicator",
    ]

    for prop in props_to_delete:
        try:
            delattr(bpy.types.Scene, prop)
        except Exception as _exc:
            support.note(_exc)


