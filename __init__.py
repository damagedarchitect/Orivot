bl_info = {
    "name": "Orivot Free",
    "blender": (4, 5, 0),  # tested on 4.5 LTS, 5.0 and 5.2 LTS
    "category": "Object",
    "description": ("Origin snapping to 39 exact points on any mesh: extreme sides, corners, edge midpoints, face centres and geometry / bounding-box / mass centres, plus 3D Cursor, World Zero and an Alt+Q pie menu."),
    "author": "DaMagedArchitect",
    "version": (4, 3, 2),
    "doc_url": "https://discord.com/users/damagedarchitect",
    "tracker_url": "https://discord.com/users/damagedarchitect",
}


# Reinstalling / updating without restarting Blender re-runs this file, but Python would keep
# the old submodules (relations, grids, fab …) cached and the new __init__ would wire up stale
# code. Drop them so every `from . import x` below loads the files now on disk.
import sys as _sys
for _stale in [k for k in _sys.modules if k.startswith(__name__ + ".")]:
    del _sys.modules[_stale]
    # a reload keeps this namespace, and `from . import x` returns an existing attribute
    # without importing, so the old submodule must go from here too
    if "." not in _stale[len(__name__) + 1:]:
        globals().pop(_stale[len(__name__) + 1:], None)
# the module-level __getattr__ (defined further down) would otherwise answer `from . import x`
# with names from the OLD split modules until this file redefines it
globals().pop("__getattr__", None)
globals().pop("_SPLIT", None)

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
    from . import geo               # 4.3.2: shared bounds / normals / evaluated-mesh queries
    from . import opkit             # 4.3.2: shared operator plumbing (targets, confirm, export paths)
    from . import core              # exact origin / axis rebasing (no cursor, no bpy.ops)
    from . import meshnp            # vectorised evaluated-mesh queries
    from . import configs as _configs   # Saved Configurations (this file / all files)
    from . import help as _help     # ? buttons: animated in-panel explanations
    from . import ui                # the sidebar: Origin Snaps / Object Snaps / Settings
    from . import migrate           # carries PivotForge data in old files over to Orivot
    from . import gpudraw           # points / wide lines that also show on Vulkan & Metal
    from . import tier              # which edition this build is: Free / Basic / Pro
except ImportError:
    raise

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
from . import units                 # 4.3: output units (mm / cm / m / in / ft) for every export
try:
    from . import printprep         # 4.3: 3D Print set (Basic and up)
except ImportError:
    printprep = None
try:
    from . import cursor            # 4.3: 3D Cursor panel (Basic and up)
except ImportError:
    cursor = None
# 4.3 scene tools: Basic (health report, instance offset, presets) / Pro (the rest)
try:
    from . import scenehealth
except ImportError:
    scenehealth = None
try:
    from . import instances
except ImportError:
    instances = None
try:
    from . import presets
except ImportError:
    presets = None
try:
    from . import siterebase
except ImportError:
    siterebase = None
try:
    from . import importclean
except ImportError:
    importclean = None
try:
    from . import assets
except ImportError:
    assets = None
# 4.3 layout tools (Pro)
try:
    from . import grids
except ImportError:
    grids = None
try:
    from . import clearance
except ImportError:
    clearance = None
try:
    from . import distribute
except ImportError:
    distribute = None
try:
    from . import relations
except ImportError:
    relations = None
try:
    from . import frames
except ImportError:
    frames = None
try:
    from . import measure           # 4.3: live sizes, distances, areas, volume (Pro)
except ImportError:
    measure = None
import sys


# 4.3: the former 9.5k-line __init__.py, split by area (tools/split_init.py)
from . import state
from . import common
from . import preview
from . import op_origin
from . import op_preview
from . import op_multi
from . import op_surface
from . import op_objsnap
from . import pie
from . import op_tools
from . import op_handles
from . import op_offsets
from . import menus
from . import prefs
from . import place
from . import props
from .menus import (
    VIEW3D_MT_set_origin_centers,
    VIEW3D_MT_set_origin_edges,
    VIEW3D_MT_set_origin_faces,
    VIEW3D_MT_set_origin_main,
    VIEW3D_MT_set_origin_vertices,
)
from .op_origin import (
    ORIVOT_OT_set_origin_extreme_full,
)
from .op_tools import (
    OrivotProNamedGroup,
)
from .pie import (
    ORIVOT_OT_run_action,
    VIEW3D_MT_orivot_pie,
)
from .place import (
    ORIVOT_OT_show_shortcuts_info,
    ORIVOT_OT_snap_to_world_zero,
    ORIVOT_OT_ground,
)
from .prefs import (
    ORIVOT_OT_apply_preference_defaults,
    ORIVOT_OT_reset_pie_defaults,
    OriginMOCustomObject,
    OrivotAddonPreferences,
)
from . import support
from . import icons


_SPLIT = (state, common, preview, op_origin, op_preview, op_multi, op_surface, op_objsnap, pie,
          op_tools, op_handles, op_offsets, menus, prefs, place, props)


def __getattr__(name):
    """Old `package.<name>` lookups (ui.py, chain.py, tests ...) find the name in the
    module it moved to."""
    for _m in _SPLIT:
        if name in _m.__dict__:
            return _m.__dict__[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _pkg():
    return sys.modules[__name__]


class ORIVOT_OT_open_upgrade(bpy.types.Operator):
    """Open the Orivot store page for the next edition"""
    bl_idname = "orivot.open_upgrade"
    bl_label = "Get Orivot"
    bl_options = {'INTERNAL'}

    edition: bpy.props.EnumProperty(items=[('BASIC', "Basic", ""), ('PRO', "Pro", ""),
                                           ('FAB', "Fabricator", "")],
                                    default='PRO', options={'SKIP_SAVE'})
    dismiss: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE', 'HIDDEN'},
                                    description="Hide this heart from the sidebar for good")

    @classmethod
    def description(cls, context, properties):
        price = tier.price_text(properties.edition) if hasattr(tier, "price_text") else ""
        return cls._features(properties) + (f"\n\nPrice: {price}" if price else "")

    @classmethod
    def _features(cls, properties):
        if properties.edition == 'BASIC':
            return ("Orivot Basic adds:\n"
                    "\u2022 Surface / Vertex snap (Alt+click on the mesh)\n"
                    "\u2022 Clickable bounding-box handles\n"
                    "\u2022 Live preview of the next snap\n"
                    "\u2022 Multi-Object, Offset & Freeze\n"
                    "\u2022 Copy / Paste origin, Mirror Plane, Snap to Grid\n"
                    "\u2022 3D Cursor tools, 3D-print prep, scene health report")
        if properties.edition == 'FAB':
            return ((("Orivot Fabricator adds everything in Pro, plus:\n")) +
                    "\u2022 CNC cut files (DXF / SVG) with kerf, reliefs, true arcs\n"
                    "\u2022 Nesting on sheets, cut lists, part IDs\n"
                    "\u2022 Plans, elevations and sections (DXF / SVG / PDF)\n"
                    "\u2022 Dimensions and title blocks in the drawings\n"
                    "\u2022 Area and material schedules (CSV / XLSX)\n"
                    "\u2022 Assembly: flat-pack, mates, datums")
        return ((("Orivot Pro adds everything in Basic, plus:\n")) +
                "\u2022 Along Curve, Origin Axes, Pivot Library\n"
                "\u2022 Object Snaps: snap, drop, align, rotate\n"
                "\u2022 Line Snap and Axis Transform (Edit Mode)\n"
                "\u2022 Grids and levels, smart distribute, relations\n"
                "\u2022 Collision and clearance checks, Chain\n"
                "\u2022 Instance, site and import tools, Saved Configurations")

    def execute(self, context):
        url = {'BASIC': getattr(tier, "URL_BASIC", ""), 'PRO': getattr(tier, "URL_PRO", ""),
               'FAB': getattr(tier, "URL_FAB", "")}[self.edition]
        if url:
            bpy.ops.wm.url_open(url=url)
        if self.dismiss:            # Pro's one-time sidebar heart: never shown again
            try:
                context.preferences.addons[__name__].preferences.fab_heart_seen = True
                context.preferences.is_dirty = True
            except Exception as _exc:
                support.note(_exc)
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
    ORIVOT_OT_ground,
    ORIVOT_OT_show_shortcuts_info,
    ORIVOT_OT_run_action,
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

    state._persistent_previews.clear()
    state._preview_cache.clear()
    state._last_snap_target.clear()
    common._last_snap_normals.clear()
    state._origin_clipboard.clear()
    state._last_active_object_name = None
    state._cleanup_scheduled = False
    state._auto_show_timer = None

    # Clear edit-tool transient state (markers, track line, type-flash, axis preview, scroll memory)
    for _mod, _fn in ((linesnap, "reset_transient"), (axistransform, "reset_transient"),
                      (curvepath, "reset_transient"), (scenesnap, "reset_transient"),
                      (collision, "reset_transient"), (panelscroll, "reset_state"),
                      (clearance, "reset_transient"), (measure, "reset_transient")):
        if _mod is not None:
            try:
                getattr(_mod, _fn)()
            except Exception as _exc:
                support.note(_exc)

    # Clear Orivot Place transient state
    place.clear_snap_history()
    common._handle_hover_world_pos[0] = None
    op_handles._handle_mode["running"] = False     # modal handlers do not survive a file load
    op_handles._drop_oneshot_handle_draw()
    op_handles._handle_mode["stop"] = False
    try:
        if getattr(bpy.context.scene, 'orivot_show_viewport_handles', False):
            bpy.app.timers.register(op_handles._start_handle_mode, first_interval=0.2)
    except Exception as _exc:
        support.note(_exc)
    common._history_hud_text[0]      = None
    common._mode_ind_handler[0]      = None   # handler persists but reset ref so register() re-guards correctly
    if common._collision_active[0]:
        if common._collision_handler[0] is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(common._collision_handler[0], 'WINDOW')
            except Exception as _exc:
                support.note(_exc)
        common._collision_handler[0] = None
        common._collision_active[0]  = False

    # Remove GPU draw handlers — they hold closures that reference old data.
    # ensure_handlers() will re-add the 3D ones on the next depsgraph tick when
    # the new file's preview activates. The outliner indicator is safe to
    # re-add immediately (it only reads custom props, no scene-data access).
    preview.remove_handlers()
    if state._draw_handler_outliner is None:
        try:
            state._draw_handler_outliner = bpy.types.SpaceOutliner.draw_handler_add(
                preview.draw_outliner_axis_indicators, (), 'WINDOW', 'POST_PIXEL')
        except Exception as _exc:
            support.note(_exc)


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
    if state._draw_handler_outliner is None:
        try:
            state._draw_handler_outliner = bpy.types.SpaceOutliner.draw_handler_add(
                preview.draw_outliner_axis_indicators, (), 'WINDOW', 'POST_PIXEL')
        except Exception as _exc:
            support.note(_exc)

    props._register_props()
    if preview.depsgraph_update_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(preview.depsgraph_update_handler)

    # Register collection color change detector
    if preview.collection_color_change_detector not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(preview.collection_color_change_detector)

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
        state.addon_keymaps.append((km, kmi))
        # every pie action as an (inactive) bindable hotkey
        pie.register_action_keymaps(km, state.addon_keymaps)

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
        except Exception as _exc:
            support.note(_exc)
    bpy.app.timers.register(_apply_prefs_to_scenes, first_interval=0.1)
    # a scene saved with Handles on gets its handles back when the add-on is enabled

    # F3+F6: Register persistent HUD and mode-indicator draw handlers
    if common._history_hud_handler[0] is None:
        common._history_hud_handler[0] = bpy.types.SpaceView3D.draw_handler_add(
            place._draw_history_hud, (), 'WINDOW', 'POST_PIXEL')
    if common._mode_ind_handler[0] is None:
        common._mode_ind_handler[0] = bpy.types.SpaceView3D.draw_handler_add(
            place._draw_mode_indicator, (), 'WINDOW', 'POST_PIXEL')

    # Edit-mode tools: registered last and each isolated, so a problem in one of them can
    # never take the origin tools down with it. Order matters: Axis Transform reads the lines
    # Line Snap stores, so it is only registered if Line Snap registered.
    _line_ok = False
    for _label, _mod in (("Icons", icons), ("Support", support), ("Units", units),
                         ("Help", _help), ("Panels", ui), ("3D Cursor", cursor),
                         ("3D Print", printprep), ("Scene Health", scenehealth),
                         ("Instances", instances), ("Presets", presets),
                         ("Site Rebase", siterebase), ("Import Cleanup", importclean),
                         ("Assets", assets), ("Grids & Levels", grids),
                         ("Clearances", clearance), ("Smart Distribute", distribute),
                         ("Relations", relations), ("Frames", frames),
                         ("Measure", measure),
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
            support.note(exc)
            print(f"[{tier.NAME}] {_label} failed to register: {exc!r}")
            try:
                _mod.unregister()
            except Exception as _exc:
                support.note(_exc)


def unregister():
    if op_handles._handle_mode["running"]:
        # the Handles modal dies with the add-on and never runs its cleanup: clear its
        # status-bar hint ourselves (it stayed until another tool replaced it)
        try:
            bpy.context.workspace.status_text_set(None)
        except Exception as _exc:
            support.note(_exc)
    op_handles._handle_mode["stop"] = True
    op_handles._drop_oneshot_handle_draw()
    try:
        if bpy.app.timers.is_registered(op_handles._start_handle_mode):
            bpy.app.timers.unregister(op_handles._start_handle_mode)
    except Exception as _exc:
        support.note(_exc)
    bpy.app.driver_namespace.pop("_orivot_active_tier", None)
    for _mod in (migrate, panelscroll, chain, collision, scenesnap, curvepath, fab, orient,
                 axistransform, linesnap, measure, frames, relations, distribute, clearance, grids,
                 assets, importclean, siterebase, presets,
                 instances, scenehealth, printprep, cursor, ui, _help, units, support,
                 icons):  # reverse of registration order
        if _mod is not None:
            try:
                _mod.unregister()
            except Exception as _exc:
                support.note(_exc)

    # Cancel any pending deferred-cleanup timer
    try:
        if bpy.app.timers.is_registered(preview._deferred_cleanup):
            bpy.app.timers.unregister(preview._deferred_cleanup)
    except Exception as _exc:
        support.note(_exc)
    state._cleanup_scheduled = False

    # Remove keymaps
    for km, kmi in state.addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception as _exc:
            support.note(_exc)
    state.addon_keymaps.clear()

    # Cancel any pending auto-show timer
    if state._auto_show_timer:
        try:
            if bpy.app.timers.is_registered(menus.auto_show_preview_timer):
                bpy.app.timers.unregister(menus.auto_show_preview_timer)
        except Exception as _exc:
            support.note(_exc)
        state._auto_show_timer = None

    scene = bpy.context.scene

    state._preview_cache.clear()
    state._persistent_previews.clear()
    scene.orivot_show_preview = False
    preview.remove_handlers()

    # B8: Clean up Collision Preview handler
    if common._collision_handler[0] is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(common._collision_handler[0], 'WINDOW')
        except Exception as _exc:
            support.note(_exc)
        common._collision_handler[0] = None
    common._collision_active[0] = False

    # F3: Clean up Snap History HUD handler
    if common._history_hud_handler[0] is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(common._history_hud_handler[0], 'WINDOW')
        except Exception as _exc:
            support.note(_exc)
        common._history_hud_handler[0] = None

    # F6: Clean up Mode Indicator handler
    if common._mode_ind_handler[0] is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(common._mode_ind_handler[0], 'WINDOW')
        except Exception as _exc:
            support.note(_exc)
        common._mode_ind_handler[0] = None

    objs_to_remove = [o for o in bpy.data.objects
                      if o.name.startswith(common.PREVIEW_ARROW_NAME) or common.PREVIEW_ARROW_NAME in o.name]
    for arrow_obj in objs_to_remove:
        for col in list(arrow_obj.users_collection):
            try:
                col.objects.unlink(arrow_obj)
            except Exception as _exc:
                support.note(_exc)
        try:
            bpy.data.objects.remove(arrow_obj, do_unlink=True)
        except Exception as _exc:
            support.note(_exc)

    col = bpy.data.collections.get(common.PREVIEW_COLLECTION)
    if col and len(col.objects) == 0:
        try:
            bpy.context.scene.collection.children.unlink(col)
        except Exception as _exc:
            support.note(_exc)
        try:
            bpy.data.collections.remove(col)
        except Exception as _exc:
            support.note(_exc)

    try:
        bpy.types.VIEW3D_MT_object.remove(menu_func)
    except Exception as _exc:
        support.note(_exc)
    try:
        bpy.types.VIEW3D_MT_object_context_menu.remove(context_menu_func)
    except Exception as _exc:
        support.note(_exc)

    # Remove handlers (consolidated - removed duplicate code)
    try:
        bpy.app.handlers.depsgraph_update_post.remove(preview.depsgraph_update_handler)
    except Exception as _exc:
        support.note(_exc)

    try:
        bpy.app.handlers.depsgraph_update_post.remove(preview.collection_color_change_detector)
    except Exception as _exc:
        support.note(_exc)

    try:
        bpy.app.handlers.load_post.remove(_on_load_post)
    except Exception as _exc:
        support.note(_exc)
    for _lst in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if op_handles._handles_after_undo in _lst:
            _lst.remove(op_handles._handles_after_undo)

    props._unregister_props()

    # classes last: the properties above still referenced some of them (property groups)
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as _exc:
            support.note(_exc)


if __name__ == "__main__":
    register()
