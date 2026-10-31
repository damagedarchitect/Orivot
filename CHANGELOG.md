# Changelog - Orivot Free

## 4.3.3

- **Faster on big selections:** snapping the origins of 1600 objects at once takes about 0.7 s (1.2 s before). Moving origins asked Blender for each object's children, which walks the whole file every time.
- The other 4.3.3 fixes are in the paid editions (Scene Health no longer lists cameras and lights; origin tools never move cameras, lights or empties; Import Cleanup keeps the empties your scene uses).
- Tested live in Blender 5.2.3 and headless on 4.5 LTS and 5.2 LTS. No errors.

## 4.3.2

- **Ground** (Quick Snap and the Alt+Q pie, also bindable to a key): the origin goes to the bottom centre of each selected object's world-aligned box and the object rests on the floor (Z = 0), in one undo step. Every object is grounded on its own, parents before children.
  - The box is measured on the real geometry, modifiers included, so tilted parts touch the floor exactly. It is the box, not the centre of mass.
  - Collection instances are set on the floor by what they show; their origin (the collection's) is left alone.
  - Objects linked from a library are skipped and named in the report.
- Quick Snap: 3D Cursor | World Zero on one row, Ground below.
- Tested live in Blender 5.2.3 (every button on five selection cases, the redraws, undo) and headless on 4.5 LTS and 5.2 LTS. No errors.
- Screenshots of every edition's sidebar in the README are new.

## 4.3.1

- Settings: the Shortcuts and Defaults buttons are replaced by a gear icon (left of Help Buttons) that opens the add-on preferences at the Shortcuts section.
- Report a Problem moved to the add-on preferences (Support).
- Removed Check for Updates, its start-up preference and the network permission. Orivot Free makes no network calls.

## 4.3.0

Orivot is now four editions: Free, Basic, Pro and the new Fabricator. Free stays free and open source.

- **Pie actions on your own keys.** Every single-button pie action (the six faces, the centres, World Zero, the 3D Cursor snap) has an unbound entry in Preferences ▸ Add-ons ▸ Orivot Free ▸ Shortcuts. Tick it and click the key field.
- **Report a Problem** (Settings) copies your Blender, OS and Orivot versions and any errors Orivot caught, ready to paste into an issue.
- **Check for Updates** (Settings) reads `latest.json` from this repository and tells you when a new version is out. It only goes online when you click it (or at start-up if you turn that on), and only with Blender's Allow Online Access on.
- **Updating without restarting Blender works:** installing a new zip over the old one loads the new code straight away.
- **Upgrade buttons:** Settings ends with Basic | Pro | Fabricator buttons; hover one to see what it adds and its price.
- Under the hood: the 9.5k-line `__init__.py` is split into modules, and every caught error is recorded for Report a Problem.
- **Tested live in Blender 5.2.2** (every button on five selection cases, the redraws, undo) and headless on 4.5 LTS and 5.2 LTS. No errors.
- **Rebuilt 23 Oct (same version):** the add-on's icon collection is freed when it is empty (it was left behind on disable); moving a curve's origin no longer records a false error in Report a Problem; the operator code is split further by area. The tests now also fail on any error Orivot catches and records itself. Screenshots of every edition's sidebar are in the README.

## 4.2.5

- **Section icons.** Quick Snap and Snap Points now show an icon in their header, like Origin Snaps and Settings, so the panel list reads at a glance. Only Blender's own icons are used, and each name is checked against the running Blender, so an icon renamed in a future version shows nothing instead of breaking the panel.
- **Smaller upgrade advert.** The 16-line "More Tools" panel is gone. Settings ends with one row of two heart buttons, ❤ Basic and ❤ Pro; hover either one to see what that edition adds. Settings now opens by default.
- **Tested live in Blender 5.2.2** (every button on five selection cases, with the sidebar redrawn after each) and headless on 4.5 LTS, 5.0 and 5.2 LTS. No errors.

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
