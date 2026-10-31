"""Surface and vertex snap of the origin (modal and Alt+click quick versions).

Split out of __init__.py in 4.3 (tools/split_init.py)."""

import sys
import bpy
from mathutils import Vector, Matrix
import gpu
from gpu_extras.batch import batch_for_shader
from bpy.app.handlers import persistent
from bpy_extras.view3d_utils import (
    region_2d_to_vector_3d,
    region_2d_to_origin_3d,
    location_3d_to_region_2d,
)

from . import geo
from . import gpudraw
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


def _pkg():
    return sys.modules[__package__]


# ---------------- Surface Snap Operator (Free Surface Mode) ----------------
# ---------------- Vertex Snap Operator (Drag-to-Snap Mode) ----------------
# ---------------- Quick Snap Operators for Alt+Click ----------------
from . import place  # noqa: E402  (load order, see __init__)
from . import support
