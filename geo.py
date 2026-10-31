"""Recurring geometry operations, in one place (4.3.2, every edition).

Before 4.3.2 each tool carried its own copy of these few lines, and the copies drifted:

  * world bounding box     `[o.matrix_world @ Vector(c) for c in o.bound_box]` in 24 files
  * normals to world       `M.to_3x3() @ n` in five places: wrong for any object with
                           unapplied non-uniform scale (a 45° slope on a 1 x 1 x 4 object
                           came out 62° off, so Snap to Object / Place on Surface / Surface
                           Snap tilted the object). Normals take the inverse-transpose.
  * evaluated mesh access  `evaluated_get -> to_mesh -> ... -> to_mesh_clear` 30 times,
                           each with its own try/finally (or without one)
  * nearest feature        Python loops over every vertex / edge / face (Snap to Object
                           Vertex / Edge / Face Centre): seconds on a heavy kit part

Everything here is read-only: nothing moves an origin or an object (that is core.py).
"""

import contextlib

import numpy as np

import bpy
from mathutils import Matrix, Vector

from . import support

# Object types whose bound_box describes real geometry extents. Everything else (empties,
# lights, cameras, speakers, lattices) contributes its origin point only.
GEOMETRY_TYPES = {
    'MESH', 'CURVE', 'SURFACE', 'META', 'FONT',
    'CURVES', 'POINTCLOUD', 'VOLUME', 'GPENCIL', 'GREASEPENCIL',
}


# ── transforms ──────────────────────────────────────────────────────────────────

def normal_matrix(mw):
    """3x3 matrix that takes LOCAL normals to world: the inverse-transpose of the linear part.
    (For rotation + uniform scale it equals mw.to_3x3() up to length.)"""
    return mw.to_3x3().inverted_safe().transposed()


def normal_to_world(mw, n):
    """A local surface normal as a unit world normal (zero vector stays zero)."""
    v = normal_matrix(mw) @ Vector(n)
    return v.normalized() if v.length > 1e-12 else v


# ── bounds ──────────────────────────────────────────────────────────────────────

def box_corners(lo, hi):
    """The 8 corners of the axis-aligned box lo..hi."""
    return [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]


def collection_box(col, _seen=None):
    """World (lo, hi) of everything a collection holds (recursive, nested instances included),
    or None when it holds no geometry."""
    _seen = set() if _seen is None else _seen
    if col.as_pointer() in _seen:              # a collection that (indirectly) instances itself
        return None
    _seen = _seen | {col.as_pointer()}
    pts = []
    for o in col.all_objects:
        pts += world_corners(o, _seen)
    if not pts:
        return None
    return _minmax(pts)


def _minmax(pts):
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def world_corners(obj, _seen=None):
    """World points that bound obj: the 8 bounding-box corners of a geometry object; for a
    collection instance (an empty showing a collection), the corners of what it SHOWS
    (4.3.2: before, a kit part placed as an instance counted as a 2 m display cube or a point);
    the origin of anything else (plain empties, lights, cameras)."""
    mw = obj.matrix_world
    if obj.type in GEOMETRY_TYPES:
        return [mw @ Vector(c) for c in obj.bound_box]
    if obj.type == 'EMPTY' and obj.instance_type == 'COLLECTION' \
            and obj.instance_collection is not None:
        col = obj.instance_collection
        sub = collection_box(col, _seen)
        if sub is not None:
            off = Matrix.Translation(-col.instance_offset)
            return [mw @ off @ c for c in box_corners(*sub)]
    return [mw.translation.copy()]


def world_aabb(objs):
    """(lo, hi) world axis-aligned box around one object or a list, None for none."""
    if isinstance(objs, bpy.types.Object):
        objs = (objs,)
    pts = []
    for o in objs:
        pts += world_corners(o)
    return _minmax(pts) if pts else None


# ── evaluated mesh ──────────────────────────────────────────────────────────────

@contextlib.contextmanager
def evaluated_mesh(obj, depsgraph=None, preserve_all_data_layers=False):
    """with evaluated_mesh(obj) as (me, oe): ...   modifiers / geometry nodes applied.

    `me` is None when the object has no mesh after evaluation; the temporary mesh is always
    released, even when the body raises."""
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    oe = obj.evaluated_get(dg)
    try:
        me = oe.to_mesh(preserve_all_data_layers=preserve_all_data_layers, depsgraph=dg)
    except RuntimeError as exc:              # object type without a mesh
        support.note(exc)
        me = None
    try:
        yield me, oe
    finally:
        if me is not None:
            oe.to_mesh_clear()


def _co(me):
    """Vertex positions (N, 3) float64. The generic 'position' attribute is read in one call
    (10-60x faster than MeshVertex.co); older layouts fall back to vertices.co."""
    n = len(me.vertices)
    try:
        a = me.attributes.get("position")
        if a is not None and len(a.data) == n:
            co = np.empty(n * 3, np.float32)
            a.data.foreach_get("vector", co)
            return co.reshape(n, 3).astype(np.float64)
    except Exception as _exc:
        support.note(_exc)
    co = np.empty(n * 3, np.float64)
    me.vertices.foreach_get("co", co)
    return co.reshape(n, 3)


def _world(pts, mw):
    M = np.array(mw, dtype=np.float64)
    return pts @ M[:3, :3].T + M[:3, 3]


MESHABLE = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}


def world_extent(obj, depsgraph=None):
    """TIGHT world axis-aligned box (lo, hi) of the evaluated geometry: modifiers and geometry
    nodes applied, measured on the real vertices. Unlike world_aabb (the object's local box
    turned into world space), a tilted part's box touches its geometry, so "rest on Z = 0"
    really rests (a sphere tilted 40° no longer floats 0.3 r above the floor).
    Collection instances: the real vertices of everything the instance shows (nested
    instances and members' modifiers included). Other objects: world_aabb."""
    if obj.type in MESHABLE:
        with evaluated_mesh(obj, depsgraph) as (me, oe):
            if me is not None and len(me.vertices):
                w = _world(_co(me), oe.matrix_world)
                return Vector(w.min(0).tolist()), Vector(w.max(0).tolist())
    if is_collection_instance(obj):
        box = instance_extent(obj, depsgraph)
        if box is not None:
            return box
    return world_aabb(obj)


def is_collection_instance(obj):
    return (obj.type == 'EMPTY' and obj.instance_type == 'COLLECTION'
            and obj.instance_collection is not None)


def instance_extent(empty, depsgraph=None):
    """Tight world (lo, hi) of what a collection instance shows: every instanced object's
    evaluated vertices placed by the depsgraph (so rotation, instance offset, nesting and the
    members' modifiers are all exact). None when it shows no geometry (empty collection, or the
    instancer is hidden so Blender produces no instances)."""
    dg = depsgraph or bpy.context.evaluated_depsgraph_get()
    lo = hi = None
    for inst in dg.object_instances:
        if not inst.is_instance:
            continue
        par = inst.parent
        if par is None or par.original != empty.original:
            continue
        ob = inst.object
        if ob is None or ob.type not in MESHABLE:
            continue
        mw = inst.matrix_world.copy()           # instance data is only valid in this step
        try:
            me = ob.to_mesh()
        except RuntimeError as exc:
            support.note(exc)
            continue
        try:
            if me is None or not len(me.vertices):
                continue
            w = _world(_co(me), mw)
            a, b = w.min(0), w.max(0)
        finally:
            ob.to_mesh_clear()
        lo = a if lo is None else np.minimum(lo, a)
        hi = b if hi is None else np.maximum(hi, b)
    if lo is None:
        return None
    return Vector(lo.tolist()), Vector(hi.tolist())


def bottom_centre(lo, hi):
    """Centre of the bottom face of the box lo..hi (world X / Y centre, lowest Z)."""
    return Vector(((lo.x + hi.x) * 0.5, (lo.y + hi.y) * 0.5, lo.z))


def by_depth(objs):
    """objs ordered parents first (a parent's move carries its children, so children are
    handled after it has moved)."""
    def depth(o):
        d, p = 0, o.parent
        while p is not None and d < 256:
            d, p = d + 1, p.parent
        return d
    return sorted(objs, key=depth)


# ── nearest feature ─────────────────────────────────────────────────────────────

FEATURES = ('VERTEX', 'EDGE_MIDPOINT', 'FACE_CENTER')


