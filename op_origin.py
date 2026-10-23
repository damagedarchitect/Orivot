"""Origin snap operator (39 points) plus preview / colour / Multi-Object operators.

Split out of __init__.py in 4.3 (tools/split_init.py)."""

import sys
import bpy
from mathutils import Vector, Matrix
from gpu_extras.batch import batch_for_shader
import math
from bpy.app.handlers import persistent
from bpy_extras.view3d_utils import (
    region_2d_to_vector_3d,
    region_2d_to_origin_3d,
    location_3d_to_region_2d,
)

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
from . import common
from . import preview
from . import support


def _pkg():
    return sys.modules[__package__]


class ORIVOT_OT_set_origin_extreme_full(bpy.types.Operator):
    """Set origin to geometry extremes (local-axis aware when Mesh mode selected)."""
    bl_idname = "orivot.set_origin_extreme_full"
    @classmethod
    def poll(cls, context):
        # greyed out (with the reason as tooltip) when it cannot act on the selection
        if preview._any_affected_mesh(context):
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
            self.landed_info = preview._snap_info_json(context.scene, self.get_mode_description(context),
                                               self._landed_info)
        except Exception as _exc:
            support.note(_exc)
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
        except Exception as _exc:
            support.note(_exc)
            info = None
        if not info:
            layout.label(text="Snap origin")
            return
        layout.label(text=info["desc"], icon='OBJECT_ORIGIN')
        return

    def _execute(self, context):
        scene = context.scene
        source = scene.orivot_snap_source

        affected_objects = preview.get_affected_objects(context)

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
                common._record_history(obj)
                final = common._apply_lock_and_offset(obj, target_world, scene, frame_obj=frame)
                self._note_landing(obj, target_world, final)
                pairs.append((obj, final))
            res = common._apply_origins_batch(context, pairs)
            for obj, _p in pairs:
                state._last_snap_target[obj.name] = Vector((0, 0, 0))
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
                target_world = common._apply_lock_and_offset(obj, target_world, scene)
                self._note_landing(obj, raw, target_world)
                common._record_history(obj)
                pairs.append((obj, target_world))
            self._landed = {obj.name: p.copy() for obj, p in pairs}
            res = common._apply_origins_batch(context, pairs)
            for obj, _p in pairs:
                state._last_snap_target[obj.name] = Vector((0, 0, 0))
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
                    preview.create_or_update_preview(obj)
                except Exception as _exc:
                    support.note(_exc)
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
                common._last_snap_normals[aobj.name] = nw

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
            corners = [o.matrix_world @ v for o in meshes for v in common.get_bbox_local(o)]
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
            corners = [o.matrix_world @ v for o in meshes for v in common.get_bbox_local(o)]
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
                return common.get_combined_face_centroid(meshes, axis, ext, source)
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
            verts_local = common.get_bbox_local(obj)
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
                t = common.face_centroid_extreme(obj, 'Z', 'max')
                target_world = t if t is not None else common.local_to_world(obj,
                                                                      Vector((xmid_local, ymid_local, max_z_local.z)))
            else:
                target_world = common.local_to_world(obj, Vector((xmid_local, ymid_local, max_z_local.z)))

        elif self.mode == "FACE_BOTTOM":
            if source == 'MESH':
                t = common.face_centroid_extreme(obj, 'Z', 'min')
                target_world = t if t is not None else common.local_to_world(obj,
                                                                      Vector((xmid_local, ymid_local, min_z_local.z)))
            else:
                target_world = common.local_to_world(obj, Vector((xmid_local, ymid_local, min_z_local.z)))

        elif self.mode == "FACE_LEFT":
            if scene.orivot_flip_left_right:
                if source == 'MESH':
                    t = common.face_centroid_extreme(obj, 'X', 'min')
                    target_world = t if t is not None else common.local_to_world(obj, Vector(
                        (min_x_local.x, ymid_local, zmid_local)))
                else:
                    target_world = common.local_to_world(obj, Vector((min_x_local.x, ymid_local, zmid_local)))
            else:
                if source == 'MESH':
                    t = common.face_centroid_extreme(obj, 'X', 'max')
                    target_world = t if t is not None else common.local_to_world(obj, Vector(
                        (max_x_local.x, ymid_local, zmid_local)))
                else:
                    target_world = common.local_to_world(obj, Vector((max_x_local.x, ymid_local, zmid_local)))

        elif self.mode == "FACE_RIGHT":
            if scene.orivot_flip_left_right:
                if source == 'MESH':
                    t = common.face_centroid_extreme(obj, 'X', 'max')
                    target_world = t if t is not None else common.local_to_world(obj, Vector(
                        (max_x_local.x, ymid_local, zmid_local)))
                else:
                    target_world = common.local_to_world(obj, Vector((max_x_local.x, ymid_local, zmid_local)))
            else:
                if source == 'MESH':
                    t = common.face_centroid_extreme(obj, 'X', 'min')
                    target_world = t if t is not None else common.local_to_world(obj, Vector(
                        (min_x_local.x, ymid_local, zmid_local)))  # Use min_x for fallback
                else:
                    target_world = common.local_to_world(obj, Vector((min_x_local.x, ymid_local, zmid_local)))  # Use min_x for bbox

        elif self.mode == "FACE_FRONT":
            if source == 'MESH':
                t = common.face_centroid_extreme(obj, 'Y', 'max')
                target_world = t if t is not None else common.local_to_world(obj,
                                                                      Vector((xmid_local, max_y_local.y, zmid_local)))
            else:
                target_world = common.local_to_world(obj, Vector((xmid_local, max_y_local.y, zmid_local)))

        elif self.mode == "FACE_BACK":
            if source == 'MESH':
                t = common.face_centroid_extreme(obj, 'Y', 'min')
                target_world = t if t is not None else common.local_to_world(obj,
                                                                      Vector((xmid_local, min_y_local.y, zmid_local)))
            else:
                target_world = common.local_to_world(obj, Vector((xmid_local, min_y_local.y, zmid_local)))

        # --- Vertices ---
        elif self.mode.startswith("VERT_"):
            ideal_local = self.get_vertex_ideal_local(scene, min_x_local, max_x_local, min_y_local, max_y_local,
                                                        min_z_local, max_z_local)
            if source == 'MESH':
                t = meshnp.closest_vertex_world(obj, ideal_local)
                target_world = t if t is not None else common.local_to_world(obj, ideal_local)
            else:
                target_world = common.local_to_world(obj, ideal_local)

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
                    t = common.edge_midpoint_extreme(obj, axis1, extreme1, axis2, extreme2)
                    target_world = t if t is not None else common.local_to_world(obj, ideal_local)
                else:
                    target_world = common.local_to_world(obj, ideal_local)
            else:
                # In BBox mode: use exact calculated midpoint position
                target_world = common.local_to_world(obj, ideal_local)

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
                target_world = t if t is not None else common.local_to_world(obj, ideal_local)
            else:
                # In BBox mode: use exact calculated face center position
                target_world = common.local_to_world(obj, ideal_local)

        # --- Global Centers ---
        elif self.mode == "CENTER_GEOMETRY":
            # Center of Geometry (median point - average of all vertices)
            if source == 'MESH':
                t = meshnp.mean_world(obj)
                target_world = t if t is not None else common.local_to_world(
                    obj, Vector((xmid_local, ymid_local, zmid_local)))
            else:
                # BBox mode: use bbox center
                target_world = common.local_to_world(obj, Vector((xmid_local, ymid_local, zmid_local)))

        elif self.mode == "CENTER_BBOX":
            # Center of BBox (geometric center of bounds - works in both modes)
            target_world = common.local_to_world(obj, Vector((xmid_local, ymid_local, zmid_local)))

        elif self.mode == "CENTER_MASS":
            # Centre of mass (volume), computed here so Offset & Freeze and Combined mode
            # apply like every other snap. Up to 4.1.0 this called Blender's own
            # operator, which skipped both and ignored Combined.
            _v, t = meshnp.volume_centroid_world(obj)
            target_world = t if t is not None else common.local_to_world(
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
