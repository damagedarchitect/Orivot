"""3D-print geometry (pure Python, no bpy; unit-tested outside Blender).

Shared by the print set (printprep.py, Basic and up) and Fabrication (fab/, which imports
these names from here). Verts are (x, y, z) tuples; faces are lists of vertex indices.
"""

import math
import struct


