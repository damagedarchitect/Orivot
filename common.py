"""Shared helpers: selection, pivot slots, origin history, bbox / front-axis maths, extreme-point queries, colour presets.

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

from . import core
from . import geo
from . import meshnp
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


def _pkg():
    return sys.modules[__package__]


# ---------------- Constants ----------------
EPS = 1e-9


PREVIEW_ARROW_NAME = "Orivot_Preview_Arrow"


PREVIEW_COLLECTION = "Orivot_Preview_Col"


ORIGIN_HISTORY_MAX = 5


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


def _record_history(obj):
    """Push current world origin onto obj's history stack (max 5)."""
    pos = obj.matrix_world.translation.copy()
    stack = state._origin_history.setdefault(obj.name, [])
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
    except Exception as _exc:
        support.note(_exc)
    # Auto-record every successful snap into Orivot Place Snap History
    try:
        place.push_snap_history(obj.name, Vector(world_pos))
    except Exception as _exc:
        support.note(_exc)
    return res


def _apply_origins_batch(context, pairs):
    """Batch form of _apply_origin for many objects: one pass, one depsgraph update."""
    res = core.set_origins(context, pairs)
    for obj, pos in pairs:
        try:
            place.push_snap_history(obj.name, Vector(pos))
        except Exception as _exc:
            support.note(_exc)
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
    state._last_snap_target[obj.name] = Vector((0, 0, 0))

    if scene.orivot_show_preview:
        try:
            preview.create_or_update_preview(obj)
        except Exception as _exc:
            support.note(_exc)
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
    except Exception as _exc:
        support.note(_exc)
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


# 4.3.2: one definition, in geo.py (instances count by what they show).
GEOMETRY_TYPES = geo.GEOMETRY_TYPES


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
                support.note(e)
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
                support.note(e)
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
                except Exception as _exc:
                    support.note(_exc)
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
            support.note(e)
            print(f"[Origin Snap] Error calculating centroid: {e}")
            continue
        finally:
            # release evaluated mesh if any
            if obj_eval and mesh:
                try:
                    obj_eval.to_mesh_clear()
                except Exception as _exc:
                    support.note(_exc)
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

    valid_names = {obj.name for obj in bpy.data.objects if obj.type == 'MESH'}
    orphaned = []
    renames  = {}  # old_key -> new_key

    for key in list(state._persistent_previews.keys()):
        if key in valid_names:
            continue
        # May be a rename: if an object with this key still physically exists
        # but Blender already updated its .name, the stashed _obj_ref will
        # reveal the new name.
        obj_ref = state._persistent_previews[key].get('_obj_ref')
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
        state._persistent_previews[new_key] = state._persistent_previews.pop(old_key)

    for obj_name in orphaned:
        data = state._persistent_previews.pop(obj_name, {})
        arrow = data.get('arrow')
        if arrow:
            try:
                if arrow.name in bpy.data.objects:
                    for col in list(arrow.users_collection):
                        try:
                            col.objects.unlink(arrow)
                        except Exception as _exc:
                            support.note(_exc)
                    try:
                        bpy.data.objects.remove(arrow, do_unlink=True)
                    except Exception as _exc:
                        support.note(_exc)
            except ReferenceError:
                pass

    return bool(orphaned) or bool(renames)


from . import preview  # noqa: E402  (load order, see __init__)
from . import place  # noqa: E402  (load order, see __init__)
from . import support
