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
        except Exception:
            pass
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
        except Exception:
            pass
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
                except Exception:
                    pass
            try:
                del src[k]
            except Exception:
                pass
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
            except Exception:
                pass
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
                        except Exception:
                            pass
                n += 1
            except Exception:
                pass
    return n


def migrate_all():
    """Returns how many items were carried over (0 for an Orivot-only file)."""
    n = 0
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
        except Exception:
            pass
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


@persistent
def _on_load(*_):
    try:
        migrate_all()
    except Exception as exc:
        print(f"[Orivot] PivotForge data migration skipped: {exc!r}")


def _first():
    _on_load()
    return None


def register():
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)
    bpy.app.timers.register(_first, first_interval=0.3)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    try:
        if bpy.app.timers.is_registered(_first):
            bpy.app.timers.unregister(_first)
    except Exception:
        pass
