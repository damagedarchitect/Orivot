bl_info = {
    "name": "Orivot Free",
    "blender": (4, 5, 0),  # tested on 4.5 LTS, 5.0 and 5.2 LTS
    "category": "Object",
    "description": ("Origin snapping to 39 exact points on any mesh: extreme sides, corners, edge midpoints, face centres and geometry / bounding-box / mass centres, plus 3D Cursor, World Zero and an Alt+Q pie menu."),
    "author": "DaMagedArchitect",
    "version": (4, 2, 4),
    "doc_url": "https://discord.com/users/damagedarchitect",
    "tracker_url": "https://discord.com/users/damagedarchitect",
}


import bpy
import csv
import os
import mathutils
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

try:
    from . import core              # exact origin / axis rebasing (no cursor, no bpy.ops)
    from . import meshnp            # vectorised evaluated-mesh queries
    from . import configs as _configs   # Saved Configurations (this file / all files)
    from . import help as _help     # ? buttons: animated in-panel explanations
    from . import ui                # the sidebar: Origin Snaps / Object Snaps / Settings
    from . import migrate           # carries PivotForge data in old files over to Orivot
    from . import gpudraw           # points / wide lines that also show on Vulkan & Metal
    from . import tier              # which edition this build is: Free / Basic / Pro
except ImportError:                 # running as a bare script from the Text Editor
    import core
    import meshnp
    import configs as _configs
    import help as _help
    import ui
    import migrate
    import gpudraw
    import tier

# Edit-mode tools live in their own modules. Each import is guarded on its own, so running
# this file as a bare script (Text Editor) or shipping a build without a module still works.
# axistransform needs linesnap (it rotates / shears about the active stored line); if
# linesnap is missing its import fails too and it is simply skipped.
try:
    from . import linesnap          # Line Snap: vertex snapping to stored guide / constraint lines
except ImportError:
    linesnap = None
try:
    from . import axistransform     # Axis Transform: rotate / shear about a line or X, Y, Z
except ImportError:
    axistransform = None
try:
    from . import chain             # Chain / Distribute (origins or objects in a row)
except ImportError:
    chain = None
try:
    from . import collision         # Collision Preview: live bbox / mesh clash check
except ImportError:
    collision = None
try:
    from . import scenesnap         # Pick Object Origin eyedropper, Snap to Scene Surface
except ImportError:
    scenesnap = None
try:
    from . import curvepath         # Curve Path: origins on a curve (start/mid/end, %, follow along)
except ImportError:
    curvepath = None
try:
    from . import panelscroll       # remembers the sidebar scroll position per mode
except ImportError:
    panelscroll = None
try:
    from . import fab               # Orivot Fab: cut files, nesting, assembly, datums
except ImportError:
    fab = None
try:
    from . import orient            # 4.0: Align Origin Axes + edit-mode 27-point grid
except ImportError:
    orient = None

# ---------------- Constants ----------------
EPS = 1e-9


PREVIEW_ARROW_NAME = "Orivot_Preview_Arrow"
PREVIEW_COLLECTION = "Orivot_Preview_Col"

# Module-level handler reference
_draw_handler_3d = None
_draw_handler_2d = None   # POST_PIXEL for shaped bbox handles
_draw_handler_outliner = None  # POST_PIXEL for per-object front-axis dot in outliner

# Re-entry guard for depsgraph handler
_depsgraph_updating = False

# Track active object name to detect selection changes for front axis reset
_last_active_object_name = None

# ── New in v1.2.0 ────────────────────────────────────────────────────────────

# Origin history: {obj_name: [Vector(world_pos), ...]}  max 5 per object
_origin_history: dict = {}
ORIGIN_HISTORY_MAX = 5

# Copy/Paste clipboard  {'position': Vector, 'front_axis': str, 'snap_source': str}
_origin_clipboard: dict = {}

# Proportional-origin clipboard: normalized position (0..1 per axis) of an
# object's origin within its own local bounding box. Captured from a reference
# object, applied to others so each gets the SAME relative origin placement
# regardless of its size. {'t': Vector} or empty.
_origin_proportion_clipboard: dict = {}

# Module-level cache dictionary for GPU overlay
# quad_local: quad verts in object local space (always)
# obj_name: which object owns the cache
# orientation/front_axis: needed to recompute GLOBAL quads at draw time
_preview_cache = {
    'quad_world': None,
    'quad_local': None,
    'obj_name':   None,
    'orientation': None,
    'front_axis':  None,
    'bbox_local':  None,
}

# Per-object preview storage (when Keep Persistent is enabled)
# Structure: {
#   'custom_color': (r,g,b) or None,     # User's RGB picker override
#   'collection_color': (r,g,b) or None, # From Blender's collection tag
#   'fallback_color': (r,g,b),           # Random default
#   'muted': False,
#   'arrow': object_reference,
#   'quad': [v1, v2, v3, v4]
# }
_persistent_previews = {}

# Timer handle for auto-show
_auto_show_timer = None

# Last confirmed snap target per object in LOCAL space.
# Keyed by object name. Converted world→local at recording time,
# local→world at placement time so the arrow moves with the object.
_last_snap_target = {}

# Last surface normal at snap point per object — used by Normal Offset
# {obj_name: Vector(world-space normal)}
_last_snap_normals: dict = {}

# Hovered handle world position — written by ORIVOT_OT_click_bbox_handle.modal()
# on every MOUSEMOVE, read by draw_handle_shapes_2d() to scale the hovered shape.
# Single-element list so it's mutable from inside class methods without `global`.
_handle_hover_world_pos: list = [None]  # None | Vector

# ── Orivot Place — Phase 1: Snap History ───────────────────────────────────────
_SNAP_HISTORY: list       = []
_SNAP_HISTORY_MAX: int    = 10
_SNAP_HISTORY_IDX: list   = [0]    # mutable container; avoids `global` in methods
_SNAP_RECORDING:  list    = [True]  # set False during history replay / batch ops
                                    # to prevent re-recording while restoring

# ── Orivot Place — Phase 1: Pivot Library ──────────────────────────────────────
_PIVOT_SLOTS: int         = 8
# Key stored ON the object — slot number only, no obj.name in key.
# This means pivots survive object renames.
PIVOT_PROP_KEY: str       = 'orivot_pivot_{}'   # format(slot)


# ── Orivot Place — Phase 1: Collision Preview ──────────────────────────────────
_collision_handler: list  = [None]   # [draw_handler | None]
_collision_active:  list  = [False]  # [bool]

# ── Snap History HUD (F3) ─────────────────────────────────────────────────────
# A small POST_PIXEL overlay shown for ~2 s after Prev/Next navigation.
_history_hud_handler: list = [None]   # [draw_handler | None]
_history_hud_text:    list = [None]   # [str | None]
_history_hud_time:    list = [0.0]    # [float] — time.monotonic() when last set

# ── Viewport Mode Indicator (F6) ──────────────────────────────────────────────
_mode_ind_handler: list = [None]   # [draw_handler | None]

# Surface snap mode state
_surface_snap_active = False
_surface_snap_preview_point = None

# GLOBAL COLOR DEFINITIONS (use everywhere)
COLOR_PRESETS = {
    'RED': {
        'rgb': (0.9, 0.2, 0.2),
        'collection_icon': 'COLLECTION_COLOR_01',
        'colorset_icon': 'COLORSET_01_VEC',
        'name': 'Red'
    },
    'ORANGE': {
        'rgb': (0.95, 0.5, 0.2),
        'collection_icon': 'COLLECTION_COLOR_02',
        'colorset_icon': 'COLORSET_02_VEC',
        'name': 'Orange'
    },
    'YELLOW': {
        'rgb': (0.95, 0.85, 0.2),
        'collection_icon': 'COLLECTION_COLOR_03',
        'colorset_icon': 'COLORSET_03_VEC',
        'name': 'Yellow'
    },
    'GREEN': {
        'rgb': (0.3, 0.8, 0.3),
        'collection_icon': 'COLLECTION_COLOR_04',
        'colorset_icon': 'COLORSET_04_VEC',
        'name': 'Green'
    },
    'BLUE': {
        'rgb': (0.2, 0.4, 0.9),
        'collection_icon': 'COLLECTION_COLOR_05',
        'colorset_icon': 'COLORSET_05_VEC',
        'name': 'Blue'
    },
    'PURPLE': {
        'rgb': (0.7, 0.3, 0.9),
        'collection_icon': 'COLLECTION_COLOR_06',
        'colorset_icon': 'COLORSET_06_VEC',
        'name': 'Purple'
    },
    'PINK': {
        'rgb': (0.9, 0.2, 0.7),
        'collection_icon': 'COLLECTION_COLOR_07',
        'colorset_icon': 'COLORSET_07_VEC',
        'name': 'Pink'
    },
    'BROWN': {
        'rgb': (0.6, 0.4, 0.2),
        'collection_icon': 'COLLECTION_COLOR_08',
        'colorset_icon': 'COLORSET_08_VEC',
        'name': 'Brown'
    },
}

# Blender's native collection color tag mapping
BLENDER_COLLECTION_COLORS = {
    'COLOR_01': (0.9, 0.2, 0.2),    # Red
    'COLOR_02': (0.95, 0.5, 0.2),   # Orange
    'COLOR_03': (0.95, 0.85, 0.2),  # Yellow
    'COLOR_04': (0.3, 0.8, 0.3),    # Green
    'COLOR_05': (0.2, 0.4, 0.9),    # Blue/Cyan
    'COLOR_06': (0.7, 0.3, 0.9),    # Purple
    'COLOR_07': (0.9, 0.2, 0.7),    # Pink/Magenta
    'COLOR_08': (0.6, 0.4, 0.2),    # Brown
}


# ── History helpers ───────────────────────────────────────────────────────────

def _record_history(obj):
    """Push current world origin onto obj's history stack (max 5)."""
    global _origin_history
    pos = obj.matrix_world.translation.copy()
    stack = _origin_history.setdefault(obj.name, [])
    if stack and (stack[-1] - pos).length < 1e-6:
        return
    stack.append(pos)
    if len(stack) > ORIGIN_HISTORY_MAX:
        stack.pop(0)


def _apply_origin(obj, world_pos, context):
    """Move obj's origin to world_pos, geometry fixed. Cursor/selection untouched.

    Routed through core.set_origins: exact for shape keys, children and linked
    duplicates, works from any mode, and never uses the 3D cursor for mesh/curve data.
    Returns the core.Result.
    """
    res = core.set_origins(context, [(obj, Vector(world_pos))])
    # Persist the offset that produced this snap so the user can recall it
    try:
        scene = context.scene
        ox = getattr(scene, 'orivot_offset_x', 0.0)
        oy = getattr(scene, 'orivot_offset_y', 0.0)
        oz = getattr(scene, 'orivot_offset_z', 0.0)
        if abs(ox) > 1e-9 or abs(oy) > 1e-9 or abs(oz) > 1e-9:
            obj['orivot_last_offset_x'] = ox
            obj['orivot_last_offset_y'] = oy
            obj['orivot_last_offset_z'] = oz
    except Exception:
        pass
    # Auto-record every successful snap into Orivot Place Snap History
    try:
        push_snap_history(obj.name, Vector(world_pos))
    except Exception:
        pass
    return res


def _apply_origins_batch(context, pairs):
    """Batch form of _apply_origin for many objects: one pass, one depsgraph update."""
    res = core.set_origins(context, pairs)
    for obj, pos in pairs:
        try:
            push_snap_history(obj.name, Vector(pos))
        except Exception:
            pass
    return res


def _set_origin_world_fast(obj, world_pos, context=None):
    """Move obj's origin to world_pos with no bpy.ops and a single undo step.

    Used by the live offset drag path (property update callback), so it must not call
    operators for mesh data. core.set_origins keeps shape keys, children and linked
    duplicates in place (the pre-4.0 shortcut corrupted all three).
    """
    if getattr(obj, "mode", 'OBJECT') != 'OBJECT':
        return None     # never switch modes (an operator) from a property callback
    return core.set_origins(context or bpy.context, [(obj, Vector(world_pos))])


def _apply_lock_and_offset(obj, target, scene, frame_obj=None):
    """Apply Freeze Axis + numeric offset to a world-space target.

    A frozen axis ALWAYS wins: the origin keeps its current coordinate on that axis, in
    both Offset and Direct mode, and an offset typed on a frozen axis is ignored.
    (Up to 4.0.x Offset mode froze the snap but still added the offset on a frozen
    axis, and the live drag ignored Freeze Axis and Local space altogether.)

    Direct: fields are absolute world coordinates (handled by the live drag), so a snap
            only applies the world freeze.
    Offset: fields are a delta in World or Local space; the freeze uses the same space,
            so in Local space Freeze X keeps the object's local-X position.
    """
    return target



def _live_offset_update(self, context):
    """Called whenever an offset field changes — moves origin live.

    Two modes controlled by orivot_offset_mode:
      OFFSET  — fields are a delta added on top of the last snap base position.
      DIRECT  — fields ARE the world position. Drag to place origin anywhere.
    """
    scene = context.scene
    obj   = context.active_object
    if not obj or obj.type != 'MESH':
        return
    if not getattr(scene, 'orivot_live_offset', False):
        return

    mode = getattr(scene, 'orivot_offset_mode', 'OFFSET')

    if mode == 'DIRECT':
        # Fields = absolute world X Y Z.  Lock axes freeze that axis to current position.
        cur = obj.matrix_world.translation.copy()
        target = Vector((
            cur.x if scene.orivot_lock_x else scene.orivot_offset_x,
            cur.y if scene.orivot_lock_y else scene.orivot_offset_y,
            cur.z if scene.orivot_lock_z else scene.orivot_offset_z,
        ))
    else:
        # OFFSET mode — fields are delta from last snap base
        base_key = '_orivot_offset_base'
        base = scene.get(base_key)
        if base is None:
            base = list(obj.matrix_world.translation)
            scene[base_key] = base
        # base + offset in the chosen space, frozen axes held (same rule as a snap)
        target = _apply_lock_and_offset(obj, Vector(base), scene)

    # Live drag: use the no-op setter so the whole drag is ONE undo step and no
    # operator runs inside this property callback.
    _set_origin_world_fast(obj, target, context)
    _last_snap_target[obj.name] = Vector((0, 0, 0))

    if scene.orivot_show_preview:
        try:
            create_or_update_preview(obj)
        except Exception:
            pass  # intentional: try:


def _live_offset_update_x(self, context):
    if not context.scene.get('_orivot_suppress_offset_update'):
        _live_offset_update(self, context)
def _live_offset_update_y(self, context):
    if not context.scene.get('_orivot_suppress_offset_update'):
        _live_offset_update(self, context)
def _live_offset_update_z(self, context):
    if not context.scene.get('_orivot_suppress_offset_update'):
        _live_offset_update(self, context)


def _offset_mode_update(self, context):
    """When switching to DIRECT mode, load current origin into the fields.
    When switching to OFFSET mode, reset fields to zero."""
    scene = context.scene
    obj   = context.active_object
    if not obj or obj.type != 'MESH':
        return
    if scene.orivot_offset_mode == 'DIRECT':
        # Populate fields with current world origin — ready to nudge
        pos = obj.matrix_world.translation
        scene['_orivot_offset_base'] = None  # clear offset base
        # Suppress the update callback while we set values
        scene['_orivot_suppress_offset_update'] = True
        scene.orivot_offset_x = round(pos.x, 6)
        scene.orivot_offset_y = round(pos.y, 6)
        scene.orivot_offset_z = round(pos.z, 6)
        scene['_orivot_suppress_offset_update'] = False
    else:
        # Back to OFFSET — reset fields to zero, stash current position as base
        pos = obj.matrix_world.translation
        scene['_orivot_offset_base'] = list(pos)
        scene['_orivot_suppress_offset_update'] = True
        scene.orivot_offset_x = 0.0
        scene.orivot_offset_y = 0.0
        scene.orivot_offset_z = 0.0
        scene['_orivot_suppress_offset_update'] = False

# ---------------- Utilities (evaluated mesh + bbox) ----------------
def get_evaluated_mesh(obj):
    """Return (obj_eval, mesh) for evaluated object (modifiers applied).
    Forces a view_layer update so the depsgraph is never stale after origin_set calls.
    Raises RuntimeError if mesh cannot be evaluated (caller should treat as no geometry).
    """
    ctx = bpy.context
    # Ensure depsgraph is up to date — critical after origin_set dirtied the graph
    try:
        ctx.view_layer.update()
    except Exception:
        pass  # intentional: try:
    depsgraph = ctx.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
    if mesh is None:
        raise RuntimeError(f"to_mesh() returned None for '{obj.name}'")
    if len(mesh.vertices) == 0:
        obj_eval.to_mesh_clear()
        raise RuntimeError(f"Mesh '{obj.name}' has no vertices after evaluation")
    return obj_eval, mesh


def get_bbox_local(obj):
    """Return list of 8 corner Vectors in object local space (from bound_box)."""
    return [Vector(corner) for corner in obj.bound_box]


# Object types whose bound_box describes real geometry extents. Everything else
# (empties, lights, cameras, speakers, lattices) has no meaningful volume, so we
# treat its origin point as its only contributing location.
GEOMETRY_TYPES = {
    'MESH', 'CURVE', 'SURFACE', 'META', 'FONT',
    'CURVES', 'POINTCLOUD', 'VOLUME', 'GPENCIL', 'GREASEPENCIL',
}


VALID_FRONT_AXES = {
    'LOCAL_Y_POS', 'LOCAL_Y_NEG',
    'LOCAL_X_POS', 'LOCAL_X_NEG',
    'LOCAL_Z_POS', 'LOCAL_Z_NEG',
}

def get_obj_front_axis(obj, scene=None):
    """
    Return the committed front axis for obj if one exists,
    otherwise +Y (Blender default). Does NOT fall back to scene setting —
    that's intentional to avoid circular reads when syncing the dropdown.
    """
    val = obj.get('orivot_front_axis') if obj else None
    if val in VALID_FRONT_AXES:
        return val
    return 'LOCAL_Y_POS'




def local_to_world(obj, v_local):
    """Local -> world using object's matrix_world."""
    return obj.matrix_world @ Vector(v_local)


def avg_vec(vecs):
    if not vecs:
        return Vector((0.0, 0.0, 0.0))
    s = Vector((0.0, 0.0, 0.0))
    for v in vecs:
        s += v
    return s / len(vecs)


def edge_midpoint_extreme(obj, axis1, extreme1, axis2, extreme2):
    """World-space mean of the vertices at the intersection of two LOCAL-axis
    extremes (e.g. Z max & X max = top-right edge midpoint). None if empty."""
    return meshnp.edge_midpoint_extreme(obj, axis1, extreme1, axis2, extreme2)

def polygon_area_from_world_coords(world_vs):
    """Area of polygon from world-space vertex list (triangulate fan)."""
    if len(world_vs) < 3:
        return 0.0
    area = 0.0
    v0 = world_vs[0]
    for i in range(1, len(world_vs) - 1):
        a = world_vs[i] - v0
        b = world_vs[i + 1] - v0
        area += a.cross(b).length / 2.0
    return area


# ---------------- Geometry-driven face centroid helpers (local-axis aware) ----------------
def face_centroid_extreme(obj, axis, extreme='max'):
    """Area-weighted world centroid of polygons whose vertices all lie at the extreme
    along a LOCAL axis (vectorised; falls back to the extreme vertex layer)."""
    return meshnp.face_centroid_extreme(obj, axis, extreme)

# ---------------- Multi-Object Combined Extremes ----------------
def get_combined_face_centroid(objects, axis, extreme='max', source='MESH'):
    """
    Calculate area-weighted face centroid across ALL objects' combined mesh in WORLD space.
    """
    if source == 'MESH':
        return meshnp.combined_face_centroid(objects, axis, extreme)
    # STEP 1: Find the GLOBAL extreme value across all objects in WORLD coordinates
    global_extreme_val = None

    # We'll also collect per-object world verts/polygons to reuse later
    obj_world_data = []

    for obj in objects:
        if obj.type != 'MESH':
            continue

        if source == 'MESH':
            try:
                obj_eval, mesh = get_evaluated_mesh(obj)
                try:
                    mw = obj_eval.matrix_world
                    # world-space coords for verts
                    verts_world = [mw @ v.co for v in mesh.vertices]
                    polys = list(mesh.polygons)
                    if not verts_world or not polys:
                        continue

                    # Get extreme in world space
                    if axis == 'X':
                        obj_extreme = max(v.x for v in verts_world) if extreme == 'max' else min(v.x for v in verts_world)
                    elif axis == 'Y':
                        obj_extreme = max(v.y for v in verts_world) if extreme == 'max' else min(v.y for v in verts_world)
                    else:  # 'Z'
                        obj_extreme = max(v.z for v in verts_world) if extreme == 'max' else min(v.z for v in verts_world)

                    # Update global extreme
                    if global_extreme_val is None:
                        global_extreme_val = obj_extreme
                    else:
                        global_extreme_val = max(global_extreme_val, obj_extreme) if extreme == 'max' else min(global_extreme_val, obj_extreme)

                    obj_world_data.append((obj_eval, mesh, verts_world, polys, mw))
                finally:
                    # do NOT clear here – we'll release later after we use meshes in step 2
                    pass
            except Exception as e:
                print(f"[Origin Snap] Error processing object {obj.name}: {e}")
                continue
        else:
            # BBox source: use bbox corners converted to world space
            try:
                bbox_local = get_bbox_local(obj)
                bbox_world = [obj.matrix_world @ v for v in bbox_local]
                if not bbox_world:
                    continue
                if axis == 'X':
                    obj_extreme = max(v.x for v in bbox_world) if extreme == 'max' else min(v.x for v in bbox_world)
                elif axis == 'Y':
                    obj_extreme = max(v.y for v in bbox_world) if extreme == 'max' else min(v.y for v in bbox_world)
                else:
                    obj_extreme = max(v.z for v in bbox_world) if extreme == 'max' else min(v.z for v in bbox_world)

                if global_extreme_val is None:
                    global_extreme_val = obj_extreme
                else:
                    global_extreme_val = max(global_extreme_val, obj_extreme) if extreme == 'max' else min(global_extreme_val, obj_extreme)

                # For BBOX source emulate simple rectangular faces using bbox_world as polys
                obj_world_data.append((None, None, bbox_world, None, obj.matrix_world))
            except Exception as e:
                print(f"[Origin Snap] Error processing bbox for {obj.name}: {e}")
                continue

    if global_extreme_val is None:
        # nothing found
        # release any evaluated meshes we kept open
        for d in obj_world_data:
            obj_eval = d[0]
            mesh = d[1]
            if obj_eval and mesh:
                try:
                    obj_eval.to_mesh_clear()
                except Exception:
                    pass  # intentional: try:
        return None

    # STEP 2: Now collect faces that lie at this GLOBAL extreme (use world-space)
    total_area = 0.0
    weighted_centroid = Vector((0.0, 0.0, 0.0))
    fallback_verts = []  # Collect all extreme vertices as fallback

    for item in obj_world_data:
        obj_eval, mesh, verts_world, polys, mw = item
        try:
            if mesh and polys:
                # compute tolerance in world space based on object extents
                xs = [v.x for v in verts_world]
                ys = [v.y for v in verts_world]
                zs = [v.z for v in verts_world]
                if axis == 'X':
                    tol_basis = max(max(ys) - min(ys), max(zs) - min(zs), 1e-6)
                elif axis == 'Y':
                    tol_basis = max(max(xs) - min(xs), max(zs) - min(zs), 1e-6)
                else:
                    tol_basis = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
                tol = tol_basis * 1e-3 + 1e-6

                # Collect vertices at extreme for fallback
                for v in verts_world:
                    val = v.x if axis == 'X' else (v.y if axis == 'Y' else v.z)
                    if abs(val - global_extreme_val) < tol:
                        fallback_verts.append(v)

                for poly in polys:
                    poly_world_vs = [verts_world[i] for i in poly.vertices]
                    all_at_extreme = True
                    for wv in poly_world_vs:
                        val = wv.x if axis == 'X' else (wv.y if axis == 'Y' else wv.z)
                        if abs(val - global_extreme_val) > tol:
                            all_at_extreme = False
                            break
                    if not all_at_extreme:
                        continue

                    area = polygon_area_from_world_coords(poly_world_vs)
                    if area <= EPS:
                        area = 1.0
                    center = avg_vec(poly_world_vs)
                    weighted_centroid += center * area
                    total_area += area
            else:
                # bbox-only fallback (treat bbox corners as a fake face layer)
                if verts_world:
                    # pick verts close to global extreme
                    if axis == 'X':
                        layer_vs = [v for v in verts_world if abs(v.x - global_extreme_val) < 1e-5]
                    elif axis == 'Y':
                        layer_vs = [v for v in verts_world if abs(v.y - global_extreme_val) < 1e-5]
                    else:
                        layer_vs = [v for v in verts_world if abs(v.z - global_extreme_val) < 1e-5]

                    if layer_vs:
                        fallback_verts.extend(layer_vs)
                        center = avg_vec(layer_vs)
                        weighted_centroid += center * 1.0
                        total_area += 1.0
        except Exception as e:
            print(f"[Origin Snap] Error calculating centroid: {e}")
            continue
        finally:
            # release evaluated mesh if any
            if obj_eval and mesh:
                try:
                    obj_eval.to_mesh_clear()
                except Exception:
                    pass  # intentional: try:

    if total_area > 0.0:
        return weighted_centroid / total_area

    # FALLBACK: If no faces found, use average of extreme vertices
    if fallback_verts:
        return avg_vec(fallback_verts)

    return None

# ---------------- Closest vertex helper (local-space based) ----------------
# ---------------- Cleanup orphaned previews ----------------
def cleanup_deleted_objects():
    """Remove previews for objects no longer in the scene AND re-key renamed objects.

    Two cases handled:
    1. DELETED: key is not in bpy.data.objects at all -> evict from cache.
    2. RENAMED: a cached object still exists but its name changed. Blender renames
       the object in-place, so obj.name differs from the cache key. We re-key the
       cache entry to the new name so the draw handler still finds it.
       Without this, renaming an object while preview is on produces a ghost quad
       that never clears.
    """
    global _persistent_previews

    valid_names = {obj.name for obj in bpy.data.objects if obj.type == 'MESH'}
    orphaned = []
    renames  = {}  # old_key -> new_key

    for key in list(_persistent_previews.keys()):
        if key in valid_names:
            continue
        # May be a rename: if an object with this key still physically exists
        # but Blender already updated its .name, the stashed _obj_ref will
        # reveal the new name.
        obj_ref = _persistent_previews[key].get('_obj_ref')
        if obj_ref is not None:
            try:
                new_name = obj_ref.name  # ReferenceError if deleted
                if new_name != key and new_name in valid_names:
                    renames[key] = new_name
                    continue
            except ReferenceError:
                pass
        orphaned.append(key)

    for old_key, new_key in renames.items():
        _persistent_previews[new_key] = _persistent_previews.pop(old_key)

    for obj_name in orphaned:
        data = _persistent_previews.pop(obj_name, {})
        arrow = data.get('arrow')
        if arrow:
            try:
                if arrow.name in bpy.data.objects:
                    for col in list(arrow.users_collection):
                        try:
                            col.objects.unlink(arrow)
                        except Exception:
                            pass
                    try:
                        bpy.data.objects.remove(arrow, do_unlink=True)
                    except Exception:
                        pass
            except ReferenceError:
                pass

    return bool(orphaned) or bool(renames)


# ── Deferred cleanup (NEVER mutate blend data from a draw or depsgraph handler) ──
# Removing objects from a POST_VIEW draw callback can corrupt state or crash
# Blender. cleanup_deleted_objects() therefore must only ever run from a timer,
# which executes in a context where bpy.data mutation is safe.
_cleanup_scheduled = False


def _tag_view3d_redraw():
    """Tag all 3D viewports for redraw (robust to a missing context.screen)."""
    try:
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        pass


def _deferred_cleanup():
    """Timer callback: run orphan-preview cleanup in a data-safe context."""
    global _cleanup_scheduled
    _cleanup_scheduled = False
    try:
        if cleanup_deleted_objects():
            _tag_view3d_redraw()
    except Exception as e:
        print(f"[Orivot] deferred cleanup failed: {e}")
    return None  # one-shot


def schedule_cleanup():
    """Request a deferred cleanup. Coalesces many requests into a single timer,
    so calling this every draw frame costs at most one pending timer."""
    global _cleanup_scheduled
    if _cleanup_scheduled:
        return
    _cleanup_scheduled = True
    try:
        bpy.app.timers.register(_deferred_cleanup, first_interval=0.0)
    except Exception:
        _cleanup_scheduled = False

def remove_preview_objects():
    """Clear preview state. GPU-drawn arrows need no bpy.data cleanup.
    Also sweeps for any legacy SINGLE_ARROW empties left by older versions."""
    global _preview_cache, _persistent_previews

    _preview_cache.clear()
    _persistent_previews.clear()

    # Sweep for legacy empties (from versions before GPU-drawn arrows)
    legacy = [o for o in bpy.data.objects
              if o.name.startswith(PREVIEW_ARROW_NAME)]
    for o in legacy:
        for col in list(o.users_collection):
            try: col.objects.unlink(o)
            except Exception: pass
        try: bpy.data.objects.remove(o, do_unlink=True)
        except Exception: pass

    # Remove the preview collection if it exists and is now empty
    col = bpy.data.collections.get(PREVIEW_COLLECTION)
    if col:
        if len(col.objects) == 0:
            try: bpy.context.scene.collection.children.unlink(col)
            except Exception: pass
            try: bpy.data.collections.remove(col)
            except Exception: pass


# ---------------- GPU draw handler ----------------
_BBOX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
               (0, 4), (1, 5), (2, 6), (3, 7))


def draw_handle_shapes_2d():
    """POST_PIXEL callback: draw shaped, colored, outlined bbox handles in screen space.

    Runs in 2D screen space so handle shapes are a FIXED PIXEL SIZE regardless of
    zoom level or object distance — matching the legibility of Blender's own gizmos.

    Shape ↔ handle type:
      Diamond  (orange) → bbox corners   (8 handles)
      Square   (red)    → edge midpoints (12 handles)
      Triangle (blue)   → face centers   (6 handles)
      Circle   (yellow) → bbox center    (1 handle, only in BBOX_CENTER mode)
    """
    return


def draw_overlay_3d():
    """POST_VIEW draw: translucent quad(s) with depth awareness.

    Quads are stored in local space and transformed to world every frame
    using the object's current matrix_world — so they follow object movement,
    rotation, and scale correctly without needing a depsgraph update trigger.
    """
    return

def mom_preview_active(scene=None):
    """Derived state — Multi-Object PREVIEW is active when the preview is ON and
    2+ geometry objects are selected.

    This is intentionally NOT a stored toggle. Computing it from the live
    selection means it can never be mutated from a depsgraph callback and can
    never fight the user. It is fully independent of 'Keep Persistent'.
    """
    if scene is None:
        scene = bpy.context.scene
    if not getattr(scene, 'orivot_show_preview', False):
        return False
    try:
        sel = [o for o in bpy.context.selected_objects if o.type in GEOMETRY_TYPES]
        return len(sel) >= 2
    except Exception:
        return False


# ---------------- Preview management (cache + handlers) ----------------
def draw_outliner_axis_indicators():
    """POST_PIXEL callback on the Outliner: draw a small coloured dot next to
    each object whose committed front-axis is non-default.

    The dot colour matches the axis: +Y (default) → grey (suppressed), -Y → cyan,
    +Z → green, -Z → magenta, +X → orange, -X → blue.  A grey dot would clutter
    the outliner, so objects using the Blender-default LOCAL_Y_POS get nothing.

    The callback is very cheap: it only fires when the Outliner is redrawn
    (user scrolling, scene change) and does a single font.draw() per marked object
    rather than geometry batches.
    """
    try:
        import blf
        ctx = bpy.context
        if ctx is None:
            return
        # Only run when objects carry the custom prop
        marked = {}
        for obj in bpy.data.objects:
            fa = obj.get('orivot_front_axis', 'LOCAL_Y_POS')
            if fa and fa != 'LOCAL_Y_POS':
                marked[obj.name] = fa

        if not marked:
            return

        AXIS_COLORS = {
            'LOCAL_Y_NEG': (0.2, 0.9, 0.9, 1.0),   # cyan
            'LOCAL_Z_POS': (0.4, 0.9, 0.2, 1.0),   # green
            'LOCAL_Z_NEG': (0.9, 0.2, 0.8, 1.0),   # magenta
            'LOCAL_X_POS': (1.0, 0.55, 0.1, 1.0),  # orange
            'LOCAL_X_NEG': (0.2, 0.5,  1.0, 1.0),  # blue
        }
        AXIS_LABELS = {
            'LOCAL_Y_NEG': '−Y', 'LOCAL_Z_POS': '+Z', 'LOCAL_Z_NEG': '−Z',
            'LOCAL_X_POS': '+X', 'LOCAL_X_NEG': '−X',
        }

        region = ctx.region
        if not region or region.width < 10:
            return

        font_id = 0
        blf.size(font_id, 10)
        x_pos = region.width - 28  # right-aligned, inside the outliner column

        # Walk the visible tree — we can only approximate row positions without
        # direct outliner RNA access, so we draw a legend stripe at top-right instead,
        # listing non-default objects: name  axis-label  coloured dot.
        y = region.height - 22
        for name, fa in list(marked.items()):
            if y < 8:
                break
            color = AXIS_COLORS.get(fa, (0.8, 0.8, 0.8, 1.0))
            label = AXIS_LABELS.get(fa, fa[-1])
            blf.color(font_id, *color)
            blf.position(font_id, x_pos, y, 0)
            blf.draw(font_id, label)
            y -= 14
    except Exception:
        pass  # never crash the outliner


def ensure_handle_draw():
    """The bbox handle shapes (POST_PIXEL) belong to Handles, not to Preview.

    Up to 4.1.0 this hook was only installed through ensure_handlers(), i.e. when
    Preview was on: with Preview off, Handles started the click tool but drew nothing.
    """
    global _draw_handler_2d
    if _draw_handler_2d is None:
        _draw_handler_2d = bpy.types.SpaceView3D.draw_handler_add(
            draw_handle_shapes_2d, (), 'WINDOW', 'POST_PIXEL')


def ensure_handlers():
    global _draw_handler_3d, _draw_handler_2d, _draw_handler_outliner
    if _draw_handler_3d is None:
        _draw_handler_3d = bpy.types.SpaceView3D.draw_handler_add(
            draw_overlay_3d, (), 'WINDOW', 'POST_VIEW')
    if _draw_handler_2d is None:
        _draw_handler_2d = bpy.types.SpaceView3D.draw_handler_add(
            draw_handle_shapes_2d, (), 'WINDOW', 'POST_PIXEL')
    if _draw_handler_outliner is None:
        _draw_handler_outliner = bpy.types.SpaceOutliner.draw_handler_add(
            draw_outliner_axis_indicators, (), 'WINDOW', 'POST_PIXEL')


def remove_handlers():
    global _draw_handler_3d, _draw_handler_2d, _draw_handler_outliner
    if _draw_handler_3d is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_draw_handler_3d, 'WINDOW')
        except Exception:
            pass
        _draw_handler_3d = None
    if _draw_handler_2d is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_draw_handler_2d, 'WINDOW')
        except Exception:
            pass
        _draw_handler_2d = None
    if _draw_handler_outliner is not None:
        try:
            bpy.types.SpaceOutliner.draw_handler_remove(_draw_handler_outliner, 'WINDOW')
        except Exception:
            pass
        _draw_handler_outliner = None

def create_or_update_preview(obj):
    """Create or update preview plane (GPU) and arrow (mesh empty) to match active object."""
    return

# ---------------- Depsgraph Handler ----------------
def _sync_active_ui():
    """Bring scene-level UI fields in line with the active object (runs from a timer).

    * Front Face Axis dropdown  -> the object's committed axis
    * Direct-mode offset fields -> the object's current origin
    """
    global _active_sync_scheduled
    _active_sync_scheduled = False
    try:
        ctx = bpy.context
        scene = ctx.scene
        obj = ctx.view_layer.objects.active if ctx.view_layer else None
        committed = get_obj_front_axis(obj, scene) if obj else 'LOCAL_Y_POS'
        if scene.orivot_front_axis != committed:
            scene.orivot_front_axis = committed
        if obj and obj.type == 'MESH' and \
                getattr(scene, 'orivot_offset_mode', 'OFFSET') == 'DIRECT':
            pos = obj.matrix_world.translation
            vals = (round(pos.x, 6), round(pos.y, 6), round(pos.z, 6))
            if (scene.orivot_offset_x, scene.orivot_offset_y, scene.orivot_offset_z) != vals:
                scene['_orivot_suppress_offset_update'] = True
                try:
                    scene.orivot_offset_x, scene.orivot_offset_y, scene.orivot_offset_z = vals
                finally:
                    scene['_orivot_suppress_offset_update'] = False
    except Exception as e:
        print(f"[Orivot] active-object UI sync failed: {e}")
    return None


_active_sync_scheduled = False


def _schedule_active_ui_sync():
    global _active_sync_scheduled
    if _active_sync_scheduled:
        return
    _active_sync_scheduled = True
    try:
        bpy.app.timers.register(_sync_active_ui, first_interval=0.0)
    except Exception:
        _active_sync_scheduled = False


@persistent
def depsgraph_update_handler(scene, depsgraph):
    """Update preview dynamically when scene changes."""
    global _depsgraph_updating
    global _last_active_object_name
    global _preview_cache, _persistent_previews

    if _depsgraph_updating:
        return

    preview_on = False

    # ── Preview turned OFF ────────────────────────────────────────────────────
    # The draw handler already early-exits, hiding the GPU quad. But arrow mesh
    # objects persist in bpy.data until we clean them here. Do it once, cheaply,
    # by checking whether any arrows still exist.
    if not preview_on:
        if _preview_cache or _persistent_previews:
            _preview_cache.clear()
            _persistent_previews.clear()
            schedule_cleanup()   # deferred bpy.data removal — safe from here
        return

    # ── Preview ON from here ──────────────────────────────────────────────────
    ensure_handlers()

    # NOTE: Multi-Object PREVIEW is now a DERIVED state (see mom_preview_active).
    # We deliberately do NOT mutate orivot_multi_object_preview or
    # orivot_keep_preview_persistent here. Writing scene properties from inside a
    # depsgraph callback re-enters the handler and fires their update callbacks,
    # which was the root cause of the preview/arrow/colour instability.

    obj = bpy.context.active_object

    current_name = obj.name if obj else None
    if current_name != _last_active_object_name:
        _last_active_object_name = current_name
        # Syncing the Front Axis dropdown / Direct-mode offset fields WRITES scene
        # properties. Doing that inside depsgraph_update_post re-enters the depsgraph
        # and fires their update callbacks, so it is deferred to a one-shot timer.
        _schedule_active_ui_sync()
        # Stamp cache immediately so draw handler shows the new object
        if obj and obj.type in GEOMETRY_TYPES:
            _preview_cache['obj_name']    = current_name
            _preview_cache['front_axis']  = get_obj_front_axis(obj, scene)
            _preview_cache['orientation'] = getattr(
                scene, 'orivot_preview_orientation', 'LOCAL')

    # Auto-enable MO mode on shift-select is no longer needed — multi-object
    # preview is derived from the live selection (mom_preview_active).

    if not obj or obj.type not in GEOMETRY_TYPES:
        if not getattr(scene, "orivot_keep_preview_persistent", False):
            # Cache-only clear: no bpy.data mutation (and no O(N) name sweep) from
            # inside a depsgraph handler. Legacy arrow empties are swept on load.
            _preview_cache.clear()
            _persistent_previews.clear()
        return

    if not getattr(scene, "orivot_snap_auto_recalc", True):
        return

    _depsgraph_updating = True
    try:
        create_or_update_preview(obj)
        # Derived Multi-Object mode: build per-object preview data for the rest of
        # the selection. The draw handler recomputes world position from
        # matrix_world every frame, so transforms/camera moves need NO rebuild.
        # We therefore only (re)build an object when it has no cached local data
        # yet, or when its GEOMETRY actually changed this tick. This is what keeps
        # large multi-selections from rebuilding all N objects every frame.
        if mom_preview_active(scene):
            geo_changed = set()
            try:
                for upd in depsgraph.updates:
                    idd = getattr(upd, 'id', None)
                    if isinstance(idd, bpy.types.Object) and getattr(upd, 'is_updated_geometry', False):
                        geo_changed.add(idd.name)
            except Exception:
                pass
            for o in bpy.context.selected_objects:
                if o is obj or o.type not in GEOMETRY_TYPES:
                    continue
                cached = _persistent_previews.get(o.name)
                needs_build = (
                    cached is None
                    or 'quad_local' not in cached
                    or o.name in geo_changed
                )
                if needs_build:
                    try:
                        create_or_update_preview(o)
                    except Exception as e:
                        print(f"[Orivot] multi preview build failed for '{o.name}': {e}")
    except Exception as e:
        print(f"[Orivot] depsgraph update failed: {e}")
    finally:
        _depsgraph_updating = False

@persistent
def collection_color_change_detector(scene, depsgraph):
    """
    Auto-sync when Blender's collection colors change in Properties Panel.
    Only updates objects that DON'T have custom color overrides.
    Fires whenever MO preview is active (derived state — no stored flag needed).
    """
    global _persistent_previews

    # Only run when multi-object preview is actually visible
    if not mom_preview_active(scene):
        return

    try:
        updated_count = 0

        # Only objects that actually have a preview entry can change colour —
        # iterate those instead of every object in the file on every tick.
        for obj_name in list(_persistent_previews.keys()):
            obj = bpy.data.objects.get(obj_name)
            if obj is None or obj.type != 'MESH':
                continue

            # Skip if object has CUSTOM color override
            custom = _persistent_previews[obj_name].get('custom_color')
            if custom is not None:
                continue

            # Get collection color
            primary_collection = None
            for col in obj.users_collection:
                if col.name != "Scene Collection" and col != scene.collection:
                    primary_collection = col
                    break

            if not primary_collection:
                continue

            if not hasattr(primary_collection, 'color_tag') or primary_collection.color_tag == 'NONE':
                continue

            # Get Blender's color
            blender_color = BLENDER_COLLECTION_COLORS.get(primary_collection.color_tag)
            if not blender_color:
                continue

            # Check if color changed
            cached_color = _persistent_previews[obj_name].get('collection_color')

            if cached_color != blender_color:
                # Update collection color
                _persistent_previews[obj_name]['collection_color'] = blender_color

                # Update preview if visible
                if scene.orivot_show_preview:
                    try:
                        create_or_update_preview(obj)
                    except Exception:
                        pass  # intentional: try:

                updated_count += 1

        if updated_count > 0:
            _tag_view3d_redraw()

    except Exception:
        pass  # Silently fail

# ---------------- Callbacks for property updates ----------------
def keep_persistent_update(self, context):
    """Callback when Keep Persistent is toggled. Independent of Multi-Object mode."""
    scene = context.scene

    if not self.orivot_keep_preview_persistent:
        # Toggled OFF - remove persisted (non-selected) previews
        remove_preview_objects()
    # Redraw either way
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()

def origin_snap_source_update(self, context):
    """Update callback: if preview is on, refresh it when snap source changes."""
    scene = context.scene
    if scene.orivot_show_preview:
        obj = context.active_object
        if obj and obj.type == 'MESH':
            try:
                create_or_update_preview(obj)
            except Exception:
                pass  # intentional: try:


def origin_arrow_scale_update(self, context):
    """Update callback: refresh preview when arrow scale changes."""
    scene = context.scene
    if scene.orivot_show_preview:
        obj = context.active_object
        if obj and obj.type == 'MESH':
            try:
                create_or_update_preview(obj)
            except Exception:
                pass  # intentional: try:


def origin_flip_left_right_update(self, context):
    """Update callback: force UI redraw when flip toggle changes."""
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def origin_preview_orientation_update(self, context):
    """Update callback: refresh preview when orientation changes."""
    scene = context.scene
    if scene.orivot_show_preview:
        obj = context.active_object
        if obj and obj.type == 'MESH':
            try:
                create_or_update_preview(obj)
            except Exception:
                pass  # intentional: try:

# ---------------- Multi-Object Target Selection ----------------
def _any_affected_mesh(context):
    """Something the Snap Points / Cursor buttons can act on (selection, list or collection)."""
    try:
        return any(o.type == 'MESH' for o in get_affected_objects(context))
    except Exception:
        return False


def get_affected_objects(context):
    """Return list of objects to be affected based on current settings.

    MMO auto-activates:
    - ALL_SELECTED: activates automatically when multiple meshes are selected —
      no preview toggle required.
    - CUSTOM_OBJECTS / COLLECTION: always uses those scopes regardless of
      selection count or preview state.
    Preview mode is no longer required to activate multi-object operation.
    """
    scene = context.scene
    # Free has no Multi-Object panel: always the selection (a Pro / Basic file may have
    # a list or collection scope stored that the Free user could not see or change)
    affect_target = ('ALL_SELECTED')

    if affect_target == 'CUSTOM_OBJECTS':
        result = []
        vl_objects = context.view_layer.objects
        for item in scene.orivot_mo_custom_objects:
            obj = item.obj
            # PointerProperty can go stale after origin_set — fall back to name lookup
            if obj is None and item.name:
                obj = vl_objects.get(item.name)
            if obj and obj.name in vl_objects and obj.type == 'MESH' and obj.library is None:
                result.append(obj)
        # Fallback: custom list empty → use active object
        if not result:
            obj = context.active_object
            return [obj] if obj and obj.type == 'MESH' and obj.library is None else []
        return result

    elif affect_target == 'COLLECTION':
        col = scene.orivot_mo_target_collection
        if not col:
            # No collection chosen → fallback to active object
            obj = context.active_object
            return [obj] if obj and obj.type == 'MESH' and obj.library is None else []
        vl_objects = context.view_layer.objects
        # all_objects: child collections count too (up to 4.1 only direct members did);
        # objects outside this view layer (excluded collections) cannot be edited here
        return [obj for obj in col.all_objects
                if obj.type == 'MESH' and obj.library is None and obj.name in vl_objects]

    else:  # ALL_SELECTED (default) — auto-MMO: all selected when multiple, active when single
        selected_meshes = [obj for obj in context.selected_objects
                           if obj.type == 'MESH' and obj.library is None]
        if selected_meshes:
            return selected_meshes
        # Fallback: active object only
        obj = context.active_object
        return [obj] if obj and obj.type == 'MESH' and obj.library is None else []
# ---------------- Operators ----------------

def _snap_info_json(sc, desc, landed):
    """Offset & Freeze state at snap time + per-object shift away from the exact snap,
    for the snap operator's Adjust Last Operation panel."""
    import json as _json
    return _json.dumps({
        "desc": desc,
        "mode": getattr(sc, 'orivot_offset_mode', 'OFFSET'),
        "space": getattr(sc, 'orivot_offset_space', 'WORLD'),
        "offset": [sc.orivot_offset_x, sc.orivot_offset_y, sc.orivot_offset_z],
        "lock": [sc.orivot_lock_x, sc.orivot_lock_y, sc.orivot_lock_z],
        "objects": list(landed)[:50],
    })


class ORIVOT_OT_set_origin_extreme_full(bpy.types.Operator):
    """Set origin to geometry extremes (local-axis aware when Mesh mode selected)."""
    bl_idname = "orivot.set_origin_extreme_full"
    @classmethod
    def poll(cls, context):
        # greyed out (with the reason as tooltip) when it cannot act on the selection
        if _any_affected_mesh(context):
            return True
        cls.poll_message_set('Needs a mesh: curves, text and other types have no snap points (World Zero and Handles work on them)')
        return False
    bl_label = "Snap Origin"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.StringProperty(options={'HIDDEN'})
    # What Offset & Freeze did to this snap, for the Adjust Last Operation panel (JSON).
    landed_info: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        # One evaluated-mesh read per object for the whole operation.
        self._landed_info = []
        with meshnp.session():
            res = self._execute(context)
        try:
            self.landed_info = _snap_info_json(context.scene, self.get_mode_description(context),
                                               self._landed_info)
        except Exception:
            pass
        return res

    def _sync_offset_fields(self, context):
        """Same bookkeeping after an Individual or a Combined snap (Combined skipped the
        Direct-mode sync up to 4.1): the live-offset base, and in Direct mode the X / Y / Z
        fields show where the active object's origin landed."""
        sc = context.scene
        act = context.active_object
        landed = getattr(self, "_landed", {})
        if act is None or act.name not in landed:
            act = next((o for o in context.selected_objects if o.name in landed), None)
        if act is None:
            return
        pos = act.matrix_world.translation
        sc['_orivot_offset_base'] = list(Vector((pos.x - sc.orivot_offset_x,
                                                 pos.y - sc.orivot_offset_y,
                                                 pos.z - sc.orivot_offset_z)))
        if getattr(sc, 'orivot_offset_mode', 'OFFSET') == 'DIRECT':
            sc['_orivot_suppress_offset_update'] = True
            try:
                sc.orivot_offset_x = round(pos.x, 6)
                sc.orivot_offset_y = round(pos.y, 6)
                sc.orivot_offset_z = round(pos.z, 6)
            finally:
                sc['_orivot_suppress_offset_update'] = False

    def _center_axis(self, scene):
        flip = scene.orivot_flip_left_right
        return {
            'CENTER_TOP': ('Z', 'max'), 'CENTER_BOTTOM': ('Z', 'min'),
            'CENTER_FRONT': ('Y', 'max'), 'CENTER_BACK': ('Y', 'min'),
            'CENTER_LEFT': ('X', 'min' if flip else 'max'),
            'CENTER_RIGHT': ('X', 'max' if flip else 'min'),
        }[self.mode]

    def _edge_params(self, scene):
        flip = scene.orivot_flip_left_right
        L, R = ('min' if flip else 'max'), ('max' if flip else 'min')
        return {
            'EDGE_TOP_LEFT': ('Z', 'max', 'X', L), 'EDGE_TOP_RIGHT': ('Z', 'max', 'X', R),
            'EDGE_TOP_FRONT': ('Z', 'max', 'Y', 'max'), 'EDGE_TOP_BACK': ('Z', 'max', 'Y', 'min'),
            'EDGE_BOT_LEFT': ('Z', 'min', 'X', L), 'EDGE_BOT_RIGHT': ('Z', 'min', 'X', R),
            'EDGE_BOT_FRONT': ('Z', 'min', 'Y', 'max'), 'EDGE_BOT_BACK': ('Z', 'min', 'Y', 'min'),
            'EDGE_FRONT_LEFT': ('Y', 'max', 'X', L), 'EDGE_FRONT_RIGHT': ('Y', 'max', 'X', R),
            'EDGE_BACK_LEFT': ('Y', 'min', 'X', L), 'EDGE_BACK_RIGHT': ('Y', 'min', 'X', R),
        }.get(self.mode)

    def _note_landing(self, obj, raw, final):
        d = Vector(final) - Vector(raw)
        self._landed_info.append([obj.name, [round(v, 6) for v in d]])

    def draw(self, context):
        """Adjust Last Operation: a reminder of Offset & Freeze. Display only — it never
        changes them (reset is in Origin Snaps > Offset & Freeze)."""
        import json as _json
        layout = self.layout
        try:
            info = _json.loads(self.landed_info) if self.landed_info else None
        except Exception:
            info = None
        if not info:
            layout.label(text="Snap origin")
            return
        layout.label(text=info["desc"], icon='OBJECT_ORIGIN')
        return

    def _execute(self, context):
        scene = context.scene
        source = scene.orivot_snap_source

        affected_objects = get_affected_objects(context)

        if not affected_objects:
            # Give a specific reason based on current mode
            target = scene.orivot_mo_affect_target
            if target == 'ALL_SELECTED':
                self.report({'WARNING'}, "No mesh objects selected — select objects in the viewport first")
            elif target == 'CUSTOM_OBJECTS':
                self.report({'WARNING'}, "Custom object list is empty — add objects via Set Origin To panel")
            elif target == 'COLLECTION':
                if not scene.orivot_mo_target_collection:
                    self.report({'WARNING'}, "No collection selected — pick a target collection in Set Origin To panel")
                else:
                    self.report({'WARNING'}, f"Collection '{scene.orivot_mo_target_collection.name}' has no mesh objects")
            else:
                self.report({'WARNING'}, "No valid mesh objects to process")
            return {'CANCELLED'}

        snap_mode = (('INDIVIDUAL'))

        if snap_mode == 'COMBINED' and len(affected_objects) > 1:
            # COMBINED MODE: Calculate ONE target for all objects
            # Cursor button, or Snap Source = 3D Cursor: the target IS the cursor.
            # (3.x-4.0.1 computed a geometry position first, which returned None for the
            # CURSOR mode, so the Cursor button silently did nothing.)
            if self.mode == 'CURSOR' or source == 'CURSOR':
                target_world = context.scene.cursor.location.copy()
            else:
                target_world = self.calculate_combined_extreme(affected_objects, source, context)

            if target_world is None:
                self.report({'WARNING'}, "Could not calculate combined extreme")
                return {'CANCELLED'}

            # Apply SAME target to ALL objects in one batch (no cursor, no per-object ops)
            pairs = []
            act = context.active_object
            frame = act if act in affected_objects else affected_objects[0]
            for obj in affected_objects:
                _record_history(obj)
                final = _apply_lock_and_offset(obj, target_world, scene, frame_obj=frame)
                self._note_landing(obj, target_world, final)
                pairs.append((obj, final))
            res = _apply_origins_batch(context, pairs)
            for obj, _p in pairs:
                _last_snap_target[obj.name] = Vector((0, 0, 0))
            self._batch_note = res.summary()
            self._landed = {obj.name: p.copy() for obj, p in pairs}
            self._sync_offset_fields(context)

        else:
            # INDIVIDUAL MODE: Calculate SEPARATE target for EACH object, then apply
            # them all in one batch (O(N), no cursor, no per-object operator calls).
            pairs = []
            for obj in affected_objects:
                if self.mode == 'CURSOR' or source == 'CURSOR':
                    target_world = context.scene.cursor.location.copy()
                else:
                    target_world = self.calculate_single_extreme(obj, source, context)
                if target_world is None:
                    continue
                raw = target_world
                target_world = _apply_lock_and_offset(obj, target_world, scene)
                self._note_landing(obj, raw, target_world)
                _record_history(obj)
                pairs.append((obj, target_world))
            self._landed = {obj.name: p.copy() for obj, p in pairs}
            res = _apply_origins_batch(context, pairs)
            for obj, _p in pairs:
                _last_snap_target[obj.name] = Vector((0, 0, 0))
            self._batch_note = res.summary()

            self._sync_offset_fields(context)

        # Report AFTER all origin setting is complete (uses the landed positions; no
        # second mesh evaluation just to print coordinates).
        if affected_objects:
            desc = self.get_mode_description(context)
            note = getattr(self, "_batch_note", "")
            note = f"  ({note})" if note else ""
            if snap_mode == 'COMBINED' and len(affected_objects) > 1:
                self.report({'INFO'}, f"✓ {desc} - Combined {len(affected_objects)} objects{note}")
            elif len(affected_objects) == 1:
                target = getattr(self, "_landed", {}).get(affected_objects[0].name)
                if target is not None:
                    self.report({'INFO'}, f"✓ {desc} at X:{target.x:.3f}, Y:{target.y:.3f}, Z:{target.z:.3f}{note}")
                else:
                    self.report({'INFO'}, f"✓ {desc}{note}")
            else:
                self.report({'INFO'}, f"✓ {desc} - {len(affected_objects)} objects (Independent){note}")

        if scene.orivot_show_preview:
            obj = context.active_object
            if obj and obj.type == 'MESH':
                try:
                    create_or_update_preview(obj)
                except Exception:
                    pass  # intentional: try:

        # Store face normal for Normal Offset (face/center ops have well-defined normals)
        _FACE_NORMALS_LOCAL = {
            'FACE_TOP':    Vector(( 0,  0,  1)), 'CENTER_TOP':    Vector(( 0,  0,  1)),
            'FACE_BOTTOM': Vector(( 0,  0, -1)), 'CENTER_BOTTOM': Vector(( 0,  0, -1)),
            'FACE_FRONT':  Vector(( 0,  1,  0)), 'CENTER_FRONT':  Vector(( 0,  1,  0)),
            'FACE_BACK':   Vector(( 0, -1,  0)), 'CENTER_BACK':   Vector(( 0, -1,  0)),
            'FACE_LEFT':   Vector((-1,  0,  0)), 'CENTER_LEFT':   Vector((-1,  0,  0)),
            'FACE_RIGHT':  Vector(( 1,  0,  0)), 'CENTER_RIGHT':  Vector(( 1,  0,  0)),
        }
        if self.mode in _FACE_NORMALS_LOCAL:
            normal_local = _FACE_NORMALS_LOCAL[self.mode]
            for aobj in affected_objects:
                if scene.orivot_preview_orientation == 'LOCAL':
                    nw = (aobj.matrix_world.to_3x3() @ normal_local).normalized()
                else:
                    nw = normal_local.normalized()
                _last_snap_normals[aobj.name] = nw

        return {'FINISHED'}

    def calculate_combined_extreme(self, objects, source, context):
        """Calculate combined extreme for multiple objects."""
        scene = context.scene

        # Object centres of the whole group (up to 4.1.0 Geometry and BBox returned
        # nothing in Combined mode, and Mass ignored Combined).
        if self.mode in ("CENTER_GEOMETRY", "CENTER_BBOX", "CENTER_MASS"):
            meshes = [o for o in objects if o.type == 'MESH']
            if self.mode == "CENTER_MASS":
                return meshnp.combined_volume_centroid(meshes)
            if self.mode == "CENTER_GEOMETRY" and source == 'MESH':
                return meshnp.combined_mean_world(meshes)
            corners = [o.matrix_world @ v for o in meshes for v in get_bbox_local(o)]
            if not corners:
                return None
            lo = Vector((min(v.x for v in corners), min(v.y for v in corners), min(v.z for v in corners)))
            hi = Vector((max(v.x for v in corners), max(v.y for v in corners), max(v.z for v in corners)))
            return (lo + hi) / 2.0

        meshes = [o for o in objects if o.type == 'MESH']
        if not meshes:
            return None

        # Group bounds in WORLD axes: Mesh uses the real vertices; BBox the objects' boxes
        # (up to 4.1 Mesh also used the boxes, which are bigger than rotated geometry).
        W = meshnp.combined_world_points(meshes) if source == 'MESH' else None
        if W is not None and len(W):
            lo, hi = W.min(axis=0), W.max(axis=0)
        else:
            corners = [o.matrix_world @ v for o in meshes for v in get_bbox_local(o)]
            if not corners:
                return None
            lo = [min(v[i] for v in corners) for i in range(3)]
            hi = [max(v[i] for v in corners) for i in range(3)]
        lo = [float(x) for x in lo]
        hi = [float(x) for x in hi]
        mid = [(lo[i] + hi[i]) / 2.0 for i in range(3)]

        def ideal(mode):
            saved = self.mode
            try:
                self.mode = mode
                return self.get_combined_ideal_world(scene, lo[0], hi[0], lo[1], hi[1], lo[2], hi[2],
                                                     mid[0], mid[1], mid[2])
            finally:
                self.mode = saved

        face_axis = {
            'FACE_TOP': ('Z', 'max'), 'FACE_BOTTOM': ('Z', 'min'),
            'FACE_FRONT': ('Y', 'max'), 'FACE_BACK': ('Y', 'min'),
            'FACE_LEFT': ('X', 'min' if scene.orivot_flip_left_right else 'max'),
            'FACE_RIGHT': ('X', 'max' if scene.orivot_flip_left_right else 'min'),
        }
        if self.mode in face_axis:
            if source == 'MESH':
                axis, ext = face_axis[self.mode]
                return get_combined_face_centroid(meshes, axis, ext, source)
            # BBox: the centre of the group box's face (up to 4.1 this averaged the touching
            # objects' own faces, so Faces > Top and Face Centres > Top disagreed)
            return ideal(self.mode.replace("FACE_", "CENTER_"))

        target = ideal(self.mode)
        if target is None or source != 'MESH':
            return target
        if self.mode.startswith("VERT_"):
            return meshnp.combined_closest_vertex(meshes, target)
        if self.mode.startswith("EDGE_"):
            ep = self._edge_params(scene)
            t = meshnp.combined_edge_midpoint(meshes, *ep) if ep else None
            return t if t is not None else target
        if self.mode.startswith("CENTER_"):
            axis, ext = self._center_axis(scene)
            t = meshnp.combined_surface_center(meshes, axis, ext, lo, hi)
            return t if t is not None else target
        return target

    def get_combined_ideal_world(self, scene, min_x, max_x, min_y, max_y, min_z, max_z, xmid, ymid, zmid):
        """Get ideal world position for combined bounding box based on mode."""
        flip = scene.orivot_flip_left_right

        # VERTICES
        if self.mode == 'VERT_TLF':
            return Vector((min_x if flip else max_x, max_y, max_z))
        elif self.mode == 'VERT_TRF':
            return Vector((max_x if flip else min_x, max_y, max_z))
        elif self.mode == 'VERT_TLB':
            return Vector((min_x if flip else max_x, min_y, max_z))
        elif self.mode == 'VERT_TRB':
            return Vector((max_x if flip else min_x, min_y, max_z))
        elif self.mode == 'VERT_BLF':
            return Vector((min_x if flip else max_x, max_y, min_z))
        elif self.mode == 'VERT_BRF':
            return Vector((max_x if flip else min_x, max_y, min_z))
        elif self.mode == 'VERT_BLB':
            return Vector((min_x if flip else max_x, min_y, min_z))
        elif self.mode == 'VERT_BRB':
            return Vector((max_x if flip else min_x, min_y, min_z))

        # EDGES
        elif self.mode == 'EDGE_TOP_LEFT':
            return Vector((min_x if flip else max_x, ymid, max_z))
        elif self.mode == 'EDGE_TOP_RIGHT':
            return Vector((max_x if flip else min_x, ymid, max_z))
        elif self.mode == 'EDGE_TOP_FRONT':
            return Vector((xmid, max_y, max_z))
        elif self.mode == 'EDGE_TOP_BACK':
            return Vector((xmid, min_y, max_z))
        elif self.mode == 'EDGE_BOT_LEFT':
            return Vector((min_x if flip else max_x, ymid, min_z))
        elif self.mode == 'EDGE_BOT_RIGHT':
            return Vector((max_x if flip else min_x, ymid, min_z))
        elif self.mode == 'EDGE_BOT_FRONT':
            return Vector((xmid, max_y, min_z))
        elif self.mode == 'EDGE_BOT_BACK':
            return Vector((xmid, min_y, min_z))
        elif self.mode == 'EDGE_FRONT_LEFT':
            return Vector((min_x if flip else max_x, max_y, zmid))
        elif self.mode == 'EDGE_FRONT_RIGHT':
            return Vector((max_x if flip else min_x, max_y, zmid))
        elif self.mode == 'EDGE_BACK_LEFT':
            return Vector((min_x if flip else max_x, min_y, zmid))
        elif self.mode == 'EDGE_BACK_RIGHT':
            return Vector((max_x if flip else min_x, min_y, zmid))

        # CENTERS
        elif self.mode == 'CENTER_TOP':
            return Vector((xmid, ymid, max_z))
        elif self.mode == 'CENTER_BOTTOM':
            return Vector((xmid, ymid, min_z))
        elif self.mode == 'CENTER_LEFT':
            return Vector((min_x if flip else max_x, ymid, zmid))
        elif self.mode == 'CENTER_RIGHT':
            return Vector((max_x if flip else min_x, ymid, zmid))
        elif self.mode == 'CENTER_FRONT':
            return Vector((xmid, max_y, zmid))
        elif self.mode == 'CENTER_BACK':
            return Vector((xmid, min_y, zmid))

        return None

    def calculate_single_extreme(self, obj, source, context):
        """Calculate extreme for a single object."""
        scene = context.scene

        if source == 'MESH':
            ext = meshnp.extreme_vertices(obj)
            if ext is None:
                return None
            min_x_local, max_x_local, min_y_local, max_y_local, min_z_local, max_z_local = ext
        else:
            verts_local = get_bbox_local(obj)
            if not verts_local:
                return None
            min_x_local = min(verts_local, key=lambda v: v.x)
            max_x_local = max(verts_local, key=lambda v: v.x)
            min_y_local = min(verts_local, key=lambda v: v.y)
            max_y_local = max(verts_local, key=lambda v: v.y)
            min_z_local = min(verts_local, key=lambda v: v.z)
            max_z_local = max(verts_local, key=lambda v: v.z)

        xmid_local = (min_x_local.x + max_x_local.x) / 2.0
        ymid_local = (min_y_local.y + max_y_local.y) / 2.0
        zmid_local = (min_z_local.z + max_z_local.z) / 2.0

        target_world = None

        # --- Faces ---
        if self.mode == "FACE_TOP":
            if source == 'MESH':
                t = face_centroid_extreme(obj, 'Z', 'max')
                target_world = t if t is not None else local_to_world(obj,
                                                                      Vector((xmid_local, ymid_local, max_z_local.z)))
            else:
                target_world = local_to_world(obj, Vector((xmid_local, ymid_local, max_z_local.z)))

        elif self.mode == "FACE_BOTTOM":
            if source == 'MESH':
                t = face_centroid_extreme(obj, 'Z', 'min')
                target_world = t if t is not None else local_to_world(obj,
                                                                      Vector((xmid_local, ymid_local, min_z_local.z)))
            else:
                target_world = local_to_world(obj, Vector((xmid_local, ymid_local, min_z_local.z)))

        elif self.mode == "FACE_LEFT":
            if scene.orivot_flip_left_right:
                if source == 'MESH':
                    t = face_centroid_extreme(obj, 'X', 'min')
                    target_world = t if t is not None else local_to_world(obj, Vector(
                        (min_x_local.x, ymid_local, zmid_local)))
                else:
                    target_world = local_to_world(obj, Vector((min_x_local.x, ymid_local, zmid_local)))
            else:
                if source == 'MESH':
                    t = face_centroid_extreme(obj, 'X', 'max')
                    target_world = t if t is not None else local_to_world(obj, Vector(
                        (max_x_local.x, ymid_local, zmid_local)))
                else:
                    target_world = local_to_world(obj, Vector((max_x_local.x, ymid_local, zmid_local)))

        elif self.mode == "FACE_RIGHT":
            if scene.orivot_flip_left_right:
                if source == 'MESH':
                    t = face_centroid_extreme(obj, 'X', 'max')
                    target_world = t if t is not None else local_to_world(obj, Vector(
                        (max_x_local.x, ymid_local, zmid_local)))
                else:
                    target_world = local_to_world(obj, Vector((max_x_local.x, ymid_local, zmid_local)))
            else:
                if source == 'MESH':
                    t = face_centroid_extreme(obj, 'X', 'min')
                    target_world = t if t is not None else local_to_world(obj, Vector(
                        (min_x_local.x, ymid_local, zmid_local)))  # Use min_x for fallback
                else:
                    target_world = local_to_world(obj, Vector((min_x_local.x, ymid_local, zmid_local)))  # Use min_x for bbox

        elif self.mode == "FACE_FRONT":
            if source == 'MESH':
                t = face_centroid_extreme(obj, 'Y', 'max')
                target_world = t if t is not None else local_to_world(obj,
                                                                      Vector((xmid_local, max_y_local.y, zmid_local)))
            else:
                target_world = local_to_world(obj, Vector((xmid_local, max_y_local.y, zmid_local)))

        elif self.mode == "FACE_BACK":
            if source == 'MESH':
                t = face_centroid_extreme(obj, 'Y', 'min')
                target_world = t if t is not None else local_to_world(obj,
                                                                      Vector((xmid_local, min_y_local.y, zmid_local)))
            else:
                target_world = local_to_world(obj, Vector((xmid_local, min_y_local.y, zmid_local)))

        # --- Vertices ---
        elif self.mode.startswith("VERT_"):
            ideal_local = self.get_vertex_ideal_local(scene, min_x_local, max_x_local, min_y_local, max_y_local,
                                                        min_z_local, max_z_local)
            if source == 'MESH':
                t = meshnp.closest_vertex_world(obj, ideal_local)
                target_world = t if t is not None else local_to_world(obj, ideal_local)
            else:
                target_world = local_to_world(obj, ideal_local)

                # --- Edges ---
        elif self.mode.startswith("EDGE_"):
            ideal_local = self.get_edge_ideal_local(scene, min_x_local, max_x_local, min_y_local, max_y_local,
                                                        min_z_local, max_z_local, xmid_local, ymid_local, zmid_local)
            if source == 'MESH':
                # In Mesh mode: find TRUE edge midpoint by averaging vertices at both extremes
                flip = scene.orivot_flip_left_right
                
                # Map edge mode to axis extremes
                edge_params = {
                    # Top ring edges (Z=max)
                    'EDGE_TOP_LEFT':    ('Z', 'max', 'X', 'min' if flip else 'max'),
                    'EDGE_TOP_RIGHT':   ('Z', 'max', 'X', 'max' if flip else 'min'),
                    'EDGE_TOP_FRONT':   ('Z', 'max', 'Y', 'max'),
                    'EDGE_TOP_BACK':    ('Z', 'max', 'Y', 'min'),
                    # Bottom ring edges (Z=min)
                    'EDGE_BOT_LEFT':    ('Z', 'min', 'X', 'min' if flip else 'max'),
                    'EDGE_BOT_RIGHT':   ('Z', 'min', 'X', 'max' if flip else 'min'),
                    'EDGE_BOT_FRONT':   ('Z', 'min', 'Y', 'max'),
                    'EDGE_BOT_BACK':    ('Z', 'min', 'Y', 'min'),
                    # Vertical edges (X and Y extremes)
                    'EDGE_FRONT_LEFT':  ('Y', 'max', 'X', 'min' if flip else 'max'),
                    'EDGE_FRONT_RIGHT': ('Y', 'max', 'X', 'max' if flip else 'min'),
                    'EDGE_BACK_LEFT':   ('Y', 'min', 'X', 'min' if flip else 'max'),
                    'EDGE_BACK_RIGHT':  ('Y', 'min', 'X', 'max' if flip else 'min'),
                }
                
                if self.mode in edge_params:
                    axis1, extreme1, axis2, extreme2 = edge_params[self.mode]
                    t = edge_midpoint_extreme(obj, axis1, extreme1, axis2, extreme2)
                    target_world = t if t is not None else local_to_world(obj, ideal_local)
                else:
                    target_world = local_to_world(obj, ideal_local)
            else:
                # In BBox mode: use exact calculated midpoint position
                target_world = local_to_world(obj, ideal_local)

            # --- Centers ---
        elif self.mode.startswith("CENTER_") and self.mode not in {"CENTER_GEOMETRY", "CENTER_BBOX", "CENTER_MASS"}:
            ideal_local = self.get_center_ideal_local(scene, min_x_local, max_x_local, min_y_local, max_y_local,
                                                      min_z_local, max_z_local, xmid_local, ymid_local, zmid_local)
            if source == 'MESH':
                # Mesh: the point on the surface in the middle of that side (a ray through the
                # box face centre). Up to 4.1 this took the vertex nearest the box face
                # centre, so on a plain box "Top" landed on an arbitrary corner.
                axis, ext = self._center_axis(scene)
                t = meshnp.surface_center_world(obj, axis, ext)
                target_world = t if t is not None else local_to_world(obj, ideal_local)
            else:
                # In BBox mode: use exact calculated face center position
                target_world = local_to_world(obj, ideal_local)

        # --- Global Centers ---
        elif self.mode == "CENTER_GEOMETRY":
            # Center of Geometry (median point - average of all vertices)
            if source == 'MESH':
                t = meshnp.mean_world(obj)
                target_world = t if t is not None else local_to_world(
                    obj, Vector((xmid_local, ymid_local, zmid_local)))
            else:
                # BBox mode: use bbox center
                target_world = local_to_world(obj, Vector((xmid_local, ymid_local, zmid_local)))

        elif self.mode == "CENTER_BBOX":
            # Center of BBox (geometric center of bounds - works in both modes)
            target_world = local_to_world(obj, Vector((xmid_local, ymid_local, zmid_local)))

        elif self.mode == "CENTER_MASS":
            # Centre of mass (volume), computed here so Offset & Freeze and Combined mode
            # apply like every other snap. Up to 4.1.0 this called Blender's own
            # operator, which skipped both and ignored Combined.
            _v, t = meshnp.volume_centroid_world(obj)
            target_world = t if t is not None else local_to_world(
                obj, Vector((xmid_local, ymid_local, zmid_local)))

        return target_world

    def get_vertex_ideal_local(self, scene, min_x, max_x, min_y, max_y, min_z, max_z):
        """Get ideal local position for vertex corners with flip support."""
        flip = scene.orivot_flip_left_right

        corner_map = {
            'VERT_TLF': Vector((min_x.x if flip else max_x.x, max_y.y, max_z.z)),
            'VERT_TRF': Vector((max_x.x if flip else min_x.x, max_y.y, max_z.z)),
            'VERT_TLB': Vector((min_x.x if flip else max_x.x, min_y.y, max_z.z)),
            'VERT_TRB': Vector((max_x.x if flip else min_x.x, min_y.y, max_z.z)),
            'VERT_BLF': Vector((min_x.x if flip else max_x.x, max_y.y, min_z.z)),
            'VERT_BRF': Vector((max_x.x if flip else min_x.x, max_y.y, min_z.z)),
            'VERT_BLB': Vector((min_x.x if flip else max_x.x, min_y.y, min_z.z)),
            'VERT_BRB': Vector((max_x.x if flip else min_x.x, min_y.y, min_z.z)),
        }
        return corner_map.get(self.mode, Vector((0, 0, 0)))

    def get_edge_ideal_local(self, scene, min_x, max_x, min_y, max_y, min_z, max_z, xmid, ymid, zmid):
        """Get ideal local position for edge midpoints with flip support."""
        flip = scene.orivot_flip_left_right

        edge_map = {
            'EDGE_TOP_LEFT': Vector((min_x.x if flip else max_x.x, ymid, max_z.z)),
            'EDGE_TOP_RIGHT': Vector((max_x.x if flip else min_x.x, ymid, max_z.z)),
            'EDGE_TOP_FRONT': Vector((xmid, max_y.y, max_z.z)),
            'EDGE_TOP_BACK': Vector((xmid, min_y.y, max_z.z)),
            'EDGE_BOT_LEFT': Vector((min_x.x if flip else max_x.x, ymid, min_z.z)),
            'EDGE_BOT_RIGHT': Vector((max_x.x if flip else min_x.x, ymid, min_z.z)),
            'EDGE_BOT_FRONT': Vector((xmid, max_y.y, min_z.z)),
            'EDGE_BOT_BACK': Vector((xmid, min_y.y, min_z.z)),
            'EDGE_FRONT_LEFT': Vector((min_x.x if flip else max_x.x, max_y.y, zmid)),
            'EDGE_FRONT_RIGHT': Vector((max_x.x if flip else min_x.x, max_y.y, zmid)),
            'EDGE_BACK_LEFT': Vector((min_x.x if flip else max_x.x, min_y.y, zmid)),
            'EDGE_BACK_RIGHT': Vector((max_x.x if flip else min_x.x, min_y.y, zmid)),
        }
        return edge_map.get(self.mode, Vector((xmid, ymid, zmid)))

    def get_center_ideal_local(self, scene, min_x, max_x, min_y, max_y, min_z, max_z, xmid, ymid, zmid):
        """Get ideal local position for face centers with flip support."""
        flip = scene.orivot_flip_left_right

        center_map = {
            'CENTER_TOP': Vector((xmid, ymid, max_z.z)),
            'CENTER_BOTTOM': Vector((xmid, ymid, min_z.z)),
            'CENTER_LEFT': Vector((min_x.x if flip else max_x.x, ymid, zmid)),
            'CENTER_RIGHT': Vector((max_x.x if flip else min_x.x, ymid, zmid)),
            'CENTER_FRONT': Vector((xmid, max_y.y, zmid)),
            'CENTER_BACK': Vector((xmid, min_y.y, zmid)),
        }
        return center_map.get(self.mode, Vector((xmid, ymid, zmid)))

    def get_mode_description(self, context):
        """Get human-readable description of the mode."""
        scene = context.scene
        flip = scene.orivot_flip_left_right

        descriptions = {
            'CURSOR': "Origin to 3D Cursor",
            'FACE_TOP': "Top Face (+Z)",
            'FACE_BOTTOM': "Bottom Face (-Z)",
            'FACE_LEFT': f"Left Face ({'-X' if flip else '+X'})",
            'FACE_RIGHT': f"Right Face ({'+X' if flip else '-X'})",
            'FACE_FRONT': "Front Face (+Y)",
            'FACE_BACK': "Back Face (-Y)",
        }

        descriptions.update({
            'CENTER_GEOMETRY': "Geometry Centre", 'CENTER_BBOX': "BBox Centre",
            'CENTER_MASS': "Centre of Mass",
        })
        if self.mode in descriptions:
            return descriptions[self.mode]
        kind, _, rest = self.mode.partition("_")
        words = rest.replace("BOT", "BOTTOM").replace("_", " ").title()
        if kind == 'VERT' and len(rest) == 3:          # TLF -> Top Left Front
            names = {'T': "Top", 'B': "Bottom", 'L': "Left", 'R': "Right", 'F': "Front"}
            words = " ".join([names[rest[0]], names[rest[1]], "Front" if rest[2] == 'F' else "Back"])
        return {'VERT': "Corner", 'EDGE': "Edge Midpoint", 'CENTER': "Face Centre"}.get(kind, "Snap") + \
            (f" {words}" if words else "")


# ---------------- Supporting Operators ----------------

# ---------------- Surface Snap Operator (Free Surface Mode) ----------------
# ---------------- Vertex Snap Operator (Drag-to-Snap Mode) ----------------
# ---------------- Quick Snap Operators for Alt+Click ----------------
# ── Object Snap Tools — Helper Functions ──────────────────────────────────────

# ── Object Snap Tools — Operators ─────────────────────────────────────────────


# ── Pie Menu ──────────────────────────────────────────────────────────────────

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
              'PASTE_ORIGIN', 'ORIGIN_TOOLS', 'EDITMODE_SNAP', 'SNAP_TO_GRID', 'SYMMETRY_AUTO'}
_PIE_PRO = {'OBJECT_SNAP_INSTANT', 'PLACE_ON_SURFACE', 'SNAP_TO_CURVE'}
ORIVOT_PIE_ACTIONS = [a for a in ORIVOT_PIE_ACTIONS
                      if (((a[0] not in _PIE_BASIC))) and (((a[0] not in _PIE_PRO)))]
ORIVOT_PIE_DEFAULTS = ORIVOT_PIE_DEFAULTS[:7] + ('WORLD_ZERO',)


def _orivot_pie_draw_action(layout, action, prefs):
    """Draw one pie-menu action into `layout` (a pie slot or a column)."""
    op_id = "orivot.set_origin_extreme_full"

    if action == 'NONE':
        return
    elif action == 'LEFT':
        layout.operator(op_id, text="Left (+X)", icon='TRIA_LEFT').mode = 'FACE_LEFT'
    elif action == 'RIGHT':
        layout.operator(op_id, text="Right (-X)", icon='TRIA_RIGHT').mode = 'FACE_RIGHT'
    elif action == 'BOTTOM':
        layout.operator(op_id, text="Bottom (-Z)", icon='TRIA_DOWN').mode = 'FACE_BOTTOM'
    elif action == 'TOP':
        layout.operator(op_id, text="Top (+Z)", icon='TRIA_UP').mode = 'FACE_TOP'
    elif action == 'BACK':
        layout.operator(op_id, text="Back (-Y)", icon='BACK').mode = 'FACE_BACK'
    elif action == 'FRONT':
        layout.operator(op_id, text="Front (+Y)", icon='FORWARD').mode = 'FACE_FRONT'
    elif action == 'SURFACE_SNAP':
        layout.operator("orivot.surface_snap_origin", text="Surface Snap", icon='PIVOT_CURSOR')
    elif action == 'VERTEX_SNAP':
        layout.operator("orivot.vertex_snap_origin", text="Vertex Snap", icon='VERTEXSEL')
    elif action == 'CENTER_GEOMETRY':
        layout.operator(op_id, text="Center Geometry", icon='PIVOT_MEDIAN').mode = 'CENTER_GEOMETRY'
    elif action == 'CENTER_BBOX':
        layout.operator(op_id, text="Center BBox", icon='PIVOT_BOUNDBOX').mode = 'CENTER_BBOX'
    elif action == 'CENTER_MASS':
        layout.operator(op_id, text="Center Mass", icon='MOD_PHYSICS').mode = 'CENTER_MASS'
    elif action == 'CLICK_BBOX_HANDLE':
        layout.operator("orivot.click_bbox_handle", text="Click BBox Handle", icon='SNAP_ON')
    elif action == 'COPY_ORIGIN':
        layout.operator("orivot.copy_origin", text="Copy Origin", icon='COPYDOWN')
    elif action == 'PASTE_ORIGIN':
        layout.operator("orivot.paste_origin", text="Paste Origin", icon='PASTEDOWN')
    elif action == 'EDITMODE_SNAP':
        layout.operator("orivot.editmode_snap", text="Edit Mode Snap", icon='SNAP_ON')
    elif action == 'OBJECT_SNAP_INSTANT':
        layout.operator("orivot.object_snap_instant", text="Snap to Object", icon='SNAP_ON')
    elif action == 'PLACE_ON_SURFACE':
        layout.operator("orivot.place_on_surface", text="Place on Surface", icon='CURSOR')
    elif action == 'SNAP_TO_CURVE':
        layout.operator("orivot.snap_to_curve", text="Snap to Curve", icon='CURVE_DATA')
    elif action == 'WORLD_ZERO':
        layout.operator("orivot.snap_to_world_zero", text="World Zero", icon='WORLD')
    elif action == 'SNAP_TO_GRID':
        layout.operator("orivot.snap_to_grid", text="Snap to Grid", icon='SNAP_GRID')
    elif action == 'SYMMETRY_AUTO':
        layout.operator("orivot.symmetry_origin", text="Mirror Plane (Auto)", icon='MOD_MIRROR').axis = 'AUTO'
    elif action == 'GLOBAL_CENTERS':
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
        return context.preferences.addons[__name__].preferences
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


# ── Snap to World Grid ────────────────────────────────────────────────────────

# ── Normal Offset (apply along last stored snap normal) ───────────────────────

# ── Symmetry Origin ───────────────────────────────────────────────────────────

# ── Viewport BBox Handles — Click-to-Snap Modal ────────────────────────────────

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
        except Exception:
            pass


def _start_handle_mode():
    """Timer: start the persistent handle-snap modal in a real 3D Viewport region.
    (Operators must not be called from a property update callback.)"""
    try:
        ctx = bpy.context
        if not getattr(ctx.scene, 'orivot_show_viewport_handles', False) or _handle_mode["running"]:
            return None
        ensure_handle_draw()                 # file load / add-on enable with Handles saved on
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
            ensure_handle_draw()
            if not bpy.app.timers.is_registered(_start_handle_mode):
                bpy.app.timers.register(_start_handle_mode, first_interval=0.0)
    except Exception:
        pass


def _handles_toggle_update(self, context):
    """Handles ON  -> snapping is live immediately (no extra button).
    Handles OFF -> the running modal sees the flag and ends on its next event."""
    if self.orivot_show_viewport_handles:
        _handle_mode["stop"] = False
        ensure_handle_draw()                 # visible even with Preview off
        if not bpy.app.timers.is_registered(_start_handle_mode):
            bpy.app.timers.register(_start_handle_mode, first_interval=0.0)
    _tag_view3d_redraw()


# ---------------- Panel ----------------


# ═══════════════════════════════════════════════════════════════════════════════
# NEW v1.2.0 OPERATORS
# ═══════════════════════════════════════════════════════════════════════════════

# ── Origin History ────────────────────────────────────────────────────────────

# ── Copy / Paste Origin ───────────────────────────────────────────────────────

# ── Edit Mode Origin Snap ─────────────────────────────────────────────────────

# ── Batch Normalize ───────────────────────────────────────────────────────────

# ── Batch Normalize helpers (module-level so Blender never validates them) ─────


# ═══════════════════════════════════════════════════════════════════════════════
# ORIVOT PRO — NEW FEATURE OPERATORS
# ═══════════════════════════════════════════════════════════════════════════════


# ── FEATURE 3: Object-space offset toggle ─────────────────────────────────────
# Handled via scene.orivot_offset_space prop + modified _apply_lock_and_offset
# (wired below in property registration)

# ── FEATURE 4: Snap to another object's origin (eyedropper picker) ────────────
# ── FEATURE 4b: Move object to another object's origin ───────────────────────
# ── FEATURE 5: Align origins across selection ─────────────────────────────────
# ── FEATURE 1: Snap to Curve (start / middle / end / control-point average) ───
# ── FEATURE 6: Named persistent MO groups ────────────────────────────────────
class OrivotProNamedGroup(bpy.types.PropertyGroup):
    """A named, persistent group of objects for Multi-Object operations."""
    name       : bpy.props.StringProperty(name="Group Name", default="Group")
    object_names: bpy.props.StringProperty(
        name="Objects",
        description="Comma-separated object names (persists with .blend file)"
    )
    # Derived: list of names is stored as CSV string for persistence

# ── FEATURE 7: Surface snap to other scene objects ────────────────────────────
# ── FEATURE 9: CSV export of origin positions ─────────────────────────────────
# ---------------- Menus ----------------
def auto_show_preview_timer():
    """One-shot timer behind 'Auto-show on hover': turn the preview on for the active
    object when a Set Origin submenu opens. (Referenced since 3.x but never defined —
    opening the submenu with the option on raised NameError.)"""
    global _auto_show_timer
    _auto_show_timer = None
    try:
        scene = bpy.context.scene
        obj = bpy.context.active_object
        if obj is None or obj.type not in GEOMETRY_TYPES:
            return None
        if not scene.orivot_show_preview:
            scene.orivot_show_preview = True       # update callback builds the preview
        else:
            create_or_update_preview(obj)
        _tag_view3d_redraw()
    except Exception as e:
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


# ---------------- Property Group for Custom Objects ----------------

class OriginMOCustomObject(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(
        name="Object",
        type=bpy.types.Object,
        description="Mesh object to affect"
    )


# ---------------- Registration ----------------
class OrivotAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

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

    configs         : bpy.props.CollectionProperty(type=_configs.OrivotConfig)
    named_groups    : bpy.props.CollectionProperty(type=OrivotProNamedGroup)

    # ---- Pie Menu (Alt+Q) — fully customizable, Orivot Pro only ----
    pie_slot_w  : bpy.props.EnumProperty(name="West",      items=ORIVOT_PIE_ACTIONS, default='LEFT',
        description="Action shown on the West (left) position of the pie menu")
    pie_slot_e  : bpy.props.EnumProperty(name="East",      items=ORIVOT_PIE_ACTIONS, default='RIGHT',
        description="Action shown on the East (right) position of the pie menu")
    pie_slot_s  : bpy.props.EnumProperty(name="South",     items=ORIVOT_PIE_ACTIONS, default='BOTTOM',
        description="Action shown on the South (bottom) position of the pie menu")
    pie_slot_n  : bpy.props.EnumProperty(name="North",     items=ORIVOT_PIE_ACTIONS, default='TOP',
        description="Action shown on the North (top) position of the pie menu")
    pie_slot_nw : bpy.props.EnumProperty(name="Northwest", items=ORIVOT_PIE_ACTIONS, default='BACK',
        description="Action shown on the Northwest position of the pie menu")
    pie_slot_ne : bpy.props.EnumProperty(name="Northeast", items=ORIVOT_PIE_ACTIONS, default='FRONT',
        description="Action shown on the Northeast position of the pie menu")
    pie_slot_sw : bpy.props.EnumProperty(name="Southwest", items=ORIVOT_PIE_ACTIONS, default='GLOBAL_CENTERS',
        description="Action shown on the Southwest position of the pie menu")
    pie_slot_se : bpy.props.EnumProperty(name="Southeast", items=ORIVOT_PIE_ACTIONS, default=ORIVOT_PIE_DEFAULTS[7],
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
        prefs = context.preferences.addons[__name__].preferences
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
        prefs = context.preferences.addons[__name__].preferences
        (prefs.pie_slot_w, prefs.pie_slot_e, prefs.pie_slot_s, prefs.pie_slot_n,
         prefs.pie_slot_nw, prefs.pie_slot_ne, prefs.pie_slot_sw, prefs.pie_slot_se) = ORIVOT_PIE_DEFAULTS
        prefs.pie_gc_show_geometry = True
        prefs.pie_gc_show_bbox     = True
        prefs.pie_gc_show_mass     = True
        prefs.pie_ot_show_copy     = True
        prefs.pie_ot_show_paste    = True
        prefs.pie_ot_show_handle   = True
        self.report({'INFO'}, "Orivot: pie menu layout reset to defaults")
        return {'FINISHED'}




# ══════════════════════════════════════════════════════════════════════════════
# ORIVOT PLACE — Phases 1, 2 & 3
# ══════════════════════════════════════════════════════════════════════════════

# ── Snap History helpers ───────────────────────────────────────────────────────

def push_snap_history(obj_name: str, world_pos: Vector) -> None:
    """Record a snap position. Called automatically by _apply_origin() and confirm_snap.
    Suppressed during history navigation and batch operations via _SNAP_RECORDING[0]."""
    if not _SNAP_RECORDING[0]:
        return
    entry = (obj_name, world_pos.copy())
    if _SNAP_HISTORY and _SNAP_HISTORY[-1] == entry:
        return
    _SNAP_HISTORY.append(entry)
    if len(_SNAP_HISTORY) > _SNAP_HISTORY_MAX:
        _SNAP_HISTORY.pop(0)
    _SNAP_HISTORY_IDX[0] = len(_SNAP_HISTORY) - 1


def clear_snap_history() -> None:
    _SNAP_HISTORY.clear()
    _SNAP_HISTORY_IDX[0] = 0


# ── Collision Preview helpers ──────────────────────────────────────────────────

# ── Surface Align helper ───────────────────────────────────────────────────────

# ══ Phase 1 Operators ═════════════════════════════════════════════════════════

# ══ Phase 2 Operators ═════════════════════════════════════════════════════════

# ══ Orivot Place Panel ═════════════════════════════════════════════════════════

# ══ F3: Snap History HUD draw function ════════════════════════════════════════

def _draw_history_hud():
    """POST_PIXEL: show a small history-position banner for ~2 s after Prev/Next."""
    import time
    try:
        if not _history_hud_text[0]:
            return
        elapsed = time.monotonic() - _history_hud_time[0]
        if elapsed > 2.5:
            _history_hud_text[0] = None
            _tag_view3d_redraw()   # force viewport to repaint so text clears immediately
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
        blf.draw(0, _history_hud_text[0])
    except Exception:
        pass


# ══ F6: Viewport Mode Indicator draw function ══════════════════════════════════

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
    except Exception:
        pass


# ══ F1: Snap to World Zero ════════════════════════════════════════════════════

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
                context.active_object.type in GEOMETRY_TYPES and
                not context.active_object.library)

    def execute(self, context):
        obj = context.active_object
        _record_history(obj)
        _apply_origin(obj, Vector((0.0, 0.0, 0.0)), context)
        self.report({'INFO'}, f"✓ Origin → World Zero (0,0,0)  [{obj.name}]")
        _tag_view3d_redraw()
        return {'FINISHED'}


class ORIVOT_OT_open_upgrade(bpy.types.Operator):
    """Open the Orivot store page for the next edition"""
    bl_idname = "orivot.open_upgrade"
    bl_label = "Get Orivot"
    bl_options = {'INTERNAL'}

    edition: bpy.props.EnumProperty(items=[('BASIC', "Basic", ""), ('PRO', "Pro", "")],
                                    default='PRO', options={'SKIP_SAVE'})

    def execute(self, context):
        bpy.ops.wm.url_open(url=tier.URL_BASIC if self.edition == 'BASIC' else tier.URL_PRO)
        return {'FINISHED'}


# What each edition registers (see tier.py). Property groups are data types every
# edition needs (preferences and scenes store them), so they are always registered.
FREE_CLASSES = (
    _configs.OrivotConfig,
    OrivotProNamedGroup,
    OriginMOCustomObject,
    OrivotAddonPreferences,
    ORIVOT_OT_apply_preference_defaults,
    ORIVOT_OT_reset_pie_defaults,
    ORIVOT_OT_set_origin_extreme_full,
    ORIVOT_OT_snap_to_world_zero,
    ORIVOT_OT_show_shortcuts_info,
    VIEW3D_MT_orivot_pie,
    VIEW3D_MT_set_origin_faces,
    VIEW3D_MT_set_origin_vertices,
    VIEW3D_MT_set_origin_edges,
    VIEW3D_MT_set_origin_centers,
    VIEW3D_MT_set_origin_main,
)
BASIC_CLASSES = ()
PRO_CLASSES = ()
classes = (FREE_CLASSES
           + ((()))
           + ((()))
           + (((ORIVOT_OT_open_upgrade,))))

def menu_func(self, context):
    self.layout.menu("VIEW3D_MT_set_origin_main")


def context_menu_func(self, context):
    self.layout.menu("VIEW3D_MT_set_origin_main")


# Keymap storage
addon_keymaps = []


@persistent
def _on_load_post(*args):
    """Reset all volatile in-memory state when a new .blend file is loaded.

    Without this, _persistent_previews and _preview_cache can contain stale
    references to objects from the previous file — RNA pointers that are now
    invalid and will hard-crash Blender on next access.

    This handler is intentionally minimal: we clear caches and remove GPU
    handlers, then let the depsgraph handler re-register them naturally on the
    first viewport redraw in the new file.
    """
    global _persistent_previews, _preview_cache, _last_snap_target
    global _last_active_object_name, _cleanup_scheduled, _auto_show_timer

    _persistent_previews.clear()
    _preview_cache.clear()
    _last_snap_target.clear()
    _last_snap_normals.clear()
    _origin_clipboard.clear()
    _last_active_object_name = None
    _cleanup_scheduled = False
    _auto_show_timer = None

    # Clear edit-tool transient state (markers, track line, type-flash, axis preview, scroll memory)
    for _mod, _fn in ((linesnap, "reset_transient"), (axistransform, "reset_transient"),
                      (curvepath, "reset_transient"), (scenesnap, "reset_transient"),
                      (collision, "reset_transient"), (panelscroll, "reset_state")):
        if _mod is not None:
            try:
                getattr(_mod, _fn)()
            except Exception:
                pass

    # Clear Orivot Place transient state
    clear_snap_history()
    _handle_hover_world_pos[0] = None
    _handle_mode["running"] = False     # modal handlers do not survive a file load
    _drop_oneshot_handle_draw()
    _handle_mode["stop"] = False
    try:
        if getattr(bpy.context.scene, 'orivot_show_viewport_handles', False):
            bpy.app.timers.register(_start_handle_mode, first_interval=0.2)
    except Exception:
        pass
    _history_hud_text[0]      = None
    _mode_ind_handler[0]      = None   # handler persists but reset ref so register() re-guards correctly
    if _collision_active[0]:
        if _collision_handler[0] is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(_collision_handler[0], 'WINDOW')
            except Exception:
                pass
        _collision_handler[0] = None
        _collision_active[0]  = False

    # Remove GPU draw handlers — they hold closures that reference old data.
    # ensure_handlers() will re-add the 3D ones on the next depsgraph tick when
    # the new file's preview activates. The outliner indicator is safe to
    # re-add immediately (it only reads custom props, no scene-data access).
    remove_handlers()
    global _draw_handler_outliner
    if _draw_handler_outliner is None:
        try:
            _draw_handler_outliner = bpy.types.SpaceOutliner.draw_handler_add(
                draw_outliner_axis_indicators, (), 'WINDOW', 'POST_PIXEL')
        except Exception:
            pass


# ── Orivot tier mutual-exclusion ───────────────────────────────────────────────
# Free / Basic / Pro share operator, menu, and panel identifiers, so only one
# tier may be enabled at a time. The active tier is recorded in Blender's global
# driver namespace (persists for the session, visible to every add-on). If a
# different tier is already active, refuse to register with a clear message
# instead of crashing mid-registration on a duplicate-identifier error.
_ORIVOT_TIER = tier.LABEL

def _orivot_guard_tier():
    other = bpy.app.driver_namespace.get("_orivot_active_tier")
    if other and other != _ORIVOT_TIER:
        raise RuntimeError(
            f"Orivot {other} is already enabled. Disable it under "
            f"Edit \u203a Preferences \u203a Add-ons before enabling Orivot {_ORIVOT_TIER}. "
            f"The Orivot tiers share the same tools and can't run at the same time."
        )


def register():
    _orivot_guard_tier()
    for cls in classes:
        bpy.utils.register_class(cls)
    tier._ops.clear()
    tier._ops.update(c.bl_idname for c in classes
                     if issubclass(c, bpy.types.Operator))
    bpy.app.driver_namespace["_orivot_active_tier"] = _ORIVOT_TIER

    bpy.types.VIEW3D_MT_object.append(menu_func)
    bpy.types.VIEW3D_MT_object_context_menu.append(context_menu_func)

    # Outliner axis indicator: register immediately so it works without ever
    # enabling preview (the 3D GPU handlers are lazy — only activated by preview).
    global _draw_handler_outliner
    if _draw_handler_outliner is None:
        try:
            _draw_handler_outliner = bpy.types.SpaceOutliner.draw_handler_add(
                draw_outliner_axis_indicators, (), 'WINDOW', 'POST_PIXEL')
        except Exception:
            pass

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
        update=origin_snap_source_update
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
        update=_live_offset_update_x
    )
    bpy.types.Scene.orivot_offset_y = bpy.props.FloatProperty(
        name="Y Offset", default=0.0, unit='LENGTH', step=1, precision=4,
        description="World-space Y offset — drag to move origin live when Live Offset is enabled",
        update=_live_offset_update_y
    )
    bpy.types.Scene.orivot_offset_z = bpy.props.FloatProperty(
        name="Z Offset", default=0.0, unit='LENGTH', step=1, precision=4,
        description="World-space Z offset — drag to move origin live when Live Offset is enabled",
        update=_live_offset_update_z
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
        update=_offset_mode_update,
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
            ('CURSOR',        "3D Cursor",      "Snap to 3D cursor (no target geometry needed)"),
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
        update=_handles_toggle_update,
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
        update=keep_persistent_update
    )
    bpy.types.Scene.orivot_preview_orientation = bpy.props.EnumProperty(
        name="Preview Orientation",
        items=[
            ('LOCAL', "Local", "Preview aligned to object's local axes"),
            ('GLOBAL', "Global", "Preview aligned to world axes")
        ],
        default='LOCAL',
        description="Orientation mode for preview highlight and arrow",
        update=origin_preview_orientation_update
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
        update=origin_arrow_scale_update
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
        update=origin_arrow_scale_update
    )
    bpy.types.Scene.orivot_arrow_show_stroke = bpy.props.BoolProperty(
        name="Arrow Stroke",
        default=False,
        description="Draw an outline/halo behind the arrows. OFF by default — "
                    "enabling it adds one extra draw call (better performance off)",
        update=origin_arrow_scale_update
    )
    bpy.types.Scene.orivot_arrow_stroke_color = bpy.props.FloatVectorProperty(
        name="Stroke Color",
        subtype='COLOR',
        default=(1.0, 1.0, 1.0),
        min=0.0, max=1.0,
        description="Color of the optional arrow stroke/halo",
        update=origin_arrow_scale_update
    )
    bpy.types.Scene.orivot_arrow_stroke_width = bpy.props.FloatProperty(
        name="Stroke Width",
        default=3.0,
        min=1.0, max=12.0,
        step=10, precision=1,
        description="Thickness of the optional arrow stroke",
        update=origin_arrow_scale_update
    )
    bpy.types.Scene.orivot_arrow_stroke_opacity = bpy.props.FloatProperty(
        name="Stroke Opacity",
        default=0.5,
        min=0.0, max=1.0,
        step=5, precision=2,
        description="Opacity of the optional arrow stroke",
        update=origin_arrow_scale_update
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
        update=origin_arrow_scale_update  # Reuse same update callback to refresh preview
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
        return mom_preview_active(self)

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
        update=origin_flip_left_right_update
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
        update=origin_preview_orientation_update  # reuse — triggers preview refresh
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
        type=OriginMOCustomObject,
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

    if depsgraph_update_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(depsgraph_update_handler)

    # Register collection color change detector
    if collection_color_change_detector not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(collection_color_change_detector)

    # File-reload safety: clear stale RNA refs when a new .blend is loaded
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)

    # Register keymap for Alt+Click surface snap
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')


    if kc:
        # Alt + Q = Orivot pie menu (every edition)
        kmi = km.keymap_items.new(
            'wm.call_menu_pie',
            'Q', 'PRESS',
            alt=True
        )
        kmi.properties.name = 'VIEW3D_MT_orivot_pie'
        addon_keymaps.append((km, kmi))

    # Apply preference defaults to all currently open scenes on load/enable
    def _apply_prefs_to_scenes():
        try:
            prefs = bpy.context.preferences.addons[__name__].preferences
            for scene in bpy.data.scenes:
                scene.orivot_preview_color         = prefs.default_highlight_color
                scene.orivot_preview_alpha         = prefs.default_highlight_alpha
                scene.orivot_face_offset           = prefs.default_face_offset
                scene.orivot_arrow_scale           = prefs.default_arrow_scale
                scene.orivot_snap_source           = prefs.default_snap_source
                scene.orivot_preview_orientation   = prefs.default_orientation
                scene.orivot_front_axis            = prefs.default_front_axis
                scene.orivot_snap_auto_recalc      = prefs.default_auto_recalc
                scene.orivot_auto_show_on_hover    = prefs.default_auto_show_on_hover
                scene.orivot_show_bbox_wireframe   = prefs.default_show_bbox_wireframe
                scene.orivot_hide_arrow_when_muted = prefs.default_hide_arrow_when_muted
        except Exception:
            pass
    bpy.app.timers.register(_apply_prefs_to_scenes, first_interval=0.1)
    # a scene saved with Handles on gets its handles back when the add-on is enabled

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

    # F3+F6: Register persistent HUD and mode-indicator draw handlers
    if _history_hud_handler[0] is None:
        _history_hud_handler[0] = bpy.types.SpaceView3D.draw_handler_add(
            _draw_history_hud, (), 'WINDOW', 'POST_PIXEL')
    if _mode_ind_handler[0] is None:
        _mode_ind_handler[0] = bpy.types.SpaceView3D.draw_handler_add(
            _draw_mode_indicator, (), 'WINDOW', 'POST_PIXEL')

    # Edit-mode tools: registered last and each isolated, so a problem in one of them can
    # never take the origin tools down with it. Order matters: Axis Transform reads the lines
    # Line Snap stores, so it is only registered if Line Snap registered.
    _line_ok = False
    for _label, _mod in (("Help", _help), ("Panels", ui),
                         ("Line Snap", linesnap), ("Axis Transform", axistransform),
                         ("Orientation tools", orient), ("Fabrication", fab),
                         ("Curve Path", curvepath), ("Scene Snap", scenesnap),
                         ("Collision Preview", collision), ("Chain / Distribute", chain),
                         ("Panel scroll memory", panelscroll), ("PivotForge data", migrate)):
        if _mod is None or (_mod is axistransform and not _line_ok):
            continue
        try:
            _mod.register()
            if _mod is linesnap:
                _line_ok = True
        except Exception as exc:
            print(f"[{tier.NAME}] {_label} failed to register: {exc!r}")
            try:
                _mod.unregister()
            except Exception:
                pass

def unregister():
    if _handle_mode["running"]:
        # the Handles modal dies with the add-on and never runs its cleanup: clear its
        # status-bar hint ourselves (it stayed until another tool replaced it)
        try:
            bpy.context.workspace.status_text_set(None)
        except Exception:
            pass
    _handle_mode["stop"] = True
    _drop_oneshot_handle_draw()
    try:
        if bpy.app.timers.is_registered(_start_handle_mode):
            bpy.app.timers.unregister(_start_handle_mode)
    except Exception:
        pass
    bpy.app.driver_namespace.pop("_orivot_active_tier", None)
    for _mod in (migrate, panelscroll, chain, collision, scenesnap, curvepath, fab, orient,
                 axistransform, linesnap, ui, _help):  # reverse of registration order
        if _mod is not None:
            try:
                _mod.unregister()
            except Exception:
                pass
    global _preview_cache
    global _persistent_previews
    global _auto_show_timer
    global addon_keymaps
    global _cleanup_scheduled

    # Cancel any pending deferred-cleanup timer
    try:
        if bpy.app.timers.is_registered(_deferred_cleanup):
            bpy.app.timers.unregister(_deferred_cleanup)
    except Exception:
        pass
    _cleanup_scheduled = False

    # Remove keymaps
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    addon_keymaps.clear()

    # Cancel any pending auto-show timer
    if _auto_show_timer:
        try:
            if bpy.app.timers.is_registered(auto_show_preview_timer):
                bpy.app.timers.unregister(auto_show_preview_timer)
        except Exception:
            pass
        _auto_show_timer = None

    scene = bpy.context.scene

    _preview_cache.clear()
    _persistent_previews.clear()
    scene.orivot_show_preview = False
    remove_handlers()

    # B8: Clean up Collision Preview handler
    if _collision_handler[0] is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_collision_handler[0], 'WINDOW')
        except Exception:
            pass
        _collision_handler[0] = None
    _collision_active[0] = False

    # F3: Clean up Snap History HUD handler
    if _history_hud_handler[0] is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_history_hud_handler[0], 'WINDOW')
        except Exception:
            pass
        _history_hud_handler[0] = None

    # F6: Clean up Mode Indicator handler
    if _mode_ind_handler[0] is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_mode_ind_handler[0], 'WINDOW')
        except Exception:
            pass
        _mode_ind_handler[0] = None

    objs_to_remove = [o for o in bpy.data.objects
                      if o.name.startswith(PREVIEW_ARROW_NAME) or PREVIEW_ARROW_NAME in o.name]
    for arrow_obj in objs_to_remove:
        for col in list(arrow_obj.users_collection):
            try:
                col.objects.unlink(arrow_obj)
            except Exception:
                pass
        try:
            bpy.data.objects.remove(arrow_obj, do_unlink=True)
        except Exception:
            pass

    col = bpy.data.collections.get(PREVIEW_COLLECTION)
    if col and len(col.objects) == 0:
        try:
            bpy.context.scene.collection.children.unlink(col)
        except Exception:
            pass
        try:
            bpy.data.collections.remove(col)
        except Exception:
            pass

    try:
        bpy.types.VIEW3D_MT_object.remove(menu_func)
    except Exception:
        pass
    try:
        bpy.types.VIEW3D_MT_object_context_menu.remove(context_menu_func)
    except Exception:
        pass

    # Remove handlers (consolidated - removed duplicate code)
    try:
        bpy.app.handlers.depsgraph_update_post.remove(depsgraph_update_handler)
    except Exception:
        pass

    try:
        bpy.app.handlers.depsgraph_update_post.remove(collection_color_change_detector)
    except Exception:
        pass

    try:
        bpy.app.handlers.load_post.remove(_on_load_post)
    except Exception:
        pass
    for _lst in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if _handles_after_undo in _lst:
            _lst.remove(_handles_after_undo)

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
        except Exception:
            pass

    # classes last: the properties above still referenced some of them (property groups)
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass


if __name__ == "__main__":
    register()
