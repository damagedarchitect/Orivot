"""Overlay drawing that looks the same on every GPU backend.

Blender's plain 'UNIFORM_COLOR' shader ignores gpu.state.point_size_set() and
line_width_set() on Vulkan and Metal: points come out 1 px (invisible) and every line
1 px thin. Up to 4.1.0 Orivot drew its markers that way, so on Vulkan the Follow Along
marker, the Pick Origin hover dot and several snap markers simply did not show.

Here lines use 'POLYLINE_UNIFORM_COLOR' (real width everywhere) and points
'POINT_UNIFORM_COLOR', with the old shader as a fallback for very old builds.
"""

import gpu
from gpu_extras.batch import batch_for_shader

_cache = {}


def _shader(name):
    sh = _cache.get(name)
    if sh is None:
        try:
            sh = gpu.shader.from_builtin(name)
        except Exception:
            sh = None
        _cache[name] = sh
    return sh


def _xyz(coords):
    """2D screen points (POST_PIXEL) get z = 0, so every shader sees 3D positions."""
    return [(c[0], c[1], 0.0) if len(c) == 2 else (c[0], c[1], c[2]) for c in coords]


def lines(coords, color, width=1.0, mode='LINES'):
    """coords: 3D (or 2D in POST_PIXEL) points; mode 'LINES' or 'LINE_STRIP'."""
    coords = _xyz(coords)
    if len(coords) < 2:
        return
    color = tuple(color) if len(color) == 4 else (*color, 1.0)
    sh = _shader('POLYLINE_UNIFORM_COLOR')
    if sh is not None:
        vp = gpu.state.viewport_get()
        batch = batch_for_shader(sh, mode, {"pos": coords})
        sh.bind()
        sh.uniform_float("viewportSize", (float(vp[2]), float(vp[3])))
        sh.uniform_float("lineWidth", float(width))
        sh.uniform_float("color", color)
        batch.draw(sh)
        return
    sh = _shader('UNIFORM_COLOR')
    gpu.state.line_width_set(float(width))
    batch = batch_for_shader(sh, mode, {"pos": coords})
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)
    gpu.state.line_width_set(1.0)


