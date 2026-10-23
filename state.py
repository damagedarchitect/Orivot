"""Mutable module-level state of Orivot (split out of __init__.py in 4.3).

Functions rebind these, so they live in one module and are always read as
`state.<name>`, never imported by value."""

from mathutils import Vector, Matrix

# Module-level handler reference
_draw_handler_3d = None

_draw_handler_2d = None   # POST_PIXEL for shaped bbox handles

_draw_handler_outliner = None  # POST_PIXEL for per-object front-axis dot in outliner

# Re-entry guard for depsgraph handler
_depsgraph_updating = False

# Track active object name to detect selection changes for front axis reset
_last_active_object_name = None

# Origin history: {obj_name: [Vector(world_pos), ...]}  max 5 per object
_origin_history: dict = {}

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

# ── Deferred cleanup (NEVER mutate blend data from a draw or depsgraph handler) ──
# Removing objects from a POST_VIEW draw callback can corrupt state or crash
# Blender. cleanup_deleted_objects() therefore must only ever run from a timer,
# which executes in a context where bpy.data mutation is safe.
_cleanup_scheduled = False

_active_sync_scheduled = False

# Keymap storage
addon_keymaps = []
