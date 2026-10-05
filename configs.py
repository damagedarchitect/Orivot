"""Orivot Saved Configurations: one list of named setting snapshots.

Replaces two near-identical systems from PivotForge: "Saved Configurations" (5 fixed slots
in the add-on preferences) and "Snap Layers" (unlimited, inside the .blend). Each saved
configuration now has a scope:

    All files   stored in the add-on preferences (available in every .blend)
    This file   stored in the scene (travels with the .blend, e.g. to a colleague)

A configuration stores the Origin Snaps settings (snap source, orientation, front face axis,
offset mode / space / X Y Z, freeze axes, live toggle, copy mode). Per configuration you
tick which of them Load restores. Loading never moves anything: it only changes settings.
"""

import sys

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

_SCOPES = [('FILE', "This File", "Saved inside this .blend (travels with the file)"),
           ('GLOBAL', "All Files", "Saved in the add-on preferences (every .blend)")]


def _pkg():
    return sys.modules[__package__]


class OrivotConfig(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", default="Configuration")
    snap_source: EnumProperty(items=[('MESH', "Mesh", ""), ('BBOX', "BBox", ""),
                                     ('CURSOR', "Cursor", "")], default='MESH')
    orientation: EnumProperty(items=[('LOCAL', "Local", ""), ('GLOBAL', "Global", "")],
                              default='LOCAL')
    front_axis: EnumProperty(items=[('LOCAL_Y_POS', "+Y", ""), ('LOCAL_Y_NEG', "-Y", ""),
                                    ('LOCAL_X_POS', "+X", ""), ('LOCAL_X_NEG', "-X", ""),
                                    ('LOCAL_Z_POS', "+Z", ""), ('LOCAL_Z_NEG', "-Z", "")],
                             default='LOCAL_Y_POS')
    offset_mode: EnumProperty(items=[('OFFSET', "Offset", ""), ('DIRECT', "Direct", "")],
                              default='OFFSET')
    offset_space: EnumProperty(items=[('WORLD', "World", ""), ('LOCAL', "Local", "")],
                               default='WORLD')
    offset_x: FloatProperty(default=0.0)
    offset_y: FloatProperty(default=0.0)
    offset_z: FloatProperty(default=0.0)
    lock_x: BoolProperty(default=False)
    lock_y: BoolProperty(default=False)
    lock_z: BoolProperty(default=False)
    live_offset: BoolProperty(default=True)
    copy_mode: EnumProperty(items=[('WORLD', "World", ""), ('DELTA', "Delta", "")],
                            default='WORLD')

    save_snap_source: BoolProperty(name="Snap Source", default=True)
    save_orientation: BoolProperty(name="Orientation", default=True)
    save_front_axis: BoolProperty(name="Front Face Axis", default=True)
    save_offset_mode: BoolProperty(name="Offset Mode & Space", default=True)
    save_offset_xyz: BoolProperty(name="Offset X/Y/Z", default=True)
    save_freeze_axis: BoolProperty(name="Freeze Axis", default=True)
    save_live_offset: BoolProperty(name="Live Toggle", default=False)
    save_copy_mode: BoolProperty(name="Copy Mode", default=False)
    show_details: BoolProperty(default=False, description="Show what this configuration restores")


def restore(cfg, scene):
    """Apply the ticked parts of cfg to the scene. Returns the restored labels."""
    done = []
    if cfg.save_snap_source:
        scene.orivot_snap_source = cfg.snap_source
        done.append("Source")
    if cfg.save_orientation:
        scene.orivot_preview_orientation = cfg.orientation
        done.append("Orientation")
    if cfg.save_front_axis:
        scene.orivot_front_axis = cfg.front_axis
        done.append("Front Axis")
    if cfg.save_offset_mode:
        scene.orivot_offset_mode = cfg.offset_mode
        if hasattr(scene, "orivot_offset_space"):
            scene.orivot_offset_space = cfg.offset_space
        done.append("Offset Mode")
    if cfg.save_offset_xyz and scene.orivot_offset_mode == 'OFFSET':
        # (Direct mode's fields are the live world position: stale values would make the
        # origin jump on the next drag, so they are only restored in Offset mode)
        scene['_orivot_suppress_offset_update'] = True
        try:
            scene.orivot_offset_x, scene.orivot_offset_y, scene.orivot_offset_z = \
                cfg.offset_x, cfg.offset_y, cfg.offset_z
        finally:
            scene['_orivot_suppress_offset_update'] = False
        done.append("Offset XYZ")
    if cfg.save_freeze_axis:
        scene.orivot_lock_x, scene.orivot_lock_y, scene.orivot_lock_z = cfg.lock_x, cfg.lock_y, cfg.lock_z
        done.append("Freeze")
    if cfg.save_live_offset:
        scene.orivot_live_offset = cfg.live_offset
        done.append("Live")
    if cfg.save_copy_mode:
        scene.orivot_copy_mode = cfg.copy_mode
        done.append("Copy Mode")
    return done


_SRC = {'MESH': "Mesh", 'BBOX': "BBox", 'CURSOR': "Cursor"}
_AXIS = {'LOCAL_Y_POS': "+Y", 'LOCAL_Y_NEG': "-Y", 'LOCAL_X_POS': "+X",
         'LOCAL_X_NEG': "-X", 'LOCAL_Z_POS': "+Z", 'LOCAL_Z_NEG': "-Z"}


CLASSES = (OrivotConfig,)
