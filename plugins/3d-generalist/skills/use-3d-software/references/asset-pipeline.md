# Asset pipeline

<!-- skill-navigation:start -->
## Reading Map

- [Asset pipeline](#asset-pipeline): the seven stages and why each ends at a gate
- [Routes](#routes): which stages your asset needs
- [Stages](#stages): what each stage takes, makes and must prove, with per-stage rules
- [Gate commands](#gate-commands): the commands and what makes each fail
- [Checked by eye](#checked-by-eye): what no script proves yet
<!-- skill-navigation:end -->

Reference → model → retopo → UV → bake → texture → rig. Every 3D asset that ships (character, creature, prop, hard-surface piece, adapted scan) goes through these seven
stages in order. Each stage ends with a gate: a command that exits 0 or a check you can point to. A stage is done
when its gate passes, not when the tool finishes. Skills that build assets (`model-characters`, `sculpt-models`,
`rig-characters`, `3d-generalist`, CC0 scan adaptation) follow this file; this skill owns the scripts.

## Routes

| Asset | Stages | Notes |
|---|---|---|
| Deforming character or creature (game, film rig) | all 7 | Retopo is quads with loops at the joints; bake from the sculpt or generator mesh |
| Low-poly or unlit atlas character (PS1, chibi, mascot) | 1, 2, 4, 6, 7 | Model low directly: no high poly, so no retopo and no bake. UV gate in `--uv-mode atlas` |
| Prop or hard-surface piece that never deforms | 1 to 6, rig optional | Retopo may be decimate or a CAD tessellation; rig only for moving parts (hinge, wheel, lid: `rig-characters` mechanical rigs) |
| Adapted CC0 scan (Poly Haven, ambientCG) | 1, 3 if too heavy, 4 to 6 | The scan is the high poly. Keep its UVs and textures when the budget fits; otherwise `mesh_prep.py run` remeshes and bakes |
| Machined part from CAD (`model-parts-in-cad`) | 1, 2, 4 to 6 | The tessellation is the low poly; bake a bevel normal map only for close-ups |

## Stages

| # | Stage | Tools | Input | Output | Gate |
|---|---|---|---|---|---|
| 1 | Reference | `model-characters` `scripts/read_character_ref.py`, photos, a tape measure, the brief | brief, images | measured heights, head count, palette; real size in metres for a prop | numbers written down; a front and side image at known scale |
| 2 | Modeling | blockout, sculpt (`sculpt-models`), generator (Tripo, Rodin), CAD, scan | reference | high poly (`*_high.glb`/`.blend`) | `sculpt-models` `scripts/check_sculpt.py`: no non-manifold or loose geometry; silhouette sheet matches the reference |
| 3 | Retopology | QuadriFlow or QRemeshify (`mesh_prep.py run --remesh`), RetopoFlow, hand retopo; Decimate only for static props | high poly | low poly (`*_low.blend` with quads) | `mesh_prep.py gate retopo --high high.glb` (+ `--deforms`): topology and shape against the high |
| 4 | UV unwrapping | seams + Unwrap, Smart UV Project, xatlas (`mesh_prep.py run --uv`), UVPackmaster | low poly | low poly with one bake UV set | `mesh_prep.py gate uv` |
| 5 | Bake | Cycles selected-to-active (`sculpt-models` `scripts/bake_ai_mesh.py`, `mesh_prep.py run --bake on`), Marmoset | high + UV'd low | tangent normal map (+ AO, curvature, base colour from a textured high) | `mesh_prep.py gate bake --high` |
| 6 | Texturing | Principled BSDF, Substance or Blender texture paint, CC0 PBR sets (Poly Haven, ambientCG), hand paint (`draw-and-paint-art`) | baked maps | PBR set: base colour, normal, roughness, metallic (+ AO, emission) | `mesh_prep.py gate texture` on the .blend |
| 7 | Rigging | Rigify, Auto-Rig Pro, Mixamo, AccuRIG, hand rig (`rig-characters`) | textured low poly | armature + weights, export GLB/FBX | `mesh_prep.py gate rig`, then `model-characters` `scripts/check_character.py` on the export |

### 3. Retopology rules

- Deforming meshes are quads (gate: quad share 0.9 or more, no n-gons, poles under 3% of vertices). Put at least
  three edge loops around each elbow, knee, shoulder, hip, wrist and finger joint, concentric loops around the eyes
  and mouth, and poles away from joints. The rig gate's bend test is what proves the loops are enough.
- Game-ready: one mesh per material where possible, triangle budget from the brief (`--budget`), no hidden faces.
- Decimate is for props that never deform. On a character it breaks loops and the bend test fails. For a
  hard-surface prop, dissolve coplanar faces first (Decimate Planar, 3 degrees) and collapse only what is left:
  a plain collapse to 20% broke the silhouette of a game-ready console (IoU 0.93); planar alone kept it (0.997).
  Weld the glTF's seam-split vertices before any collapse, and after it delete vertices on edges shared by three
  faces and fill the holes (the retopo gate counts them against the high).
- The low poly must keep the high's shape: the retopo gate compares it (Hausdorff, silhouette) and fails without
  `--high`. A QuadriFlow result can be valid topology and still a torn shape; `blender_remesh_bake.py` falls back
  to a voxel copy (then shrinkwraps onto the high) when the surface result opens edges, leaves zero-area faces or
  strays more than 1% of the diagonal.
- Known limit: where the high touches itself (crotch, armpits, fingers) no game-density low can follow the crease,
  and Hausdorff max fails while the rest fits. A Tripo body with touching thighs kept max 1.53% (p95 0.09%, p99
  0.26%) at 9.7k quads, shrinkwrap or not. The gate then prints p99 and a "contact crease likely" note with the
  spot. Fix the input, not the limit: generate or pose the high in A-pose with legs apart, or separate the contact
  (move the parts apart, or cut and cap) before retopo.
- With `--high`, non-manifold edges may not exceed the high's own count plus the profile's allowance per 10k
  triangles (a scan often has a few); without it, zero.

### 4. UV rules

- The bake UV set has no overlap. Mirrored or stacked islands go in a second UV set or after the bake.
- Texel density: pick a target (e.g. 1024 px/m for a game prop at 2K, 2048 px/m for a hero face) and keep 90% of
  the surface area within half to double the median. Faces and hands may get more on purpose: say so in the report.
- Padding: at least 8 px between islands at 2K (16 px at 4K) so mip maps and the bake margin do not bleed.
- Seams on hard edges and hidden places; straighten islands of hard-surface strips.
- Smart UV Project angle follows the surface: about 30 degrees for hard-surface (seams on the sharp edges), about 66
  for organic shapes. At 30 degrees a decimated rock's islands filled 4% of the square; 66 degrees gave 18%.
- Pack with the margin equal to the padding (8 px at 2K is 0.004), concave shapes and rotation: a 0.01 margin left
  a rock at 18% fill, 0.004 doubled it. The gate notes fill under 55%.

### 5. Bake rules

- Ray distance (or cage extrusion) must cover the measured low-to-high gap (the gate prints gap p99) and stay under
  10% of the asset's size; past that rays hit the wrong surface and the map skews.
- Size the extrusion by how far the high sits outside the low, not as a share of the ray: a start point above a lip
  or overhang bakes its underside as inward texels. `bake_ai_mesh.py` measures outward and inward gaps separately.
- A game-ready asset built from open, double-sided shells may not rebake: on a CC0 console at least 1.2% of bake
  rays hit back faces at every extrusion tried. Keep its own maps (adapted-scan route) instead.
- A multi-part prop joined into one low can fail the same way: a CC0 hydrant (body, caps and chain, every part closed
  and facing out) read 10% back-face hits after a collapse to 11%. Try baking it part by part before tuning rays.
- Use a cage for hard-surface pieces with split normals; average the cage normals so seams do not split.
- Mark hard edges as sharp and split UVs on them, or the normal map fights the vertex normals (gradients on flat faces).
  In Blender: Shade Smooth by Angle 30 degrees, then Smart UV Project at the same angle.
- Ship the baked normal through a plain Normal Map node into Principled BSDF: custom node groups do not export to glTF.
- Bake margin at least the UV padding. Save normal maps as 16-bit PNG, Non-Color.
- The bake's normal angle tracks the low's shape error more than map size: on a scanned rock, Hausdorff p95 0.25,
  0.18 and 0.15% gave 7.5, 6.0 and 5.1 degrees, while doubling the UV fill moved it 0.04. Add triangles first.
- The gate renders the high and the low with its map from six views: the normal angle must fall at least 5% against
  the low without its map, and stay inside the profile limits.

### 6. Texture rules

- Channels: base colour (sRGB, no baked lighting for PBR), normal (Non-Color, OpenGL Y+ for Blender and glTF;
  flip green for DirectX engines), roughness and metallic (Non-Color, packed as glTF ORM on export), AO optional.
- Sizes are powers of two within the budget (`--max-texture`). A map that is one flat value becomes a number.
- Check colour space on the .blend: glTF fixes it by slot, so a GLB cannot show the mistake.

### 7. Rig rules

- Weights sum to 1, at most 4 influences per vertex for engines, every vertex weighted.
- Rest pose with slightly bent elbows and knees for IK. Names follow the target (Mixamo, Unreal, Unity Humanoid).
- Export check: `check_character.py` on the GLB, then a walk or the target engine's preview.

## Gate commands

Run from the `use-3d-software` skill folder; each writes `<out>/report.md` and exits 0 (pass), 1 (a gate failed)
or 2 (tool error). Set `BLENDER` to pick a version and `MESH_PREP_GPU_WRAPPER` to queue renders.

```
uv run --no-project python scripts/mesh_prep.py gate retopo  low.blend --high high.glb --deforms --budget 20000
uv run --no-project python scripts/mesh_prep.py gate uv      low.glb --texture-size 2048 --padding 8 --texel-density 1024
uv run --no-project python scripts/mesh_prep.py gate bake    low.blend --high high.glb
uv run --no-project python scripts/mesh_prep.py gate texture low.blend --channels "Base Color,Normal,Roughness"
uv run --no-project python scripts/mesh_prep.py gate rig     character.blend
```

| Gate | Fails when |
|---|---|
| retopo | no `--high` given; Hausdorff or silhouette off the high (profile limits; a failing max also prints p99 and a contact-crease note when one spot causes it); n-gons; more non-manifold edges than the high; loose geometry; with `--deforms` quad share under 0.9 or poles over 3%; over `--budget` |
| uv | missing UVs; overlap over 0.1% (bake mode); more than 10% of area outside 0.5x..2x median density (bake mode); flipped faces over 1%; stretch over 10%; any island pair closer than the padding; median off the target by 25% |
| bake | no normal map; low faces with no high surface in reach; ray distance under gap p99 or over 10% of size; normal texels pointing inward or off unit length; normal map not Non-Color; Hausdorff, silhouette or normal-angle limits of the profile; bake not improving shading |
| texture | a required channel missing; a map not a power of two or over the budget; a colour map not sRGB or a data map not Non-Color |
| rig | no armature or skin; unweighted, over-4-influence or unnormalised vertices; a 70 degree elbow, knee or spine bend that collapses over 2% of faces or moves a vertex that lies far from every bone it turns (stray weight) |

`--uv-mode atlas` lets low-poly atlases stack and mirror. `--no-render` skips the bake renders for a quick
measurement, never for sign-off. `tests/test_asset_gates.sh` builds a good and a known-bad fixture per gate and
checks each gate passes one and fails the other; run it after changing any gate.

## Checked by eye

- Loop placement at joints: the bend test catches collapse, not ugly creases. Look at the bent poses.
- Seam placement and island orientation for hand painting.
- Whether the textures match the reference (colour, wear, scale of detail): compare renders side by side.
- Bake artifacts the six views miss (inside of mouths, under arms): orbit the asset under a raking light.
