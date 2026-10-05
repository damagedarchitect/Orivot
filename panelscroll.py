"""Orivot panel scroll memory.

Remembers where the Orivot Pro sidebar tab was scrolled to, separately for each object
mode, and puts it back when you switch modes (Object <-> Edit), so the panel you were working
in is where you left it.

Blender's Python API can READ a sidebar's scroll position (View2D.region_to_view) but cannot
SET it. The only lever is the view2d.scroll_up / scroll_down operators, whose step size and
direction are not documented. So this module never assumes them: it measures. It probes one
step to learn which operator raises the view and how far one step moves, then steps toward the
remembered position while re-reading the real position after every call (closed loop). If the
operators cannot be used at all, it disables itself after a few failures instead of fighting
the UI. Everything runs from one lightweight timer; no handlers, no property callbacks.

Turn it off any time: Preferences > Add-ons > Orivot Pro > "Remember Panel Scroll".
"""

import bpy

PANEL_CATEGORY = "Orivot"
TICK = 0.2              # seconds between checks
STABLE_TICKS = 2        # ticks a mode must persist before we capture / restore
TOL = 20.0              # px: never chase the target closer than this
MAX_STEP_CALLS = 80     # scroll-operator calls allowed per tick
MAX_TRIES = 12          # ticks spent on one restore before giving up
MAX_FAILURES = 3        # consecutive errors / dead restores before self-disabling

_state = {}             # area pointer -> _AreaState
_disabled = False       # set when the scroll operators are unusable
_errors = 0             # consecutive exceptions inside a tick
_dead = 0               # consecutive restores that could not get anywhere near the target
_up_sign = None         # +1 if view2d.scroll_up RAISES the view's top edge, -1 if it lowers it
_step = 40.0            # measured px moved per scroll-operator call


class _AreaState:
    __slots__ = ("mode", "stable", "saved", "target", "tries", "hold")

    def __init__(self, mode):
        self.mode = mode
        self.stable = 0
        self.saved = {}     # mode -> view-space y of the region's top edge
        self.target = None  # position we are currently restoring to
        self.tries = 0
        self.hold = None    # position right after a restore; don't re-capture until the user moves


def reset_state():
    """Forget everything (file load: area pointers from the old file are meaningless)."""
    global _errors, _dead
    _state.clear()
    _errors = _dead = 0


# ---- thin wrappers around bpy (tests replace these) -----------------------------

def _enabled():
    try:
        return bool(bpy.context.preferences.addons[__package__].preferences.remember_panel_scroll)
    except Exception:
        return True


def _mode_of(win):
    try:
        ob = win.view_layer.objects.active
        return ob.mode if ob is not None else 'OBJECT'
    except Exception:
        return 'OBJECT'


def _ui_region(area):
    for r in area.regions:
        if r.type == 'UI':
            return r
    return None


def _top(region):
    """View-space y of the region's top edge: 0 when scrolled to the top, negative below."""
    return region.view2d.region_to_view(0.0, float(region.height))[1]


def _scroll_once(win, area, region, up):
    with bpy.context.temp_override(window=win, area=area, region=region):
        if up:
            bpy.ops.view2d.scroll_up(deltax=0, deltay=40, page=False)
        else:
            bpy.ops.view2d.scroll_down(deltax=0, deltay=40, page=False)


# ---- closed-loop restore ---------------------------------------------------------

def _restore_step(win, area, region, target):
    """Step the region toward `target`. Returns 'done', 'more' (call again next tick) or
    'stuck' (the position stopped changing, e.g. content too short to scroll that far)."""
    global _up_sign, _step
    for _ in range(MAX_STEP_CALLS):
        top = _top(region)
        err = target - top
        if abs(err) <= max(TOL, 0.5 * _step):
            return 'done'
        want_raise = err > 0
        if _up_sign is None:
            # Probe: learn which operator raises the view and how far one call moves it. Try the
            # natural guess first; if the view is pinned against an end, try the other operator.
            for use_up in (want_raise, not want_raise):
                before = _top(region)
                _scroll_once(win, area, region, use_up)
                moved = _top(region) - before
                if moved != 0.0:
                    _up_sign = 1 if ((moved > 0) == use_up) else -1  # +1: scroll_up raises the top edge
                    _step = max(_step, abs(moved))
                    break
            else:
                return 'stuck'
            continue
        use_up = want_raise == (_up_sign > 0)
        _scroll_once(win, area, region, use_up)
        moved = _top(region) - top
        if moved == 0.0:
            return 'stuck'
        _step = max(_step, abs(moved))  # only ever grows: a call clamped at an end moves less
    return 'more'


def _disable(reason):
    global _disabled
    if not _disabled:
        _disabled = True
        print(f"[Orivot Pro] panel scroll memory disabled: {reason}")


def _step_area(win, area, region, mode, category, st):
    global _dead
    if category is not None and category != PANEL_CATEGORY:
        st.stable = 0        # another tab is showing: neither capture nor restore
        st.target = None
        return
    if mode != st.mode:      # mode just changed: schedule a restore for the new mode
        st.mode = mode
        st.stable = 0
        st.target = st.saved.get(mode)
        st.tries = 0
        st.hold = None
        return
    st.stable += 1
    if st.target is not None:
        if st.stable < STABLE_TICKS:  # let Blender finish laying the new mode out first
            return
        res = _restore_step(win, area, region, st.target)
        st.tries += 1
        if res != 'more' or st.tries >= MAX_TRIES:
            now = _top(region)
            if res == 'stuck' and _up_sign is None:
                # No scroll call has EVER moved the view, so the operators do not work here.
                # (If they have worked, 'stuck' just means the content is too short: not a fault.)
                _dead += 1
                if _dead >= MAX_FAILURES:
                    _disable("the sidebar would not scroll to the remembered position")
            else:
                _dead = 0
            st.hold = now    # keep the remembered value until the user scrolls on their own
            st.target = None
            st.stable = 0
        return
    if st.stable >= STABLE_TICKS:
        cur = _top(region)
        if st.hold is not None and abs(cur - st.hold) < 1.0:
            return
        st.hold = None
        st.saved[mode] = cur


def _tick():
    """Timer callback. Returns the next interval, or None to stop the timer."""
    global _errors
    if _disabled:
        return None
    try:
        if _enabled():
            wm = bpy.context.window_manager
            live = set()
            for win in wm.windows:
                mode = _mode_of(win)
                for area in win.screen.areas:
                    if area.type != 'VIEW_3D':
                        continue
                    region = _ui_region(area)
                    space = area.spaces.active
                    if region is None or not getattr(space, "show_region_ui", True) or region.width <= 1:
                        continue
                    key = area.as_pointer()
                    live.add(key)
                    st = _state.get(key)
                    if st is None:
                        st = _state[key] = _AreaState(mode)
                    _step_area(win, area, region, mode,
                               getattr(region, "active_panel_category", None), st)
            for key in [k for k in _state if k not in live]:
                del _state[key]
        _errors = 0
    except Exception as exc:
        _errors += 1
        if _errors >= MAX_FAILURES:
            _disable(repr(exc))
            return None
    return TICK


# ---- lifecycle ------------------------------------------------------------------

def register():
    global _disabled, _up_sign
    _disabled = False
    _up_sign = None
    reset_state()
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=1.0, persistent=True)


def unregister():
    try:
        if bpy.app.timers.is_registered(_tick):
            bpy.app.timers.unregister(_tick)
    except Exception:
        pass
    reset_state()
