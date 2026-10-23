"""Output units (bpy layer over unitsys.py): one scene setting for every file Orivot writes.

Settings › Output Units: Auto (the scene's own units), mm, cm, m, in, ft, plus how imperial
lengths read in drawings (decimal 12.375" or fractions 1'-0 3/8").

Blender units -> millimetres: 1 BU = scale_length metres, unless Fabrication's manual
"mm per Blender Unit" override is set.
"""

import bpy

from . import unitsys

ITEMS = [('AUTO', "Auto", "Use the scene's units (Scene Properties › Units)"),
         ('MM', "mm", "Millimetres"),
         ('CM', "cm", "Centimetres"),
         ('M', "m", "Metres"),
         ('IN', "in", "Inches"),
         ('FT', "ft", "Feet (drawing text as feet-inches)")]


def code(scene):
    """The resolved output unit code: MM / CM / M / IN / FT."""
    us = scene.unit_settings
    return unitsys.resolve(getattr(scene, "orivot_units", "AUTO"), us.system, us.length_unit)


def draw(layout, scene):
    row = layout.row(align=True)
    row.prop(scene, "orivot_units", text="Units")
    if code(scene) in unitsys.IMPERIAL:
        row.prop(scene, "orivot_units_imperial", text="")


PROPS = ("orivot_units", "orivot_units_imperial")


def register():
    S = bpy.types.Scene
    S.orivot_units = bpy.props.EnumProperty(
        name="Output Units", items=ITEMS, default='AUTO',
        description="Units of every file Orivot writes (cut files, drawings, schedules, "
                    "cut lists) and of lengths in their text. Auto follows the scene units")
    S.orivot_units_imperial = bpy.props.EnumProperty(
        name="Imperial Text",
        items=[('FRACTION', "Fractions", "Feet-inches with 1/16\" fractions: 1'-0 3/8\""),
               ('DECIMAL', "Decimal", "Decimal inches / feet: 12.375\"")],
        default='FRACTION',
        description="How imperial lengths are written in drawings and lists")


def unregister():
    for p in PROPS:
        try:
            delattr(bpy.types.Scene, p)
        except Exception:
            pass
