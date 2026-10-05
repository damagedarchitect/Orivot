# Changelog — Orivot Free

## 4.2.4

- **Buttons that can't act are greyed out**, with the reason in their tooltip, instead of failing when clicked. This covers Snap Points and the 3D Cursor snap when a curve, text or empty is active or selected. World Zero stays available.
- Smaller download: the Free build ships only Free's own code (about 0.37 MB).

## 4.2.3 - first Orivot release

Orivot Free is now built from the same source as Orivot Pro, so it has the Pro layout and every Pro fix.

- **Snap Points:**
  - 39 exact points (sides, corners, edge midpoints, face centres) plus the Geometry, Bounding-Box and Mass centres.
  - **Face centres with Snap Source = Mesh land on the real surface**: a sphere's pole, a roof's ridge. They used to land on the vertex nearest the box face centre.
  - Face centres on a 500k-vertex mesh take about 0.2 s per click.
- **Panels:** Origin Snaps (Snap Source, Orientation, Front axis), Quick Snap (3D Cursor, World Zero), Snap Points, and Settings.
- **Also included:**
  - in-panel help animations;
  - a mode indicator in the viewport;
  - Swap Left / Right labels.
- **Alt+Q pie** with configurable slots, and the Object ▸ Set Origin to... menu.
- **Settings from Basic or Pro files are ignored.** A file saved in those editions may hold Offset, Freeze or Multi-Object settings. Free ignores them, so a Free snap always lands on the exact point.
- **Clickable bounding-box handles moved to Orivot Basic.**
