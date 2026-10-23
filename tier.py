"""Which Orivot edition this build is: Free, Basic, Pro or Fabricator.

One codebase builds all four. tools/build_tiers.py copies the add-on, rewrites the
TIER line below, removes the modules the edition does not ship and its help animations,
and writes the edition's manifest. Everything else reads this module:

  __init__.py   registers only the edition's operators, pie actions and shortcuts
  ui.py         shows only the edition's panels and buttons
  help.py       uses the edition's wording where a tool has fewer options

Free        39 snap points + object centres, 3D Cursor, World Zero, Alt+Q pie, menus
Basic       Free + Surface / Vertex snap (Alt+click), Handles, Grid, live preview,
            Multi-Object, Offset & Freeze, Copy / Paste origin, Mirror Plane, history,
            Edit Mode selection snaps, Batch Normalize, 3D Cursor tools, 3D-print prep,
            scene health report
Pro         Basic + design and layout in Blender: Along Curve, Origin Axes, Object Snaps,
            Line Snap, Axis Transform, Collision, Chain, Pivot Library, Saved
            Configurations, grids and levels, smart distribute, clearance checks,
            relations, frames, instance / site / import / asset tools
Fabricator  Pro + everything that writes files for making things: CNC cut files,
            nesting, assembly, plans / elevations / sections, dimensions, schedules

Rule of the Pro / Fabricator split: Pro designs and places things in Blender; Fabricator
documents them and makes them (anything that writes a file for a workshop, contractor,
machine or drawing set).
"""

TIER = "FREE"     # rewritten by tools/build_tiers.py: "FREE" | "BASIC" | "PRO" | "FABRICATOR"

_RANK = {"FREE": 0, "BASIC": 1, "PRO": 2, "FABRICATOR": 3}
RANK = _RANK[TIER]
LABEL = TIER.title()                    # "Free" / "Basic" / "Pro" / "Fabricator"
NAME = f"Orivot {LABEL}"
BASIC = RANK >= 1                       # Basic features available
PRO = RANK >= 2                         # Pro features available
FAB = RANK >= 3                         # Fabricator features available

# Where the upgrade buttons point (Free: Basic + Pro + Fabricator, Basic: Pro, Pro: Fabricator).
URL_BASIC = "https://discord.com/users/damagedarchitect"
URL_PRO = "https://discord.com/users/damagedarchitect"
URL_FAB = "https://discord.com/users/damagedarchitect"

# Prices shown in the upgrade tooltips (4.3). Launch prices apply until LAUNCH_UNTIL
# (inclusive, ISO date); after that the tooltips show the list price only.
PRICE = {"BASIC": "AED 55 (about $15)", "PRO": "AED 145 (about $39)", "FAB": "AED 239 (about $65)"}
LAUNCH_PRICE = {"PRO": "AED 125 (about $35)", "FAB": "AED 185 (about $50)"}
LAUNCH_UNTIL = "2026-12-31"


def price_text(edition, today=None):
    """Tooltip price line, e.g. 'AED 125 (about $35) launch price until 2026-12-31,
    then AED 145 (about $39)'."""
    import datetime
    lst = PRICE.get(edition, "")
    launch = LAUNCH_PRICE.get(edition)
    today = today or datetime.date.today().isoformat()
    if launch and today <= LAUNCH_UNTIL:
        return f"{launch} launch price until {LAUNCH_UNTIL}, then {lst}"
    return lst

# bl_idnames of the operators this build registered (filled by __init__.register()).
_ops = set()


