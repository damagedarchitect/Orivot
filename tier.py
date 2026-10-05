"""Which Orivot edition this build is: Free, Basic or Pro.

One codebase builds all three. tools/build_tiers.py copies the add-on, rewrites the
TIER line below, removes the modules the edition does not ship (Fab, Line Snap, Axis
Transform, Along Curve, Scene Snap, Collision, Chain, Origin Axes) and its help
animations, and writes the edition's manifest. Everything else reads this module:

  __init__.py   registers only the edition's operators, pie actions and shortcuts
  ui.py         shows only the edition's panels and buttons
  help.py       uses the edition's wording where a tool has fewer options

Free   39 snap points + object centres, 3D Cursor, World Zero, Alt+Q pie, menus
Basic  Free + Surface / Vertex snap (Alt+click), Handles, Grid, live preview,
       Multi-Object, Offset & Freeze, Copy / Paste origin, Mirror Plane, history,
       Edit Mode selection snaps, Batch Normalize
Pro    everything (Along Curve, Origin Axes, Object Snaps, Line Snap, Axis Transform,
       Collision, Chain, Pivot Library, Saved Configurations, CSV, Fabrication...)
"""

TIER = "FREE"            # rewritten by tools/build_tiers.py: "FREE" | "BASIC" | "PRO"

_RANK = {"FREE": 0, "BASIC": 1, "PRO": 2}
RANK = _RANK[TIER]
LABEL = TIER.title()                    # "Free" / "Basic" / "Pro"
NAME = f"Orivot {LABEL}"
BASIC = RANK >= 1                       # Basic features available
PRO = RANK >= 2                         # Pro features available

# Where the upgrade buttons point (Free: Basic + Pro, Basic: Pro only).
URL_BASIC = "https://discord.com/users/damagedarchitect"
URL_PRO = "https://discord.com/users/damagedarchitect"

# bl_idnames of the operators this build registered (filled by __init__.register()).
_ops = set()


