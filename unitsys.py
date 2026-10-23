"""Length units for everything Orivot writes (pure Python, no bpy; unit-tested outside
Blender).

Internally every export works in millimetres. At the very end a writer converts to the
output unit the user picked:

    code   unit         DXF $INSUNITS   SVG length unit
    MM     millimetre   4               mm
    CM     centimetre   5               cm
    M      metre        6               mm (SVG has no metre: 1 m = 1000 mm, same size)
    IN     inch         1               in
    FT     foot         2               in (SVG has no foot: 1 ft = 12 in, same size)

Text in drawings uses fmt(): metric as decimals, imperial either as decimals (12.375")
or as feet-inches with fractions (1'-0 3/8"), rounded to 1/16" by default.
"""

MM_PER = {"MM": 1.0, "CM": 10.0, "M": 1000.0, "IN": 25.4, "FT": 304.8}
SUFFIX = {"MM": " mm", "CM": " cm", "M": " m", "IN": '"', "FT": "'"}
INSUNITS = {"MM": 4, "CM": 5, "M": 6, "IN": 1, "FT": 2}
SVG_UNIT = {"MM": "mm", "CM": "cm", "M": "mm", "IN": "in", "FT": "in"}
DECIMALS = {"MM": 1, "CM": 2, "M": 3, "IN": 3, "FT": 3}
IMPERIAL = {"IN", "FT"}



def resolve(code, system="METRIC", length_unit="MILLIMETERS"):
    """'AUTO' -> the unit a workshop expects for this scene: metric scenes -> mm (whatever
    the scene's display unit), imperial -> inches, or feet-inches when the scene's length
    unit is feet."""
    if code and code != "AUTO":
        return code
    if system == "IMPERIAL":
        return "FT" if length_unit in ("FEET", "MILES") else "IN"
    return "MM"


def col(code):
    """Short column suffix for CSV headers: mm / cm / m / in / ft."""
    return code.lower()
