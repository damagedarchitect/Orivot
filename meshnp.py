"""Vectorised (numpy) evaluated-mesh queries for Orivot snap targets.

The pre-4.0 code copied every vertex into Python Vector objects, several times per
click (e.g. FACE_TOP on a 1M-vertex mesh took ~5.6 s). Everything here reads the
evaluated mesh once with foreach_get and answers the question with array math.

Inside `with session():` evaluated arrays are cached per object, so a batch operation
that asks several questions of the same object evaluates it once.
"""

import contextlib

import bpy
import numpy as np
from mathutils import Matrix, Vector

AXIS = {'X': 0, 'Y': 1, 'Z': 2}

_cache = None          # dict while a session is open, else None
_depth = 0


@contextlib.contextmanager
def session():
    global _cache, _depth
    if _depth == 0:
        _cache = {}
    _depth += 1
    try:
        yield
    finally:
        _depth -= 1
        if _depth == 0:
            _cache = None


class MeshArrays:
    __slots__ = ("co", "mw", "_poly", "_obj")

    def __init__(self, co, mw, obj):
        self.co = co            # (N,3) float64, object-local (evaluated)
        self.mw = mw            # Matrix, evaluated matrix_world
        self._poly = None
        self._obj = obj

    @property
    def m3(self):
        return np.array(self.mw.to_3x3(), dtype=np.float64)

    @property
    def t(self):
        return np.array(self.mw.translation, dtype=np.float64)

    def world(self):
        return self.co @ self.m3.T + self.t

    def polys(self):
        return self._poly


def _eval(obj):
    ctx = bpy.context
    try:
        ctx.view_layer.update()
    except Exception:
        pass
    dg = ctx.evaluated_depsgraph_get()
    oe = obj.evaluated_get(dg)
    me = oe.to_mesh()
    return oe, me


def _read_attr(me, name, field, dtype, size):
    """Generic-attribute read: 10-60x faster than MeshVertex/MeshLoop foreach_get."""
    try:
        a = me.attributes.get(name)
        if a is None or len(a.data) * (3 if field == "vector" else 1) != size:
            return None
        out = np.empty(size, dtype)
        a.data.foreach_get(field, out)
        return out
    except Exception:
        return None


def _read_polys(me):
    """Topology only (ints are cheap to read). Centers/areas are computed on demand
    for the few polygons a query selects, not read for every face."""
    if True:
        n = len(me.polygons)
        if n == 0:
            return None
        nl = len(me.loops)
        ls = np.empty(n, np.int32); me.polygons.foreach_get("loop_start", ls)
        lv = _read_attr(me, ".corner_vert", "value", np.int32, nl)
        if lv is None:
            lv = np.empty(nl, np.int32); me.loops.foreach_get("vertex_index", lv)
        if n > 1 and np.any(np.diff(ls) <= 0):
            # Blender 4+ stores faces as monotonic offsets; handle anything exotic.
            lt = np.empty(n, np.int32); me.polygons.foreach_get("loop_total", lt)
            order = np.argsort(ls, kind="stable")
            ls, lt = ls[order], lt[order]
        else:
            lt = np.diff(np.append(ls, nl)).astype(np.int32)
        return dict(loop_start=ls, loop_total=lt, loop_vert=lv)


def _poly_centers_areas(P, pts, sel):
    """World centers (vertex mean) and exact areas (Newell) of selected polygons.

    pts: (N,3) vertex positions already in the space areas should be measured in.
    """
    ls = P["loop_start"][sel]
    lt = P["loop_total"][sel]
    lv = P["loop_vert"]
    # corner index arrays for just the selected polygons
    counts = lt
    starts = np.repeat(ls, counts)
    offs = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
    idx = starts + offs
    nxt = starts + (offs + 1) % np.repeat(counts, counts)
    a = pts[lv[idx]]
    b = pts[lv[nxt]]
    first = np.cumsum(counts) - counts          # corners are contiguous per polygon
    cen = np.add.reduceat(a, first, axis=0) / counts[:, None]
    cr = np.add.reduceat(np.cross(a, b), first, axis=0)
    area = 0.5 * np.linalg.norm(cr, axis=1)
    return cen, area


def arrays(obj):
    """MeshArrays for obj's evaluated mesh, or None if it has no vertices."""
    key = obj.as_pointer()
    if _cache is not None and key in _cache:
        return _cache[key]
    oe, me = _eval(obj)
    try:
        n = len(me.vertices)
        if n == 0:
            res = None
        else:
            co = _read_attr(me, "position", "vector", np.float32, n * 3)
            if co is None:
                co = np.empty(n * 3, np.float32)
                me.vertices.foreach_get("co", co)
            res = MeshArrays(co.reshape(-1, 3).astype(np.float64), oe.matrix_world.copy(), obj)
            res._poly = _read_polys(me)     # same evaluation; ~50 ms per 1M faces
    finally:
        oe.to_mesh_clear()
    if _cache is not None:
        _cache[key] = res
    return res


def _vec(a):
    return Vector((float(a[0]), float(a[1]), float(a[2])))


def extreme_vertices(obj):
    """(min_x, max_x, min_y, max_y, min_z, max_z) as local Vectors — the vertex holding
    each extreme (same semantics as min(verts, key=...))."""
    A = arrays(obj)
    if A is None:
        return None
    co = A.co
    out = []
    for ax in range(3):
        out.append(_vec(co[int(np.argmin(co[:, ax]))]))
        out.append(_vec(co[int(np.argmax(co[:, ax]))]))
    return tuple(out)


def closest_vertex_world(obj, ideal_local):
    A = arrays(obj)
    if A is None:
        return None
    d2 = ((A.co - np.array(ideal_local, dtype=np.float64)) ** 2).sum(axis=1)
    return A.mw @ _vec(A.co[int(np.argmin(d2))])


def mean_world(obj):
    A = arrays(obj)
    if A is None:
        return None
    return A.mw @ _vec(A.co.mean(axis=0))


def edge_midpoint_extreme(obj, axis1, extreme1, axis2, extreme2):
    A = arrays(obj)
    if A is None:
        return None
    co = A.co
    dims = co.max(axis=0) - co.min(axis=0)
    tol = float(dims.max()) * 1e-4 + 1e-6
    a1, a2 = AXIS[axis1], AXIS[axis2]
    e1 = co[:, a1].max() if extreme1 == 'max' else co[:, a1].min()
    e2 = co[:, a2].max() if extreme2 == 'max' else co[:, a2].min()
    m = (np.abs(co[:, a1] - e1) < tol) & (np.abs(co[:, a2] - e2) < tol)
    if not m.any():
        return None
    return A.mw @ _vec(co[m].mean(axis=0))


def _polys_all_in(P, vmask):
    corner = vmask[P["loop_vert"]].astype(np.int8)
    return np.minimum.reduceat(corner, P["loop_start"]).astype(bool)


def face_centroid_extreme(obj, axis, extreme='max'):
    """Area-weighted centroid (world) of polygons lying at a LOCAL-axis extreme."""
    A = arrays(obj)
    if A is None:
        return None
    P = A.polys()
    if P is None:
        return None
    co = A.co
    ax = AXIS[axis]
    others = [i for i in range(3) if i != ax]
    ext = co[:, ax].max() if extreme == 'max' else co[:, ax].min()
    ext_range = co.max(axis=0) - co.min(axis=0)
    tol_basis = max(float(ext_range[others].max()), 1e-6)
    tol = tol_basis * 1e-4 + 1e-6
    vmask = np.abs(co[:, ax] - ext) <= tol
    sel = _polys_all_in(P, vmask)
    if sel.any():
        cen_w, area = _poly_centers_areas(P, A.world(), sel)
        area = np.where(area <= 1e-9, 1.0, area)
        return _vec((cen_w * area[:, None]).sum(axis=0) / area.sum())
    tol2 = tol_basis * 1e-3 + 1e-6
    layer = np.abs(co[:, ax] - ext) < tol2
    if layer.any():
        return A.mw @ _vec(co[layer].mean(axis=0))
    return None


def combined_face_centroid(objects, axis, extreme='max'):
    """World-space area-weighted centroid of faces at the combined WORLD extreme."""
    ax = AXIS[axis]
    data = []
    g = None
    for obj in objects:
        if obj.type != 'MESH':
            continue
        A = arrays(obj)
        if A is None:
            continue
        w = A.world()
        e = w[:, ax].max() if extreme == 'max' else w[:, ax].min()
        g = e if g is None else (max(g, e) if extreme == 'max' else min(g, e))
        data.append((A, w))
    if g is None:
        return None
    total = 0.0
    acc = np.zeros(3)
    fallback = []
    for A, w in data:
        others = [i for i in range(3) if i != ax]
        rng = w.max(axis=0) - w.min(axis=0)
        tol = max(float(rng[others].max()), 1e-6) * 1e-3 + 1e-6
        vmask = np.abs(w[:, ax] - g) < tol
        if vmask.any():
            fallback.append(w[vmask])
        P = A.polys()
        if P is None or not vmask.any():
            continue
        sel = _polys_all_in(P, vmask)
        if not sel.any():
            continue
        cen_w, area = _poly_centers_areas(P, w, sel)
        area = np.where(area <= 1e-9, 1.0, area)
        acc += (cen_w * area[:, None]).sum(axis=0)
        total += float(area.sum())
    if total > 0:
        return _vec(acc / total)
    if fallback:
        return _vec(np.concatenate(fallback).mean(axis=0))
    return None


def combined_closest_vertex(objects, ideal_world):
    best = None
    bd = None
    iw = np.array(ideal_world, dtype=np.float64)
    for obj in objects:
        if obj.type != 'MESH':
            continue
        A = arrays(obj)
        if A is None:
            continue
        w = A.world()
        d2 = ((w - iw) ** 2).sum(axis=1)
        i = int(np.argmin(d2))
        if bd is None or d2[i] < bd:
            bd = float(d2[i]); best = w[i]
    return _vec(best) if best is not None else None


def _tri_fans(P):
    """Fan-triangulate every polygon: (a_idx, b_idx, c_idx) vertex index arrays."""
    ls, lt, lv = P["loop_start"], P["loop_total"], P["loop_vert"]
    ntri = np.maximum(lt - 2, 0)
    if ntri.sum() == 0:
        return None
    poly = np.repeat(np.arange(len(ls)), ntri)
    k = np.arange(ntri.sum()) - np.repeat(np.cumsum(ntri) - ntri, ntri) + 1   # 1..n-2
    start = ls[poly]
    return lv[start], lv[start + k], lv[start + k + 1]


def volume_centroid_world(obj):
    """(signed volume, world centroid) of the evaluated mesh, like Blender's
    'Origin to Center of Mass (Volume)'. Open / flat meshes (volume ~0) fall back to
    the area-weighted surface centre, then to the vertex mean. Returns (0.0, None)
    when the object has no vertices."""
    A = arrays(obj)
    if A is None:
        return 0.0, None
    W = A.world()
    ref = W.mean(axis=0)
    P = A.polys()
    tris = _tri_fans(P) if P is not None else None
    if tris is None:
        return 0.0, _vec(ref)
    a, b, c = W[tris[0]] - ref, W[tris[1]] - ref, W[tris[2]] - ref
    v6 = np.einsum("ij,ij->i", a, np.cross(b, c))              # 6 x signed tet volume
    vol6 = v6.sum()
    scale = max(float(np.abs(W - ref).max()), 1e-9) ** 3
    if abs(vol6) > 1e-9 * scale:
        cen = (v6[:, None] * (a + b + c)).sum(axis=0) / (4.0 * vol6) + ref
        return vol6 / 6.0, _vec(cen)
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    if area.sum() > 0:
        cen = (area[:, None] * (a + b + c) / 3.0).sum(axis=0) / area.sum() + ref
        return 0.0, _vec(cen)
    return 0.0, _vec(ref)


def combined_mean_world(objects):
    """Vertex-weighted mean of all evaluated vertices of several objects (world)."""
    tot, n = np.zeros(3), 0
    for obj in objects:
        A = arrays(obj) if obj.type == 'MESH' else None
        if A is None:
            continue
        W = A.world()
        tot += W.sum(axis=0)
        n += len(W)
    return _vec(tot / n) if n else None


def combined_volume_centroid(objects):
    """Volume-weighted centre of mass of several meshes (world). Falls back to the
    mean of the individual centres when the total volume is ~0."""
    parts = [volume_centroid_world(o) for o in objects if o.type == 'MESH']
    parts = [(v, c) for v, c in parts if c is not None]
    if not parts:
        return None
    tv = sum(abs(v) for v, _ in parts)
    if tv > 0:
        acc = Vector((0.0, 0.0, 0.0))
        for v, c in parts:
            acc += c * abs(v)
        return acc / tv
    acc = Vector((0.0, 0.0, 0.0))
    for _v, c in parts:
        acc += c
    return acc / len(parts)


# ── Face centres on the real surface ─────────────────────────────────────────

def _axis_ray_hit(pts, P, ax, uv, extreme):
    """First surface met by a ray running along axis `ax` through the point `uv` (the two
    other coordinates), coming from the + side ('max') or the - side ('min').
    pts: (N,3) vertex positions; P: polygon topology. Pure numpy: candidate triangles are
    those whose 2D extent contains the point; then an exact 2D barycentric test. Returns the
    hit as a (3,) array or None. ~50 ms on a 1M-triangle mesh (a BVH build took ~1.7 s)."""
    tris = _tri_fans(P) if P is not None else None
    if tris is None:
        return None
    u, v = [i for i in range(3) if i != ax]
    A, B, Cc = pts[tris[0]], pts[tris[1]], pts[tris[2]]
    pu, pv = float(uv[0]), float(uv[1])
    lo_u = np.minimum(np.minimum(A[:, u], B[:, u]), Cc[:, u])
    hi_u = np.maximum(np.maximum(A[:, u], B[:, u]), Cc[:, u])
    lo_v = np.minimum(np.minimum(A[:, v], B[:, v]), Cc[:, v])
    hi_v = np.maximum(np.maximum(A[:, v], B[:, v]), Cc[:, v])
    span = float(max(np.ptp(pts[:, u]), np.ptp(pts[:, v]), 1e-9))
    eps = span * 1e-7
    m = (lo_u - eps <= pu) & (pu <= hi_u + eps) & (lo_v - eps <= pv) & (pv <= hi_v + eps)
    if not m.any():
        return None
    A, B, Cc = A[m], B[m], Cc[m]
    x0, y0 = A[:, u], A[:, v]
    x1, y1 = B[:, u] - x0, B[:, v] - y0
    x2, y2 = Cc[:, u] - x0, Cc[:, v] - y0
    den = x1 * y2 - x2 * y1
    ok = np.abs(den) > 1e-18                       # skip triangles seen edge-on
    if not ok.any():
        return None
    A, B, Cc = A[ok], B[ok], Cc[ok]
    x0, y0, x1, y1, x2, y2, den = x0[ok], y0[ok], x1[ok], y1[ok], x2[ok], y2[ok], den[ok]
    qx, qy = pu - x0, pv - y0
    s1 = (qx * y2 - x2 * qy) / den
    s2 = (x1 * qy - qx * y1) / den
    tol = 1e-9
    inside = (s1 >= -tol) & (s2 >= -tol) & (s1 + s2 <= 1 + tol)
    if not inside.any():
        return None
    w = A[inside, ax] + s1[inside] * (B[inside, ax] - A[inside, ax]) + s2[inside] * (Cc[inside, ax] - A[inside, ax])
    depth = float(w.max() if extreme == 'max' else w.min())
    out = np.empty(3)
    out[ax], out[u], out[v] = depth, pu, pv
    return out


def surface_center_world(obj, axis, extreme):
    """The point on the mesh surface in the middle of one side (local axes): straight in
    from outside, through the centre of that bounding-box face. A plain box gives its face
    centre, a sphere its pole, a gable roof the middle of its ridge. None when nothing is
    there (e.g. a ring seen down its hole)."""
    A = arrays(obj)
    if A is None:
        return None
    co = A.co
    ax = AXIS[axis]
    c = (co.min(axis=0) + co.max(axis=0)) / 2.0
    uv = [c[i] for i in range(3) if i != ax]
    hit = _axis_ray_hit(co, A.polys(), ax, uv, extreme)
    return (A.mw @ _vec(hit)) if hit is not None else None


def combined_world_points(objects):
    """All evaluated vertices of several meshes in world space, (N,3)."""
    out = [arrays(o).world() for o in objects if o.type == 'MESH' and arrays(o) is not None]
    return np.concatenate(out) if out else None


def combined_surface_center(objects, axis, extreme, lo, hi):
    """Group version of surface_center_world in WORLD axes: straight in through the centre
    of the group's box face (lo / hi = group bounds); the outermost surface of any object."""
    ax = AXIS[axis]
    c = (np.asarray(lo, dtype=np.float64) + np.asarray(hi, dtype=np.float64)) / 2.0
    uv = [c[i] for i in range(3) if i != ax]
    best = None
    for obj in objects:
        if obj.type != 'MESH':
            continue
        A = arrays(obj)
        if A is None:
            continue
        hit = _axis_ray_hit(A.world(), A.polys(), ax, uv, extreme)
        if hit is None:
            continue
        if best is None or (hit[ax] > best[ax] if extreme == 'max' else hit[ax] < best[ax]):
            best = hit
    return _vec(best) if best is not None else None


def combined_edge_midpoint(objects, axis1, extreme1, axis2, extreme2):
    """Group version of edge_midpoint_extreme in WORLD axes: the mean of the vertices that
    sit on both group extremes. None if no vertex does (the two extremes come from
    different objects)."""
    W = combined_world_points(objects)
    if W is None or len(W) == 0:
        return None
    dims = W.max(axis=0) - W.min(axis=0)
    tol = float(dims.max()) * 1e-4 + 1e-6
    a1, a2 = AXIS[axis1], AXIS[axis2]
    e1 = W[:, a1].max() if extreme1 == 'max' else W[:, a1].min()
    e2 = W[:, a2].max() if extreme2 == 'max' else W[:, a2].min()
    m = (np.abs(W[:, a1] - e1) < tol) & (np.abs(W[:, a2] - e2) < tol)
    if not m.any():
        return None
    return _vec(W[m].mean(axis=0))
