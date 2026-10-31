"""Grid snap, symmetry, Edit Mode snap, Batch Normalize, group / proportion / align / curve tools, named groups, CSV export.

Split out of __init__.py in 4.3 (tools/split_init.py), then by area (tools/split_ops.py)."""

import bpy
import csv
import os
from mathutils import Vector, Matrix
import gpu
from gpu_extras.batch import batch_for_shader
from bpy_extras.view3d_utils import location_3d_to_region_2d
from . import opkit
from . import meshnp
from . import gpudraw
from . import state
try:
    from . import curvepath
except ImportError:
    curvepath = None
from . import common
from . import preview


# ── FEATURE 4: Snap to another object's origin (eyedropper picker) ────────────
# ── FEATURE 4b: Move object to another object's origin ───────────────────────
# ── FEATURE 5: Align origins across selection ─────────────────────────────────
# ── FEATURE 1: Snap to Curve (start / middle / end / control-point average) ───
# ── FEATURE 6: Named persistent MO groups ────────────────────────────────────
class OrivotProNamedGroup(bpy.types.PropertyGroup):
    """A named, persistent group of objects for Multi-Object operations."""
    name       : bpy.props.StringProperty(name="Group Name", default="Group")
    object_names: bpy.props.StringProperty(
        name="Objects",
        description="Comma-separated object names (persists with .blend file)"
    )


# ── FEATURE 7: Surface snap to other scene objects ────────────────────────────
# ── FEATURE 9: CSV export of origin positions ─────────────────────────────────
from . import place  # noqa: E402  (load order, see __init__)


from . import support
