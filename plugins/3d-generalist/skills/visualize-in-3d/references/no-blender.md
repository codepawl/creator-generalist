# Without Blender

When Blender is not installed and the user chose to go on without it, build the models in code with Crucible's
primitives and modeling addon. Tell the user in the report that model quality is lower: fewer bevels, no baked
ambient occlusion or sculpted detail. The reference-sheet rule still applies (`real-objects.md`); only the modelling
tool changes.

## Building models in code

- One module per asset family (`src/models/crane.js`) that returns a list of Crucible parts
  (`{ name, geometry, material, matrix }`) built at real size in metres from the reference sheet's dimension table.
  A scene graph (`createSceneGraph`, Crucible docs `scene-graph.md`) holds parents and pivots.
- Shapes: `box(bevel)`, `cylinder(segments, bevel)`, `sphere`, `torus` from `@codepawlhq/crucible`; `lathe` for turned
  parts, `extrude` with `bevel` for panels and plates (a 2 to 4 cm bevel stops the toy look) and `tube` for pipes
  and cables from `@codepawlhq/crucible/addons/modeling`.
- Parts that share one geometry and one material are batched and culled together by the renderer, so reuse the same
  geometry object for repeats instead of copying it. Keep moving parts (wheels, doors, booms, limbs) as separate named
  nodes with their pivot at the joint.
- Detail in the order the camera sees it: silhouette, large forms, then panel lines (thin dark boxes inset by a few
  millimetres), bolts, vents, windows, lights. Size small parts against a 1.8 m figure.
- Materials: `color`, `roughness` and `metallic` from the reference photos; small canvas textures as `map` for signage
  and wear; `emission` for lights. Turn on `ambientOcclusion` (needs `depth: true`) so contact shadows read.

## Checks

- Render each asset alone from the side and three-quarter views next to its reference image (a small Playwright page
  that loads one model) and fix proportions, missing parts and part counts, as the Blender compare renders do.
- Export each finished model to GLB with `exportGlb(parts)` from `@codepawlhq/crucible` so pass 2 loads it the same way
  as a Blender asset.
