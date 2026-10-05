"""Orivot core: exact, fast origin and axis rebasing without bpy.ops.

Every origin / axis change in Orivot Pro (and the Fab tools) goes through this
module. It replaces the old "move 3D cursor -> select one object -> bpy.ops.object.
origin_set -> restore" loop, which was O(N^2) on batches, clobbered the cursor, and had
a data-API shortcut that corrupted shape keys, children and linked duplicates.

Model
-----
An object's world geometry is  W @ v  (W = matrix_world, v = data-space vertex).
Rebasing by a data-space transform D rewrites every vertex v -> D @ v and every object
using that data W -> W @ D^-1, so  W' @ v' = W @ D^-1 @ D @ v = W @ v : nothing moves.

  * Origin move to world point P:   D = Translation(-L),  L = W^-1 @ P
  * Axis realign to new world M:    D = M^-1 @ W

Guarantees (each covered by the regression suite):
  * geometry stays put in world space, including shape keys (all key blocks move with
    the basis),
  * children stay put (parent-inverse compensation, like Blender's own origin_set),
  * linked duplicates stay put: data is transformed ONCE and every object using it is
    compensated; if two objects in one batch share data, the first one wins (Blender's
    rule) and the rest are reported,
  * the 3D cursor, selection and active object are never touched on the fast path,
  * objects in Edit Mode are handled (Object Mode for the duration, then restored),
  * O(N) for N objects: one pass, one depsgraph update at the end.

Object types whose data has no .transform() (text, metaballs, armatures, grease pencil,
hair curves, point clouds, volumes) fall back to bpy.ops.object.origin_set per object with
cursor and selection restored. Empties have no geometry: moving their origin means moving
the empty, so they are skipped.
"""

import bpy
from mathutils import Matrix, Vector

# Types whose .data exposes transform(matrix, shape_keys=...).
DATA_TRANSFORM_TYPES = {'MESH', 'CURVE', 'SURFACE', 'LATTICE'}
# Types with geometry that bpy.ops.object.origin_set can still handle.
FALLBACK_TYPES = {'FONT', 'META', 'ARMATURE', 'GPENCIL', 'GREASEPENCIL',
                  'CURVES', 'POINTCLOUD', 'VOLUME'}
# Parent types whose parent matrix is the parent's matrix_world.
_OBJECT_PARENT_TYPES = {'OBJECT', 'ARMATURE', 'LATTICE'}

EPS = 1e-12


class Result:
    """Outcome of a batch: counts plus human-readable notes for operator reports."""
    __slots__ = ("moved", "shared", "skipped", "fallback", "notes")

    def __init__(self):
        self.moved = 0       # objects rebased on the fast path
        self.shared = 0      # objects whose data was already rebased by an earlier item
        self.skipped = 0     # linked / override / empty / unsupported
        self.fallback = 0    # objects handled via bpy.ops.object.origin_set
        self.notes = []

    @property
    def total(self):
        return self.moved + self.fallback

    def summary(self):
        parts = []
        if self.shared:
            parts.append(f"{self.shared} linked duplicate(s) share data: origin set from the first")
        if self.skipped:
            parts.append(f"{self.skipped} skipped (linked library, override or no geometry)")
        return "; ".join(parts)


# ── helpers ────────────────────────────────────────────────────────────────────

def is_editable(obj):
    """True if obj and its data can be modified and saved in this file."""
    if obj is None or obj.library is not None:
        return False
    data = obj.data
    if data is None:
        return False
    if getattr(data, "library", None) is not None:
        return False
    if getattr(data, "override_library", None) is not None:
        return False
    return True


def can_fast_rebase(obj):
    return (obj is not None and obj.type in DATA_TRANSFORM_TYPES
            and hasattr(obj.data, "transform") and is_editable(obj))


def _users_index():
    """{data pointer: [objects using it]} for every object in the file (one O(N) pass)."""
    idx = {}
    for o in bpy.data.objects:
        d = o.data
        if d is not None:
            idx.setdefault(d.as_pointer(), []).append(o)
    return idx


# Custom properties on object DATA that hold data-space points. They are transformed
# with the data so they stay glued to the geometry (e.g. Pivot Library slots).
DATA_POINT_PREFIXES = ("orivot_pivot_",)


def _transform_data_points(data, D):
    try:
        for k in list(data.keys()):
            if k.startswith(DATA_POINT_PREFIXES) and not k.endswith("_label"):
                p = data[k]
                if len(p) == 3:
                    q = D @ Vector((p[0], p[1], p[2]))
                    data[k] = [q.x, q.y, q.z]
    except Exception:
        pass


def _transform_data(data, D):
    _transform_data_points(data, D)
    try:
        data.transform(D, shape_keys=True)
    except TypeError:                       # very old signature without shape_keys
        data.transform(D)
    try:
        data.update()
    except Exception:
        try:
            data.update_tag()
        except Exception:
            pass


def _compensate_user(u, Dinv, translation_only):
    """Re-place object u after its data was rebased by D. Returns (old_world, new_world)."""
    old_w = u.matrix_world.copy()
    if translation_only:
        # Exactly what Blender's origin_set does: shift loc by the basis rotation*scale.
        L = Dinv.to_translation()
        u.location = u.location + u.matrix_basis.to_3x3() @ L
    else:
        # world = P @ mpi @ basis  =>  basis' = basis @ D^-1 gives world' = world @ D^-1
        u.matrix_basis = u.matrix_basis @ Dinv
    return old_w, old_w @ Dinv


def _compensate_children(parent, old_w, new_w):
    """Keep every direct child of `parent` fixed in world space."""
    if not parent.children:
        return
    delta = new_w.inverted_safe() @ old_w
    for c in parent.children:
        if c.parent_type in _OBJECT_PARENT_TYPES:
            c.matrix_parent_inverse = delta @ c.matrix_parent_inverse


# ── mode handling ──────────────────────────────────────────────────────────────

def find_view3d(context):
    wm = getattr(context, "window_manager", None)
    if wm is None:
        return None, None, None
    for win in wm.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        return win, area, region
    return None, None, None


def run_op(context, op, **kw):
    """Call an operator with a real VIEW_3D context when one exists."""
    win, area, region = find_view3d(context)
    if win is not None:
        with context.temp_override(window=win, area=area, region=region):
            return op(**kw)
    return op(**kw)


class object_mode:
    """Context manager: Object Mode for the block, previous edit/paint mode restored after.

    Restores multi-object Edit Mode for exactly the objects that were in it.
    """
    _MAP = {'EDIT_MESH': 'EDIT', 'EDIT_CURVE': 'EDIT', 'EDIT_SURFACE': 'EDIT',
            'EDIT_LATTICE': 'EDIT', 'EDIT_ARMATURE': 'EDIT', 'EDIT_TEXT': 'EDIT',
            'EDIT_METABALL': 'EDIT', 'POSE': 'POSE', 'SCULPT': 'SCULPT',
            'PAINT_WEIGHT': 'WEIGHT_PAINT', 'PAINT_VERTEX': 'VERTEX_PAINT',
            'PAINT_TEXTURE': 'TEXTURE_PAINT', 'PARTICLE': 'PARTICLE_EDIT'}

    def __init__(self, context):
        self.context = context
        self.mode = context.mode
        self.in_mode = []
        self.active = None
        self.ok = True

    def __enter__(self):
        ctx = self.context
        if self.mode == 'OBJECT':
            return self
        self.active = ctx.view_layer.objects.active
        self.in_mode = [o for o in ctx.view_layer.objects if o.mode != 'OBJECT']
        try:
            run_op(ctx, bpy.ops.object.mode_set, mode='OBJECT')
        except Exception as e:
            print(f"[Orivot] could not enter Object Mode: {e}")
            self.ok = False
        return self

    def __exit__(self, *exc):
        ctx = self.context
        if self.mode == 'OBJECT' or not self.ok:
            return False
        restore = self._MAP.get(self.mode)
        if not restore or self.active is None:
            return False
        vl = ctx.view_layer
        sel = [o for o in ctx.selected_objects]
        try:
            for o in sel:
                o.select_set(False)
            for o in self.in_mode:
                if o.name in vl.objects:
                    o.select_set(True)
            vl.objects.active = self.active
            run_op(ctx, bpy.ops.object.mode_set, mode=restore)
        except Exception as e:
            print(f"[Orivot] could not restore {restore} mode: {e}")
        finally:
            try:
                for o in ctx.selected_objects:
                    if o not in sel and o not in self.in_mode:
                        o.select_set(False)
                for o in sel:
                    if o.name in vl.objects:
                        o.select_set(True)
            except Exception:
                pass
        return False


# ── public API ─────────────────────────────────────────────────────────────────

def rebase(context, items, translation_only=False, result=None):
    """Apply data-space transforms. items: iterable of (obj, D) with D a 4x4 Matrix.

    Must be called in Object Mode (use set_origins / set_matrices, which handle modes).
    """
    res = result or Result()
    users = None
    done = set()
    for obj, D in items:
        if not can_fast_rebase(obj):
            res.skipped += 1
            continue
        key = obj.data.as_pointer()
        if key in done:
            res.shared += 1
            continue
        done.add(key)
        if obj.data.users - (1 if obj.data.use_fake_user else 0) <= 1:
            owners = (obj,)                 # common case: no O(N) scan needed
        else:
            if users is None:
                users = _users_index()
            owners = users.get(key, (obj,))
        Dinv = D.inverted_safe()
        _transform_data(obj.data, D)
        for u in owners:
            old_w, new_w = _compensate_user(u, Dinv, translation_only)
            _compensate_children(u, old_w, new_w)
        res.moved += 1
    return res


def _native_origin_set(context, pairs, res):
    """Fallback for data without .transform(): per-object origin_set, state restored."""
    if not pairs:
        return
    scene = context.scene
    vl = context.view_layer
    saved_cursor = scene.cursor.location.copy()
    saved_sel = list(context.selected_objects)
    saved_active = vl.objects.active
    try:
        for o in saved_sel:
            o.select_set(False)
        for obj, pos in pairs:
            if obj.name not in vl.objects:
                res.skipped += 1
                continue
            obj.select_set(True)
            vl.objects.active = obj
            scene.cursor.location = pos
            try:
                run_op(context, bpy.ops.object.origin_set, type='ORIGIN_CURSOR', center='MEDIAN')
                res.fallback += 1
            except Exception as e:
                res.skipped += 1
                res.notes.append(f"{obj.name}: {e}")
            obj.select_set(False)
    finally:
        scene.cursor.location = saved_cursor
        for o in saved_sel:
            if o.name in vl.objects:
                o.select_set(True)
        if saved_active is not None and saved_active.name in vl.objects:
            vl.objects.active = saved_active


def set_origins(context, pairs):
    """Move each object's origin to a world-space point, geometry fixed.

    pairs: iterable of (obj, world_point). Returns a Result.
    """
    res = Result()
    try:
        context.view_layer.update()     # matrix_world must be current (no-op when clean)
    except Exception:
        pass
    fast, slow = [], []
    for obj, pos in pairs:
        if obj is None:
            continue
        pos = Vector(pos)
        if can_fast_rebase(obj):
            L = obj.matrix_world.inverted_safe() @ pos
            if L.length_squared < EPS:
                res.moved += 1          # already there; count it as done
                continue
            fast.append((obj, Matrix.Translation(-L)))
        elif obj.type in FALLBACK_TYPES and is_editable(obj):
            slow.append((obj, pos))
        else:
            res.skipped += 1
    if not fast and not slow:
        return res
    with object_mode(context) as m:
        if not m.ok:
            res.skipped += len(fast) + len(slow)
            return res
        rebase(context, fast, translation_only=True, result=res)
        _native_origin_set(context, slow, res)
        context.view_layer.update()
    return res


