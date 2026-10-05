"""Orivot in-panel help: a ? button in every sub-panel header opens a short looping
animation and a few lines of text inside that panel (Blender's Python API cannot put
images in tooltips, so the help lives in the panel itself). One topic is open at a time;
the animation plays while it is open and stops when it is closed.

Frames are PNGs in help/<anim>/NN.png, loaded on first use into a preview collection.
"""

import os
import textwrap

import bpy
import bpy.utils.previews
from bpy.props import StringProperty

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "help")
FPS = 8.0

# topic: (title, animation, {"object": [...], "edit": [...], "any": [...]})
TOPICS = {
    # ── Origin Snaps ───────────────────────────────────────────────────────────
    "origin": ("Origin Snaps", "origin", {
        "any": ["Every tool in this group moves the ORIGIN (the orange dot) only. "
                "The mesh never moves, so nothing in your scene shifts.",
                "Snap Source: Mesh = real geometry, BBox = bounding box, Cursor = 3D cursor. "
                "Orientation: Local follows the object's rotation, Global uses world axes.",
                "Front: which local axis is the object's front. Pin it to store it on the object."],
        "edit": ["In Edit Mode the origin is placed from the current selection."]}),
    "quick": ("Quick Snap", "quick", {
        "object": ["Surface: click anywhere on the mesh, the origin lands there. "
                   "Vertex: drag over the mesh, it snaps to the nearest vertex. "
                   "Hold Ctrl for grid steps.",
                   "Grid: nearest grid point. Cursor: the 3D cursor. World 0: (0,0,0).",
                   "Handles: shows clickable points on the bounding box; click one to snap. "
                   "They turn off after the snap so you can see the new origin; the pin keeps "
                   "them on to snap several objects in a row. Esc turns them off.",
                   "Shortcuts: Alt+click surface, Alt+Shift+click vertex, Alt+Q pie."]}),
    "points": ("Snap Points", "points", {
        "object": ["39 fixed spots on the object: the 6 extreme sides, 8 corners, 12 edge "
                   "midpoints, 6 face centres, plus geometry / box / mass centre.",
                   "Mirror plane: X moves the origin along X only, onto the plane halfway between "
                   "the mesh's left and right extremes (Y and Z stay). Auto does every axis the "
                   "mesh is truly mirror-symmetric on.",
                   "The panel at the bottom-left after a snap shows any Offset or frozen axis "
                   "that changed where the origin landed.",
                   "With Snap Source = Mesh they follow the real surface (a sloped roof's top "
                   "is its ridge); with BBox they sit on the bounding box.",
                   "With several objects selected see Multi-Object for one shared spot or one each."]}),
    "selection": ("Selection", "selection", {
        "edit": ["Put the origin on the selected vertices / edges / faces: an extreme side "
                 "of the selection, its centre, or the centroid of the selected faces or edges.",
                 "The 27 buttons are the corners, edge midpoints, face centres and centre of "
                 "the selection's box, in Local or World axes."]}),
    "multi": ("Multi-Object", "multi", {
        "object": ["Decides what the Snap Points buttons do with several objects.",
                   "Individual: each object gets its own spot (every chair's origin to its "
                   "own floor point). Combined: all origins go to one spot of the whole group.",
                   "Affect: the selection, a saved list of objects, or a whole collection."]}),
    "offset": ("Offset & Freeze", "offset", {
        "object": ["Offset: every snap lands this far from the chosen spot (World or the "
                   "object's Local axes). Live moves the origin while you drag the numbers.",
                   "Direct: the fields ARE the origin's world position.",
                   "Freeze X/Y/Z: snaps never move the origin on a frozen axis.",
                   "Reset puts the numbers (and a live origin) back; Apply keeps the moved origin."]}),
    "match": ("Copy & Match", "match", {
        "object": ["Copy / Paste: World pastes the exact same point; Relative pastes the same "
                   "offset from each object's box centre.",
                   "Copy % / Paste %: same place in proportion (e.g. 25% across, top).",
                   "Pick: click any object in the viewport, every selected origin goes to its "
                   "origin. X / Y / Z copy just that coordinate from the active object.",
                   "Group Center: all selected origins to the centre of the whole selection."]}),
    "surface_origin": ("Origin to Scene Surface", "surface_origin", {
        "object": ["Shoots a ray from the origin in the chosen direction; the origin moves to "
                   "the first surface of ANOTHER object (e.g. the floor under a chair).",
                   "Nearest tries all six directions. The object itself never moves."]}),
    "curve": ("Along Curve", "curve", {
        "object": ["Select the curve and the objects (any order). Start / Middle / End put "
                   "the origins on the curve.",
                   "Follow Along Curve (toggle): drag the white marker, release to apply. Ctrl "
                   "snaps to where the curve meets other meshes; type 250mm or 40% while dragging. "
                   "Other clicks work as usual, so you can move objects onto the curve. Esc leaves.",
                   "% / Distance: a blue marker shows the spot; nothing moves until Apply.",
                   "Spline Selection: a curve made of several pieces (separate, joined or "
                   "unwelded) has one spline per piece. The arrows pick which one the tools use; "
                   "it flashes blue. Only this curve's own splines count."]}),
    "axes": ("Origin Axes", "axes", {
        "object": ["Turns the origin's axes (the object's local X/Y/Z) without moving the mesh: "
                   "copy them from the active object, the 3D cursor, the view, or reset to world."],
        "edit": ["Point the axes along the selection: a face (Z = its normal), an edge (X "
                 "along it) or 3 vertices (a plane)."]}),
    "chain_origin": ("Chain / Distribute (origins)", "chain_origin", {
        "object": ["Puts the ORIGINS of the selected objects in a row; the meshes stay.",
                   "Step: first spot, then + Step each. Between: first and last stay, the rest "
                   "evenly between them. Order decides which object is first."]}),
    "library": ("Pivot Library", "library", {
        "object": ["Saves up to 8 origin spots ON this object (e.g. 'hinge', 'base'). "
                   "They move with the mesh. Click a slot to send the origin back there."]}),
    "history": ("History & Export", "history", {
        "object": ["The last origins of this object (click to go back), and every snap of the "
                   "session on any object (Prev / Next).",
                   "Export writes the selected objects' origin positions to a CSV file."]}),
    # ── Object Snaps ───────────────────────────────────────────────────────────
    "object": ("Object Snaps", "object", {
        "object": ["Every tool in this group moves or rotates whole OBJECTS. Origins stay "
                   "where they are on their objects."],
        "edit": ["In Edit Mode these tools move vertices (Line Snap, Axis Transform)."]}),
    "snap_object": ("Snap to Object", "snap_object", {
        "object": ["Select the object(s) to move, then Shift-click the target (active).",
                   "Source point: which point of the moving object touches (closest point, "
                   "origin, a vertex...). Target point: where it lands on the target.",
                   "Place by Hover: the objects follow the mouse over the target; click to drop.",
                   "Move Selected to Active's Origin: origin-to-origin, any object type."]}),
    "drop": ("Object Drop / Push to Surface", "drop", {
        "object": ["Slides each selected object until it touches another object: -Z drops to "
                   "the floor, +-X/Y push against a wall, +Z lifts to a ceiling.",
                   "Objects sunk slightly into a surface are lifted on top of it. Selected "
                   "objects don't block each other."]}),
    "surface_align": ("Surface Align", "surface_align", {
        "object": ["Click a surface: the object moves there and turns so the chosen local "
                   "axis faces along the surface (a sign onto a slanted wall)."]}),
    "rotation": ("Rotation", "rotation", {
        "object": ["Shows the rotation and resets it so the object's local Z points along "
                   "world Z, Y or X. The whole object turns about its origin."]}),
    "chain_object": ("Chain / Distribute (objects)", "chain_object", {
        "object": ["Moves the selected OBJECTS into a row by their origins.",
                   "Step: first spot, then + Step each. Between: first and last stay, the rest "
                   "evenly between them (equal spacing of booth panels)."]}),
    "collision": ("Collision Check", "collision", {
        "any": ["Live clash check. Red = cuts into another object, amber = only touching, "
                "green = clear.",
                "Mesh Geometry checks the real surfaces and draws the intersection line; "
                "Bounding Box is quick and coarse.",
                "Selected vs Scene: one selected object is enough; the one it hits lights up."]}),
    "line_snap": ("Line Snap", "line_snap", {
        "edit": ["Store guide lines from selected edges (any object), then slide one vertex "
                 "ON a line, PARALLEL to it, or onto line intersections.",
                 "Tab cycles lines, 1/2/3 switch mode, click to confirm."]}),
    "axis_transform": ("Axis Transform", "axis_transform", {
        "edit": ["Rotate or shear the selected geometry about a stored line or the X/Y/Z axis, "
                 "by an exact angle."]}),
    # ── Fabrication ────────────────────────────────────────────────────────────
    "fab": ("Fabrication", "fab", {
        "any": ["Mark the face of each panel that lies on the sheet (or Auto-Mark), then "
                "export: DXF / SVG cut files nested on sheets, a cut list, STL for printing.",
                "Every part gets an ID (P01, P02...) engraved and listed in the cut list."]}),
    "fab_sheet": ("Sheet & Machine", "fab_sheet", {
        "any": ["Sheet size, edge margin and spacing for nesting. Kerf grows outlines so parts "
                "come out at size; Corner Relief adds dogbones for router bits.",
                "Split Oversize Parts cuts a part bigger than the sheet into pieces P03-1, P03-2..."]}),
    "fab_output": ("Drawing & Shape", "fab_output", {
        "any": ["How the 2D shapes are taken from the model and drawn: islands, projection, "
                "cut depth, simplification, colours and line widths."]}),
    "fab_assembly": ("Assembly & Placement", "fab_assembly", {
        "any": ["Snapshot the assembly, Flat-Pack the parts onto the bed for cutting or "
                "printing, then Restore puts every part back.",
                "Also: drop to bed, origin to a round part's centre, hinge origin from an edge, "
                "Mate two marked faces flush."]}),
    "fab_datums": ("Datums & Transforms", "fab_datums", {
        "any": ["Named reference points (from the cursor or an origin) to send origins or "
                "objects to. Export / import object transforms as CSV."]}),
    # ── Settings ───────────────────────────────────────────────────────────────
    "preview": ("Preview & Display", "preview", {
        "any": ["The highlight and arrow show where the next origin snap will land before you "
                "click. Colours, sizes and what is shown are set here."]}),
    "configs": ("Saved Configurations", "configs", {
        "any": ["Save the current Origin Snaps settings (source, orientation, front axis, "
                "offset, freeze...) under a name, for this file or all files.",
                "Load restores only the ticked settings. Nothing moves when you load."]}),
}

# Editions with fewer tools get wording that only mentions what they have (see tier.py).
from . import tier                                          # noqa: E402
TOPICS["origin"] = ("Origin Snaps", "origin", {
    "any": [TOPICS["origin"][2]["any"][0], TOPICS["origin"][2]["any"][1],
            "Front: which local axis is the object's front (for Front / Back / Left / Right)."]})
TOPICS["quick"] = ("Quick Snap", "quick", {
    "object": ["3D Cursor: the origin goes to the 3D cursor. World Zero: to (0, 0, 0).",
               "Alt+Q opens the pie menu with the most used snap points."]})
TOPICS["points"] = ("Snap Points", "points", {
    "object": [TOPICS["points"][2]["object"][0], TOPICS["points"][2]["object"][3],
               "With several objects selected, each one gets its own spot."]})

_pcoll = None
_loaded = {}
_state = {"frame": 0}


def _frames(anim):
    d = os.path.join(DIR, anim)
    try:
        return sorted(f for f in os.listdir(d) if f.endswith(".png"))
    except OSError:
        return []


def _timing(anim, n):
    """Which stored frame to show at each tick. Held states repeat a frame, so frames are
    stored once and help/<anim>/timing.txt lists the playback order. Without the file
    (or if it is damaged) every frame plays once, in order."""
    try:
        with open(os.path.join(DIR, anim, "timing.txt")) as fh:
            seq = [int(x) for x in fh.read().replace("\n", "").split(",") if x.strip()]
        if seq and all(0 <= i < n for i in seq):
            return seq
    except (OSError, ValueError):
        pass
    return list(range(n))


def _release():
    """Free every decoded frame (only one animation is kept in memory at a time)."""
    global _pcoll
    if _pcoll is not None:
        try:
            bpy.utils.previews.remove(_pcoll)
        except Exception:
            pass
        _pcoll = None
    _loaded.clear()


def _icons(anim):
    """Preview icon ids for an animation, every frame decoded up front.

    Blender decodes previews lazily on first draw, which made each frame flash blank on
    the first loop. Reading image_size forces the decode now (~35 ms for 24 frames).
    Switching to another animation frees the previous one, so memory stays at one
    animation (~6 MB) instead of all of them (~165 MB).
    """
    global _pcoll
    if bpy.app.background:
        return []
    if anim in _loaded:
        return _loaded[anim]
    _release()
    try:
        _pcoll = bpy.utils.previews.new()
        ids = []
        for f in _frames(anim):
            p = _pcoll.load(f"{anim}/{f}", os.path.join(DIR, anim, f), 'IMAGE')
            p.image_size[0]                      # force the decode now, not on first draw
            ids.append(p.icon_id)
        _loaded[anim] = [ids[i] for i in _timing(anim, len(ids))] if ids else []
    except Exception:
        _loaded[anim] = []
    return _loaded[anim]


def _icon_scale(context):
    """Fill the sidebar width, but never past the frames' native 256 px (blurry)."""
    ui = context.preferences.system.ui_scale or 1.0
    region = getattr(context, "region", None)
    width = region.width - 44 if region is not None and region.width > 120 else 220
    return max(8.0, min(width, 256 * ui) / (20.0 * ui))


def enabled(context):
    """Preferences › Orivot Pro › 'Help buttons (?)'. On by default."""
    try:
        return context.preferences.addons[__package__].preferences.show_help_buttons
    except Exception:
        return True


def _open(context):
    wm = getattr(context, "window_manager", None)
    return getattr(wm, "orivot_help", "") if wm else ""


def header_button(layout, context, topic):
    if not enabled(context):
        return
    on = _open(context) == topic
    layout.operator("orivot.help_toggle", text="", icon='QUESTION', emboss=on,
                    depress=on).topic = topic


def _wrap(layout, text, width, icon='NONE'):
    lines = textwrap.wrap(text, width) or [""]
    col = layout.column(align=True)
    col.scale_y = 0.8
    for i, ln in enumerate(lines):
        col.label(text=ln, icon=icon if i == 0 else 'BLANK1')


def draw_inline(layout, context, topic):
    if _open(context) != topic or topic not in TOPICS or not enabled(context):
        return
    title, anim, text = TOPICS[topic]
    box = layout.box()
    r = box.row()
    r.label(text=title, icon='QUESTION')
    r.operator("orivot.help_toggle", text="", icon='X', emboss=False).topic = topic
    ids = _icons(anim)
    if ids:
        box.template_icon(icon_value=ids[_state["frame"] % len(ids)], scale=_icon_scale(context))
    width = 44
    region = getattr(context, "region", None)
    if region is not None and region.width > 40:
        width = max(24, int(region.width / (7.0 * context.preferences.system.ui_scale)) - 3)
    mode = 'edit' if context.mode == 'EDIT_MESH' else 'object'
    other = 'object' if mode == 'edit' else 'edit'
    body = text.get(mode, []) + text.get("any", [])
    if not body:
        body = text.get(other, [])
        if body:
            _wrap(box, f"Works in {'Edit' if other == 'edit' else 'Object'} Mode:", width, 'INFO')
    for para in body:
        _wrap(box, para, width, 'DOT')


def _make_draw(orig, topic):
    def draw(self, context):
        draw_inline(self.layout, context, topic)
        orig(self, context)
    return draw


def _make_header(topic):
    def draw_header_preset(self, context):
        header_button(self.layout, context, topic)
    return draw_header_preset


def attach(cls, topic):
    """Add the ? button and help box to a panel class defined elsewhere."""
    if getattr(cls, "_orivot_help_attached", False):
        return
    cls.draw = _make_draw(cls.draw, topic)
    cls.draw_header_preset = _make_header(topic)
    cls._orivot_help_attached = True


def _tick():
    try:
        wm = bpy.context.window_manager
        if not wm.orivot_help:
            return None
        _state["frame"] += 1
        for win in wm.windows:
            for area in win.screen.areas:
                if area.type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'UI':
                            region.tag_redraw()
    except Exception:
        return None
    return 1.0 / FPS


class ORIVOT_OT_help_toggle(bpy.types.Operator):
    bl_idname = "orivot.help_toggle"
    bl_label = "Explain This Tool"
    bl_description = "Show / hide an animated explanation of this panel's tools"

    topic: StringProperty()

    def execute(self, context):
        wm = context.window_manager
        wm.orivot_help = "" if wm.orivot_help == self.topic else self.topic
        _state["frame"] = 0
        if wm.orivot_help in TOPICS:
            _icons(TOPICS[wm.orivot_help][1])    # decode before the first frame is drawn
        if wm.orivot_help and not bpy.app.timers.is_registered(_tick):
            bpy.app.timers.register(_tick, first_interval=1.0 / FPS, persistent=True)
        return {'FINISHED'}


def register():
    bpy.utils.register_class(ORIVOT_OT_help_toggle)
    bpy.types.WindowManager.orivot_help = StringProperty(default="", options={'SKIP_SAVE'})


def unregister():
    global _pcoll
    try:
        if bpy.app.timers.is_registered(_tick):
            bpy.app.timers.unregister(_tick)
    except Exception:
        pass
    _release()
    try:
        del bpy.types.WindowManager.orivot_help
    except Exception:
        pass
    try:
        bpy.utils.unregister_class(ORIVOT_OT_help_toggle)
    except Exception:
        pass
