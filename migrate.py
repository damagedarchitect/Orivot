"""Bring PivotForge data in older .blend files over to Orivot.

Orivot renamed every stored key. Files made with PivotForge Pro / Fab keep working:
on file load (and when the add-on is enabled) this copies, once, and then removes:

  object keys      pivotforgepro_*         -> orivot_*          (front axis, last offset)
                   pivotforgefab_asm       -> orivot_fab_asm    (assembly snapshots)
  data keys        pivotforgepro_pivot_N   -> orivot_pivot_N    (Pivot Library)
  mesh attribute   pivotforge_fab_mark     -> orivot_fab_mark   (marked sheet faces)
  scene settings   origin_* / pivotforge_* / pivotforgeplace_* / obj_snap_*  -> orivot_*
  scene lists      Fab datums, Snap Layers (-> Saved Configurations, "This File")

Everything is idempotent and guarded: a key that already exists on the Orivot side is never
overwritten, and a value that does not fit the new setting is skipped.
"""

import bpy
from bpy.app.handlers import persistent
from . import support


# Every scene property PivotForge Pro 4.0.x registered. Only these are touched: anything
# else that happens to share a prefix (your own props, other add-ons) is left alone.
KNOWN = frozenset('''
obj_snap_align_rotation obj_snap_as_group obj_snap_source_type obj_snap_target_type
origin_arrow_color origin_arrow_scale origin_arrow_show_stroke origin_arrow_stroke_color
origin_arrow_stroke_opacity origin_arrow_stroke_width origin_auto_show_on_hover origin_copy_mode
origin_dismissed_bbox_warning origin_face_offset origin_flip_left_right origin_front_axis
origin_handle_size origin_handles_snap_type origin_hide_arrow_when_muted origin_keep_preview_persistent
origin_live_offset origin_lock_x origin_lock_y origin_lock_z
origin_mo_affect_target origin_mo_custom_objects origin_mo_global_color origin_mo_snap_mode
origin_mo_target_collection origin_multi_object_preview origin_normal_offset origin_offset_mode
origin_offset_space origin_offset_x origin_offset_y origin_offset_z
origin_preview_alpha origin_preview_color origin_preview_orientation origin_show_align
origin_show_bbox_wireframe origin_show_centers origin_show_chain_paste origin_show_csv_export
origin_show_curve_snap origin_show_edges origin_show_editmode origin_show_faces
origin_show_general_settings origin_show_global_centers origin_show_group_tools origin_show_history
origin_show_mode_indicator origin_show_named_groups origin_show_obj_snap origin_show_obj_snap_tools
origin_show_pivot_library origin_show_placement_tools origin_show_preview_controls origin_show_pro_tools
origin_show_saved_configs origin_show_scene_snap origin_show_snap_section origin_show_vertices
origin_show_viewport_handles origin_snap_auto_recalc origin_snap_source pivotforge_collision_check
pivotforge_collision_watch pivotforge_curve_by pivotforge_curve_distance pivotforge_curve_factor
pivotforge_curve_reverse pivotforge_curve_snap_tol pivotforge_curve_spline pivotforge_fab_apply_modifiers
pivotforge_fab_arc_fit pivotforge_fab_arc_tol pivotforge_fab_cut_depth pivotforge_fab_datums
pivotforge_fab_datums_index pivotforge_fab_dim_end pivotforge_fab_dim_offset pivotforge_fab_dims
pivotforge_fab_gap pivotforge_fab_grain pivotforge_fab_group_islands pivotforge_fab_hinge_axis
pivotforge_fab_kerf pivotforge_fab_label_radii pivotforge_fab_label_size pivotforge_fab_mate_offset
pivotforge_fab_min_label_radius pivotforge_fab_pack_bed_width pivotforge_fab_pack_gap pivotforge_fab_pack_orient
pivotforge_fab_part_labels pivotforge_fab_part_spacing pivotforge_fab_proj_axis pivotforge_fab_proj_marked
pivotforge_fab_relief pivotforge_fab_relief_max_angle pivotforge_fab_sheet_h pivotforge_fab_sheet_margin
pivotforge_fab_sheet_outline pivotforge_fab_sheet_preset pivotforge_fab_sheet_thickness pivotforge_fab_sheet_w
pivotforge_fab_simplify_tol pivotforge_fab_split_oversize pivotforge_fab_stl_orient pivotforge_fab_stroke
pivotforge_fab_svg_colors pivotforge_fab_text_size pivotforge_fab_thickness_tol pivotforge_fab_tick
pivotforge_fab_tool_diameter pivotforge_fab_unit_override pivotforge_fab_write_cutlist pivotforge_grid_space
pivotforge_scene_snap_target pivotforgeaxis pivotforgeline pivotforgeplace_align_axis
pivotforgeplace_chain_mode pivotforgeplace_chain_move pivotforgeplace_chain_order pivotforgeplace_chain_start
pivotforgeplace_chain_step_x pivotforgeplace_chain_step_y pivotforgeplace_chain_step_z pivotforgeplace_grid_step
pivotforgeplace_snap_layers show_origin_preview
'''.split())


def scene_key(old):
    if old not in KNOWN:
        return None
    if old in ("pivotforgeline", "pivotforgeaxis"):
        return "orivot" + old[len("pivotforge"):]
    for a, b in (("pivotforgeplace_", "orivot_"), ("pivotforge_fab_", "orivot_fab_"),
                 ("pivotforge_", "orivot_"), ("obj_snap_", "orivot_obj_snap_"),
                 ("origin_", "orivot_")):
        if old.startswith(a):
            return b + old[len(a):]
    if old == "show_origin_preview":
        return "orivot_show_preview"
    return None


def _id_keys(idb, pairs):
    n = 0
    for k in list(idb.keys()):
        for a, b in pairs:
            if k.startswith(a):
                new = b + k[len(a):]
                if new not in idb.keys():
                    idb[new] = idb[k]
                del idb[k]
                n += 1
                break
    return n


def _sys(idb):
    """Where registered (bpy.props) values live: a separate group since Blender 5.0,
    the ID's custom properties before that."""
    getter = getattr(idb, "bl_system_properties_get", None)
    if getter is not None:
        try:
            g = getter(do_create=True)
            if g is not None:
                return g
        except Exception as _exc:
            support.note(_exc)
    return idb


def _plain(v):
    """Deep copy of an ID property value into plain Python (dict / list / scalars)."""
    if hasattr(v, "to_dict"):
        return v.to_dict()
    if hasattr(v, "to_list"):
        return v.to_list()
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def _take(sc, key):
    """Pop an old raw value from custom AND system storage (a 4.x file opened in 5.x has
    it in both); returns the first copy found as plain Python, or None."""
    value = None
    for g in (sc, _sys(sc)):
        try:
            if key in g.keys():
                if value is None:
                    value = _plain(g[key])   # copy out BEFORE deleting: the items die with the key
                del g[key]
        except Exception as _exc:
            support.note(_exc)
    return value


def _scene(sc):
    n = 0
    rna = sc.bl_rna.properties
    dest = _sys(sc)
    for src in {id(sc): sc, id(dest): dest}.values():
        for k in list(src.keys()):
            if k in ("pivotforge_fab_datums", "pivotforgeplace_snap_layers"):
                continue
            new = scene_key(k)
            if new is None:
                continue
            if new in rna and new not in dest.keys():
                try:
                    dest[new] = _plain(src[k])
                    n += 1
                except Exception as _exc:
                    support.note(_exc)
            try:
                del src[k]
            except Exception as _exc:
                support.note(_exc)
    datums = _take(sc, "pivotforge_fab_datums")
    if datums and hasattr(sc, "orivot_fab_datums"):
        for it in datums:
            try:
                d = sc.orivot_fab_datums.add()
                d.name = str(it.get("name", "Datum"))
                loc = it.get("location")
                if loc is not None:
                    d.location = tuple(loc)[:3]
                n += 1
            except Exception as _exc:
                support.note(_exc)
    layers = _take(sc, "pivotforgeplace_snap_layers")
    if layers and hasattr(sc, "orivot_configs"):
        for it in layers:
            try:
                c = sc.orivot_configs.add()
                c.name = str(it.get("layer_name", "Snap Layer"))
                for f in ("offset_x", "offset_y", "offset_z", "lock_x", "lock_y", "lock_z",
                          "live_offset"):
                    if f in it:
                        setattr(c, f, it[f])
                # Snap Layers always restored everything and had no offset space
                c.save_live_offset = c.save_copy_mode = True
                c.offset_space = getattr(sc, "orivot_offset_space", 'WORLD')
                # enum values are stored as numbers in old files; strings in tests
                for f in ("snap_source", "orientation", "front_axis", "offset_mode", "copy_mode"):
                    v = it.get(f)
                    if isinstance(v, str):
                        try:
                            setattr(c, f, v)
                        except Exception as _exc:
                            support.note(_exc)
                n += 1
            except Exception as _exc:
                support.note(_exc)
    return n


def _cursor_target(sc):
    """4.3: Snap to Object lost its '3D Cursor' target (index 5) to the 3D Cursor panel.
    A scene saved with it falls back to Surface instead of an empty enum."""
    try:
        if sc.get("orivot_obj_snap_target_type") == 5:
            sc["orivot_obj_snap_target_type"] = 0
            return 1
    except Exception as _exc:
        support.note(_exc)
    return 0


def migrate_all():
    """Returns how many items were carried over (0 for an Orivot-only file)."""
    n = 0
    for sc in bpy.data.scenes:
        if sc.library is None:
            n += _cursor_target(sc)
    for ob in bpy.data.objects:
        if ob.library is not None:
            continue
        n += _id_keys(ob, (("pivotforgepro_", "orivot_"), ("pivotforgefab_asm", "orivot_fab_asm")))
    seen = set()
    for ob in bpy.data.objects:
        d = ob.data
        if d is None or d.library is not None or d.name_full in seen:
            continue
        seen.add(d.name_full)
        try:
            n += _id_keys(d, (("pivotforgepro_", "orivot_"),))
        except Exception as _exc:
            support.note(_exc)
    for me in bpy.data.meshes:
        if me.library is not None:
            continue
        a = me.attributes.get("pivotforge_fab_mark")
        if a is not None:
            if me.attributes.get("orivot_fab_mark") is None:
                a.name = "orivot_fab_mark"
            else:
                me.attributes.remove(a)
            n += 1
    for sc in bpy.data.scenes:
        if sc.library is None:
            n += _scene(sc)
    if n:
        print(f"[Orivot] carried over {n} item(s) from PivotForge data in this file")
    return n


# ---------------- 4.3.5: front is -Y (Blender's convention) ----------------
# Up to 4.3.4 the default front was +Y, so a stored +Y almost always means "the default",
# not a choice. Files are NOT changed on load: the Origin Snaps panel shows a warning and a
# Fix button (ORIVOT_OT_fix_front_axis) while a file still holds old +Y data. Everything
# written by 4.3.5 carries the axis convention (AXIS_REV), so a +Y picked on purpose later
# is never reported or converted. The preferences (not file data) are converted once.
_OLD_FRONT = 'LOCAL_Y_POS'
_NEW_FRONT = 'LOCAL_Y_NEG'
_REV = 1                                     # common.AXIS_REV
_old_count = None                            # cached scan, None = scan again


def _old_object(ob):
    return (ob.library is None and ob.override_library is None
            and ob.get('orivot_front_axis') == _OLD_FRONT
            and ob.get('orivot_front_axis_rev', 0) < _REV)


def _old_configs(coll):
    return [c for c in (coll or ()) if getattr(c, "axis_rev", _REV) < _REV
            and c.front_axis == _OLD_FRONT]


def _scan():
    n = sum(1 for ob in bpy.data.objects if _old_object(ob))
    for sc in bpy.data.scenes:
        if sc.library is None:
            n += len(_old_configs(getattr(sc, 'orivot_configs', None)))
    return n


def old_front_axis_count():
    """How many objects / saved configurations in this file still use the 4.3.4 front
    (+Y). Cached; rescanned after load, undo / redo and the Fix button."""
    global _old_count
    if _old_count is None:
        try:
            _old_count = _scan()
        except Exception as exc:
            support.note(exc)
            _old_count = 0
    return _old_count


@persistent
def _invalidate(*_):
    global _old_count
    _old_count = None


def _convert_configs(coll):
    n = 0
    for cfg in coll or ():
        if getattr(cfg, "axis_rev", _REV) >= _REV:
            continue
        if cfg.front_axis == _OLD_FRONT:
            cfg.front_axis = _NEW_FRONT
            n += 1
        cfg.axis_rev = _REV
    return n


def migrate_front_axis():
    """Objects pinned to the old +Y default and this file's Saved Configurations -> -Y,
    then every scene's Front dropdown follows its active object. Returns how many changed."""
    n = 0
    for ob in bpy.data.objects:
        if ob.library is not None or ob.override_library is not None:
            continue
        if 'orivot_front_axis' not in ob or ob.get('orivot_front_axis_rev', 0) >= _REV:
            continue
        if ob.get('orivot_front_axis') == _OLD_FRONT:
            ob['orivot_front_axis'] = _NEW_FRONT
            n += 1
        ob['orivot_front_axis_rev'] = _REV
    for sc in bpy.data.scenes:
        if sc.library is None:
            n += _convert_configs(getattr(sc, 'orivot_configs', None))
    _sync_scene_front_axes()
    _invalidate()
    if n:
        print(f"[Orivot] front is now -Y (Blender's convention): converted {n} item(s) "
              f"that used the old +Y default")
    return n


def _sync_scene_front_axes():
    """Each scene's Front dropdown = its active object's pinned axis, else the default
    (the dropdown is per active object; a file saved by 4.3.4 stored +Y there)."""
    from . import common
    for sc in bpy.data.scenes:
        if sc.library is not None or not hasattr(sc, 'orivot_front_axis'):
            continue
        try:
            act = sc.view_layers[0].objects.active if sc.view_layers else None
            want = common.get_obj_front_axis(act, sc) if act else common.default_front_axis()
            if sc.orivot_front_axis != want:
                sc.orivot_front_axis = want
        except Exception as exc:
            support.note(exc)


class ORIVOT_OT_fix_front_axis(bpy.types.Operator):
    """Switch this file to Blender's front (-Y): objects pinned to the old Orivot front (+Y)
    and Saved Configurations that stored it get -Y. Other pinned axes are kept"""
    bl_idname = "orivot.fix_front_axis"
    bl_label = "Fix Front Axis (-Y)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if old_front_axis_count():
            return True
        cls.poll_message_set("Nothing to fix: this file already uses Blender's front (-Y)")
        return False

    def execute(self, context):
        n = migrate_front_axis()
        for area in context.screen.areas if context.screen else ():
            area.tag_redraw()
        self.report({'INFO'}, f"Orivot: front is now -Y (Blender's convention), "
                              f"{n} item(s) switched from +Y")
        return {'FINISHED'}


def draw_front_axis_warning(layout):
    """The warning + Fix button in Origin Snaps while the file holds old +Y data."""
    n = old_front_axis_count()
    if not n:
        return
    box = layout.box()
    col = box.column(align=True)
    col.alert = True
    col.label(text=f"Old Orivot front (+Y) on {n} item(s)", icon='ERROR')
    col.alert = False
    col.label(text="Blender's front is -Y. Orivot 4.3.5 follows it.")
    box.operator("orivot.fix_front_axis", text="Fix: Front = -Y", icon='CHECKMARK')


def migrate_front_axis_prefs():
    """The preferences' default Front Face Axis and All-Files configurations, once."""
    try:
        p = bpy.context.preferences.addons[__package__].preferences
    except Exception:
        return 0
    if getattr(p, 'axis_rev', _REV) >= _REV:
        return 0
    n = 0
    if getattr(p, 'default_front_axis', None) == _OLD_FRONT:
        p.default_front_axis = _NEW_FRONT
        n += 1
    n += _convert_configs(getattr(p, 'configs', None))
    p.axis_rev = _REV
    try:
        bpy.context.preferences.is_dirty = True
    except Exception:
        pass
    return n


@persistent
def _on_load(*_):
    try:
        migrate_all()
    except Exception as exc:
        support.note(exc)
        print(f"[Orivot] PivotForge data migration skipped: {exc!r}")
    _invalidate()
    try:
        _sync_scene_front_axes()
    except Exception as exc:
        support.note(exc)


def _first():
    try:
        migrate_front_axis_prefs()          # before the scenes take the default from it
    except Exception as exc:
        support.note(exc)
    _on_load()
    return None


def register():
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)
    for _lst in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if _invalidate not in _lst:
            _lst.append(_invalidate)
    bpy.app.timers.register(_first, first_interval=0.3)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    for _lst in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if _invalidate in _lst:
            _lst.remove(_invalidate)
    try:
        if bpy.app.timers.is_registered(_first):
            bpy.app.timers.unregister(_first)
    except Exception as _exc:
        support.note(_exc)
