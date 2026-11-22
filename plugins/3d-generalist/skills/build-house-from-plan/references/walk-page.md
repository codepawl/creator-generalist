# Live walk page

Put the built house on a web page people walk through, with a plan minimap in the corner, rendered live in Crucible
(`@codepawlhq/crucible`), never a bare three.js renderer.

## Reading map

- Export the house: "Assets".
- Page parts: "Page".
- Proving it before anyone sees it: "Checks".
- Known engine faults: "Crucible notes".

## Assets

```bash
blender -b out/house.blend -t 6 -P scripts/export_web.py -- plan.json out/web/house.glb --texture 1024
npx -y @gltf-transform/cli@4 optimize out/web/house.glb out/web/house_opt.glb --texture-compress webp --texture-size 1024 --compress meshopt
uv run --no-project --with numpy python scripts/walk_data.py plan.json out/web/walk.json out/house_build_report.json
```

- `export_web.py` writes one GLB in the glTF frame (y up): plan (x, y) at height z becomes (x, z, -y), in metres. It
  drops the site (ground, grass, trees) unless `--keep-site`, since the page grows its own.
- `walk_data.py` writes what the walker needs, in the same frame:
  - collision walls, split at doors and cased openings;
  - room polygons and floor heights;
  - casework with its heights;
  - furniture footprints from the build report;
  - stairs as ramps;
  - lamps and shots;
  - an affine from world to the source sheet's pixels, for drawing the sheet under the minimap.
- About 9 MB after optimising for a 13-room house with 35 models.

## Page

- Ground height follows each room's floor near the house, so sunken rooms and stairs walk right. Inside the house the
  walker stands on the room's `floor`, on a stair ramp, or on 0 near the house; elsewhere it stands on terrain.
- Collision: a custom mover pushes the body out of wall, casework and furniture segments, each with its half thickness,
  and skips any segment outside the body's height band.
- Minimap: rooms and walls from `walk.json`, the walker as a dot with a view cone. Round its corners and pad the bounds
  so the approach from the street stays on the map.
- Phone: the left half of the screen is a move stick and the right half looks around. Desktop uses pointer lock and WASD.
  Keep bloom low: recessed lamps blow out at eye level.
- Credits page: every CC BY model (title, author, link), the source sheet, CC0 libraries, the engine.

## Checks

- Fps standing and walking, at 1280x720 and at a 390x844 touch viewport, in headless GPU Chrome with a fake pointer lock.
- A scripted tour: pause the runtime, place the walker frame by frame along a smooth path, and call `runtime.step(ms)`.
  Before rendering, run every planned spot through the page's own mover. Any push-out means the path walks through
  something, so stop and move the waypoint.
- Read one frame per second of the tour (hand a long batch to a subagent). Look for clipping, floating furniture,
  open closet leaves filling a corridor, blown lamps, and a minimap dot that does not move.

## Crucible notes

- `addons/splat-shader` terrain: grass or tree instancing beside it fails with "two textures of different types use the
  same sampler location", and without grass its shader fails to compile (codepawl/crucible#2272). Until that is fixed,
  use one texture set on the terrain with its UVs retiled.
- An input action needs 1 to 16 bindings; an empty list throws.
- `volumeFog` needs the renderer created with `{hdr: true, depth: true}`.
- File any new engine fault on `codepawl/crucible` with steps and a still.
