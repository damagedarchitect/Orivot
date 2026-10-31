"""Origin preview: arrows, highlight quads, bbox handles drawing, GPU overlays, depsgraph / collection-colour handlers, affected-object resolution.

Split out of __init__.py in 4.3 (tools/split_init.py)."""

import sys
import bpy
from mathutils import Vector, Matrix
import gpu
from gpu_extras.batch import batch_for_shader
from bpy.app.handlers import persistent
from bpy_extras.view3d_utils import (
    region_2d_to_vector_3d,
    region_2d_to_origin_3d,
    location_3d_to_region_2d,
)

from . import gpudraw
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


def _pkg():
    return sys.modules[__package__]


def _tag_view3d_redraw():
    """Tag all 3D viewports for redraw (robust to a missing context.screen)."""
    try:
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception as _exc:
        support.note(_exc)


def _deferred_cleanup():
    """Timer callback: run orphan-preview cleanup in a data-safe context."""
    state._cleanup_scheduled = False
    try:
        if common.cleanup_deleted_objects():
            _tag_view3d_redraw()
    except Exception as e:
        support.note(e)
        print(f"[Orivot] deferred cleanup failed: {e}")
    return None  # one-shot


def schedule_cleanup():
    """Request a deferred cleanup. Coalesces many requests into a single timer,
    so calling this every draw frame costs at most one pending timer."""
    if state._cleanup_scheduled:
        return
    state._cleanup_scheduled = True
    try:
        bpy.app.timers.register(_deferred_cleanup, first_interval=0.0)
    except Exception as _exc:
        support.note(_exc)
        state._cleanup_scheduled = False


def remove_preview_objects():
    """Clear preview state. GPU-drawn arrows need no bpy.data cleanup.
    Also sweeps for any legacy SINGLE_ARROW empties left by older versions."""

    state._preview_cache.clear()
    state._persistent_previews.clear()

    # Sweep for legacy empties (from versions before GPU-drawn arrows)
    legacy = [o for o in bpy.data.objects
              if o.name.startswith(common.PREVIEW_ARROW_NAME)]
    for o in legacy:
        for col in list(o.users_collection):
            try: col.objects.unlink(o)
            except Exception as _exc:
                support.note(_exc)
        try: bpy.data.objects.remove(o, do_unlink=True)
        except Exception as _exc:
            support.note(_exc)

    # Remove the preview collection if it exists and is now empty
    col = bpy.data.collections.get(common.PREVIEW_COLLECTION)
    if col:
        if len(col.objects) == 0:
            try: bpy.context.scene.collection.children.unlink(col)
            except Exception as _exc:
                support.note(_exc)
            try: bpy.data.collections.remove(col)
            except Exception as _exc:
                support.note(_exc)


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
    if _MOM["pass"] is not None:                # inside one depsgraph pass: computed once
        return _MOM["val"]
    try:
        n = 0
        for o in bpy.context.selected_objects:
            if o.type in common.GEOMETRY_TYPES:
                n += 1
                if n >= 2:
                    return True
        return False
    except Exception as _exc:
        support.note(_exc)
        return False


# One depsgraph update asks mom_preview_active once per previewed object; the selection
# cannot change during the pass, so the handler computes it once (4.3.3: 1600 objects
# selected = 1600 x 1600 selection walks, ~0.6 s per snap).
_MOM = {"pass": None, "val": False}


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
    except Exception as _exc:
        support.note(_exc)
        pass  # never crash the outliner


def ensure_handle_draw():
    """The bbox handle shapes (POST_PIXEL) belong to Handles, not to Preview.

    Up to 4.1.0 this hook was only installed through ensure_handlers(), i.e. when
    Preview was on: with Preview off, Handles started the click tool but drew nothing.
    """
    if state._draw_handler_2d is None:
        state._draw_handler_2d = bpy.types.SpaceView3D.draw_handler_add(
            draw_handle_shapes_2d, (), 'WINDOW', 'POST_PIXEL')


def ensure_handlers():
    if state._draw_handler_3d is None:
        state._draw_handler_3d = bpy.types.SpaceView3D.draw_handler_add(
            draw_overlay_3d, (), 'WINDOW', 'POST_VIEW')
    if state._draw_handler_2d is None:
        state._draw_handler_2d = bpy.types.SpaceView3D.draw_handler_add(
            draw_handle_shapes_2d, (), 'WINDOW', 'POST_PIXEL')
    if state._draw_handler_outliner is None:
        state._draw_handler_outliner = bpy.types.SpaceOutliner.draw_handler_add(
            draw_outliner_axis_indicators, (), 'WINDOW', 'POST_PIXEL')


def remove_handlers():
    if state._draw_handler_3d is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(state._draw_handler_3d, 'WINDOW')
        except Exception as _exc:
            support.note(_exc)
        state._draw_handler_3d = None
    if state._draw_handler_2d is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(state._draw_handler_2d, 'WINDOW')
        except Exception as _exc:
            support.note(_exc)
        state._draw_handler_2d = None
    if state._draw_handler_outliner is not None:
        try:
            bpy.types.SpaceOutliner.draw_handler_remove(state._draw_handler_outliner, 'WINDOW')
        except Exception as _exc:
            support.note(_exc)
        state._draw_handler_outliner = None


def create_or_update_preview(obj):
    """Create or update preview plane (GPU) and arrow (mesh empty) to match active object."""
    return



# ---------------- Depsgraph Handler ----------------
def _sync_active_ui():
    """Bring scene-level UI fields in line with the active object (runs from a timer).

    * Front Face Axis dropdown  -> the object's committed axis
    * Direct-mode offset fields -> the object's current origin
    """
    state._active_sync_scheduled = False
    try:
        ctx = bpy.context
        scene = ctx.scene
        obj = ctx.view_layer.objects.active if ctx.view_layer else None
        committed = common.get_obj_front_axis(obj, scene) if obj else 'LOCAL_Y_POS'
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
        support.note(e)
        print(f"[Orivot] active-object UI sync failed: {e}")
    return None


def _schedule_active_ui_sync():
    if state._active_sync_scheduled:
        return
    state._active_sync_scheduled = True
    try:
        bpy.app.timers.register(_sync_active_ui, first_interval=0.0)
    except Exception as _exc:
        support.note(_exc)
        state._active_sync_scheduled = False


@persistent
def depsgraph_update_handler(scene, depsgraph):
    """Update preview dynamically when scene changes."""

    if state._depsgraph_updating:
        return

    preview_on = False

    # ── Preview turned OFF ────────────────────────────────────────────────────
    # The draw handler already early-exits, hiding the GPU quad. But arrow mesh
    # objects persist in bpy.data until we clean them here. Do it once, cheaply,
    # by checking whether any arrows still exist.
    if not preview_on:
        if state._preview_cache or state._persistent_previews:
            state._preview_cache.clear()
            state._persistent_previews.clear()
            schedule_cleanup()   # deferred bpy.data removal — safe from here
        return

    # ── Preview ON from here ──────────────────────────────────────────────────
    ensure_handlers()
    _MOM["pass"] = None
    _MOM["val"] = mom_preview_active(scene)
    _MOM["pass"] = True
    try:
        _depsgraph_update_preview_on(scene, depsgraph)
    finally:
        _MOM["pass"] = None


def _depsgraph_update_preview_on(scene, depsgraph):
    """The preview-on part of depsgraph_update_handler (mom_preview_active cached)."""

    # NOTE: Multi-Object PREVIEW is now a DERIVED state (see mom_preview_active).
    # We deliberately do NOT mutate orivot_multi_object_preview or
    # orivot_keep_preview_persistent here. Writing scene properties from inside a
    # depsgraph callback re-enters the handler and fires their update callbacks,
    # which was the root cause of the preview/arrow/colour instability.

    obj = bpy.context.active_object

    current_name = obj.name if obj else None
    if current_name != state._last_active_object_name:
        state._last_active_object_name = current_name
        # Syncing the Front Axis dropdown / Direct-mode offset fields WRITES scene
        # properties. Doing that inside depsgraph_update_post re-enters the depsgraph
        # and fires their update callbacks, so it is deferred to a one-shot timer.
        _schedule_active_ui_sync()
        # Stamp cache immediately so draw handler shows the new object
        if obj and obj.type in common.GEOMETRY_TYPES:
            state._preview_cache['obj_name']    = current_name
            state._preview_cache['front_axis']  = common.get_obj_front_axis(obj, scene)
            state._preview_cache['orientation'] = getattr(
                scene, 'orivot_preview_orientation', 'LOCAL')

    # Auto-enable MO mode on shift-select is no longer needed — multi-object
    # preview is derived from the live selection (mom_preview_active).

    if not obj or obj.type not in common.GEOMETRY_TYPES:
        if not getattr(scene, "orivot_keep_preview_persistent", False):
            # Cache-only clear: no bpy.data mutation (and no O(N) name sweep) from
            # inside a depsgraph handler. Legacy arrow empties are swept on load.
            state._preview_cache.clear()
            state._persistent_previews.clear()
        return

    if not getattr(scene, "orivot_snap_auto_recalc", True):
        return

    state._depsgraph_updating = True
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
            except Exception as _exc:
                support.note(_exc)
            for o in bpy.context.selected_objects:
                if o is obj or o.type not in common.GEOMETRY_TYPES:
                    continue
                cached = state._persistent_previews.get(o.name)
                needs_build = (
                    cached is None
                    or 'quad_local' not in cached
                    or o.name in geo_changed
                )
                if needs_build:
                    try:
                        create_or_update_preview(o)
                    except Exception as e:
                        support.note(e)
                        print(f"[Orivot] multi preview build failed for '{o.name}': {e}")
    except Exception as e:
        support.note(e)
        print(f"[Orivot] depsgraph update failed: {e}")
    finally:
        state._depsgraph_updating = False


@persistent
def collection_color_change_detector(scene, depsgraph):
    """
    Auto-sync when Blender's collection colors change in Properties Panel.
    Only updates objects that DON'T have custom color overrides.
    Fires whenever MO preview is active (derived state — no stored flag needed).
    """

    # Only run when multi-object preview is actually visible
    if not mom_preview_active(scene):
        return

    try:
        updated_count = 0

        # Only objects that actually have a preview entry can change colour —
        # iterate those instead of every object in the file on every tick.
        for obj_name in list(state._persistent_previews.keys()):
            obj = bpy.data.objects.get(obj_name)
            if obj is None or obj.type != 'MESH':
                continue

            # Skip if object has CUSTOM color override
            custom = state._persistent_previews[obj_name].get('custom_color')
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
            blender_color = common.BLENDER_COLLECTION_COLORS.get(primary_collection.color_tag)
            if not blender_color:
                continue

            # Check if color changed
            cached_color = state._persistent_previews[obj_name].get('collection_color')

            if cached_color != blender_color:
                # Update collection color
                state._persistent_previews[obj_name]['collection_color'] = blender_color

                # Update preview if visible
                if scene.orivot_show_preview:
                    try:
                        create_or_update_preview(obj)
                    except Exception as _exc:
                        support.note(_exc)
                        pass  # intentional: try:

                updated_count += 1

        if updated_count > 0:
            _tag_view3d_redraw()

    except Exception as _exc:
        support.note(_exc)
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
            except Exception as _exc:
                support.note(_exc)
                pass  # intentional: try:


def origin_arrow_scale_update(self, context):
    """Update callback: refresh preview when arrow scale changes."""
    scene = context.scene
    if scene.orivot_show_preview:
        obj = context.active_object
        if obj and obj.type == 'MESH':
            try:
                create_or_update_preview(obj)
            except Exception as _exc:
                support.note(_exc)
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
            except Exception as _exc:
                support.note(_exc)
                pass  # intentional: try:


# ---------------- Multi-Object Target Selection ----------------
def _any_affected_mesh(context):
    """Something the Snap Points / Cursor buttons can act on (selection, list or collection)."""
    try:
        return any(o.type == 'MESH' for o in get_affected_objects(context))
    except Exception as _exc:
        support.note(_exc)
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


from . import op_origin  # noqa: E402  (load order, see __init__)
from . import support
