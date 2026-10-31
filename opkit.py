"""Recurring operator plumbing, in one place (4.3.2, every edition).

  Targets    which selected objects an operator may change, and why the others are
             skipped (linked from a library, data linked / overridden). Before 4.3.2 only
             three tools filtered linked objects; the rest relied on an exception.
  Confirm    the 4.3.1 preset dialog, generalised: "N setting(s) will change: name
             old -> new", Cancel / Apply, nothing to do = no dialog. A mixin any operator
             can use (presets, Reset, Scene Health fixes, Site Rebase).
  Values     the text of a setting's value: On / Off, the enum name, lengths in the scene's
             own units.
  Files      every file Orivot writes goes through resolve_path() (absolute, right
             extension, folder created) and atomic_open() (written to a temporary file and
             swapped in, so a cut file is never left half-written for the machine).
"""

import contextlib
import math
import os

import bpy

from . import support
from . import units


# ── targets ─────────────────────────────────────────────────────────────────────

def read_only_reason(obj, need_data=True):
    """Why obj cannot be changed, or None if it can. need_data: the tool edits the object's
    data (mesh / curve), not only its transform."""
    if getattr(obj, "library", None) is not None:
        return "linked from a library"
    if need_data:
        data = getattr(obj, "data", None)
        if data is not None:
            if getattr(data, "library", None) is not None:
                return "its data is linked from a library"
            if getattr(data, "override_library", None) is not None:
                return "its data is a library override"
    return None


def targets(context, types=None, need_data=False, exclude=(), objects=None):
    """(objects the tool may change, [(object, reason) skipped]).

    types: object types to take (None = any); objects of other types are left out silently
    (they are not "skipped": the tool never applied to them). objects: an explicit list instead
    of the selection."""
    src = list(objects) if objects is not None else list(context.selected_objects)
    ok, skipped = [], []
    for o in src:
        if o in exclude:
            continue
        if types is not None and o.type not in types:
            continue
        why = read_only_reason(o, need_data)
        if why:
            skipped.append((o, why))
        else:
            ok.append(o)
    return ok, skipped


def skipped_note(skipped, limit=3):
    """' · 2 skipped: Chair (linked from a library), …' for a report line ('' if none)."""
    if not skipped:
        return ""
    parts = [f"{o.name} ({why})" for o, why in skipped[:limit]]
    more = f", +{len(skipped) - limit} more" if len(skipped) > limit else ""
    return f" · {len(skipped)} skipped: " + ", ".join(parts) + more


# ── values ──────────────────────────────────────────────────────────────────────

def same(a, b):
    """Equal for settings: floats within 1e-5 relative, vectors element-wise."""
    if isinstance(a, (list, tuple)) or hasattr(a, "__len__") and not isinstance(a, str):
        try:
            return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
        except TypeError:
            return False
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-5, abs_tol=1e-9)
        except (TypeError, ValueError):
            return False
    return a == b


# ── confirm ─────────────────────────────────────────────────────────────────────

# ── files ───────────────────────────────────────────────────────────────────────

