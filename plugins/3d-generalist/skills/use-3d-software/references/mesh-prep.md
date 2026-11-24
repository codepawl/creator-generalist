# Mesh prep: repair, remesh, UV, LOD, compress, and prove it still looks right

<!-- skill-navigation:start -->
## Reading Map

- [Mesh prep](#mesh-prep-repair-remesh-uv-lod-compress-and-prove-it-still-looks-right): what `mesh_prep.py` runs
- [What is guaranteed](#what-is-guaranteed): what the tools can and cannot promise
- [Run](#run) and [Profiles](#profiles): running it
- [The gate](#the-gate): reading the result
- [Recipes](#recipes): choosing steps per job
- [Tools](#tools): tools and licences
- [Measured](#measured): test runs and numbers
- Per-stage gates of an asset (retopo, UV, bake, texture, rig: `mesh_prep.py gate`): `asset-pipeline.md`
<!-- skill-navigation:end -->

`scripts/mesh_prep.py` (next to this skill) runs one asset through validate, repair, optional remesh, UV unwrap when
missing, simplify and LOD, compression, validate again, then a before/after gate. Every step is a flag. A run that
breaches any threshold exits 1 and says which.

## What is guaranteed

These tools guarantee measurable properties only:

- glTF-Validator: the file follows the spec (0 errors).
- Repair: no degenerate or duplicate triangles; `--watertight` gives a closed manifold (manifold3d status `NoError`).
- A triangle budget, UV overlap and stretch numbers, and meshoptimizer's simplify error bound.

They do not guarantee the look. A decimated scan can pass every property check and lose its silhouette, a weld can
merge across a UV seam, a remesh can melt a hard edge. So every run also measures the look against the input, and
those numbers decide pass or fail, not the tool's success message.

## Run

```
uv run --no-project python <skill>/scripts/mesh_prep.py run model.glb --profile prop --simplify 0.5 --lod 0.25,0.1 --textures webp
uv run --no-project python <skill>/scripts/mesh_prep.py compare original.glb edited.glb --profile scan
```

- Input: `.glb` or `.gltf` with its `.bin` and textures. Output folder: `<stem>.prep/` with `<stem>.glb`, LOD files,
  `report.md`, `report.json`, `sheet.png` and `stages/` (every intermediate file).
- First run installs: npm packages into `~/.cache/mesh-prep/node` (glTF Transform, meshoptimizer, glTF-Validator,
  sharp); Python packages per step through `uv --with`. Blender is found from `BLENDER`, PATH or the default
  Windows install folder.
- `compare` gates any edit made elsewhere (by hand in Blender, by another tool) against the original.
- `--textures ktx2` needs `toktx` from KTX-Software (`MESH_PREP_TOKTX`). Without it the run stops with that message.
- Blender renders go through `MESH_PREP_GPU_WRAPPER` when set (a GPU queue). Bakes run on the CPU at low priority.

## Profiles

| Profile | Use for | Hausdorff max / p95 (% diag) | Silhouette IoU | Normal mean / p95 | Albedo SSIM | Limits |
|---|---|---|---|---|---|---|
| `prop` | game props, kit pieces | 1.0 / 0.3 | 0.98 | 6 / 30 deg | 0.90 | none |
| `dataset` | pack tiers | same as prop | | | | none |
| `scan` | photogrammetry, CT, lidar | 0.5 / 0.15 | 0.985 | 5 / 25 deg | 0.92 | no remesh, simplify >= 0.5 |
| `hero` | close-up hero assets | 0.3 / 0.1 | 0.99 | 4 / 20 deg | 0.95 | no remesh, simplify >= 0.5 |

`--force` lifts the limits after you have looked at the asset. `--threshold key=value` overrides one number; say why
in the report. Distant copies of a scan go through `--lod`, which is gated against its own error bound, not through
`--simplify`.

## The gate

Run on the input (after packing) against the output (decoded):

- **Hausdorff**: symmetric, surface-sampled with PyMeshLab, world space, as % of the input's bounding-box diagonal.
  Max catches one spike; p95 catches a general drift.
- **Topology**: degenerate faces must be 0. Non-manifold edges may grow by `new_non_manifold_per_10k` per 10k output
  triangles (2 for prop and dataset, 0 for scan and hero): decimation pinches a few edges that never show in renders
  but break physics and booleans; use `--watertight` for those. After a remesh they are reported only.
- **Validator**: 0 errors on the final file, meshopt and KTX2 included.
- **Renders**: six orthographic views framed from the input's bounds, rendered by Blender EEVEE as unlit albedo and as
  world-space shading normals (normal maps included). Silhouette IoU per view, normal angle mean and p95 inside the
  silhouette, and SSIM of the albedo. `sheet.png` shows input, output and a difference image per view.
- **UV**: overlap and stretch are always reported; overlap is gated only for UVs this run generated, since mirrored
  islands in an authored asset are on purpose.
- **Budget**: `--budget N` fails a final file above N triangles.
- **Simplify target**: `--simplify` and each `--lod` must reach 1.25x their target share or fail. Every pass weights
  UVs and normals (position-only simplify slid UVs on a flat normal-mapped panel and turned its shading 38 degrees)
  and uses meshopt `PreserveFolds` (keeps thin two-sided parts). `Prune` stays off: on a low-poly room it deleted 8 of
  11 whole objects at a 20% LOD (Hausdorff 4.7%); without it the same LOD passed the close-up prop gate (0.44%,
  IoU 0.998, SSIM 0.993), and no tested mesh needed it to reach its share. Seam-preserving
  wins when it reaches the target; otherwise `Permissive` runs twice, with UV- and colour-seam vertices protected
  and without, and the protected pass wins whenever it reaches the share (open seams folded a scan boulder's UVs
  and swapped a monster kit's tile colours; the open pass's lower Hausdorff, 0.49 against 0.71% on the boulder, is
  not worth that). Vertex colours are weighted like UVs. The notes name the pass used. Before writing, folds (a face and its reversed twin,
  left by simplify) are removed when the input had none, and so are emptied parts. LODs are gated on
  share, validator, Hausdorff and topology; run `compare` on a LOD file from `stages/` when it will be seen close.
- **Deviation budget**: meshopt's error is a local bound, not a bound on how far the result moves. At error 0.08 a
  low-poly shed lost its porch roof (13.8% Hausdorff) and a kitchen its shelf props, while the record said the bound
  held. So `simplifyLadder` takes `maxDeviation` (% of the diagonal): it measures points sampled on the source
  surface against the result (`scripts/mesh_deviation.mjs`, the direction that sees deleted parts; it read 13.3% on
  that shed against PyMeshLab's 13.8%) and divides the error by 2, 4, 8, 16, 64 until the result fits. `--lod`
  passes its Hausdorff limit as the budget, so a LOD that would fail the gate is rebuilt at a lower error instead.
  A scene-wide limit still let a tavern's lanterns, cups and bottles turn into blobs (2% of the scene is a whole
  cup) and a red door lose its red, so the budget can also be `{ max, piece, colour }`: `piece` caps the p95
  distance in % of each sampled point's own connected piece (floored at 3% of the model), `colour` caps the % of
  the surface whose vertex colour moved by more than 0.1 (ties between coincident faces count as matched). When the
  open permissive pass breaks the budget, the seam-safe passes are tried at the same error before going lower. There is also
  pieces_broken (% of connected pieces where 3 of 8 own samples moved 5% of the piece or changed colour), the
  metric that ranked a tavern and a kitchen worst, as eyes did. The dataset packs use the plain 1, 1.5, 2% limits
  (chosen on comparison sheets); with them the 6% level landed at 6-74% of the triangles on 16 low-poly scenes
  (median about 22%). Use the object budget where small props are seen up close.

The pass ladder lives in `scripts/mesh_simplify.mjs`, a module with no side effects that takes the caller's
meshoptimizer and glTF Transform; a pipeline with its own packages imports it instead of calling glTF Transform's
position-only, seam-preserving `simplify()`, which stops far above its target on flat-shaded and scanned meshes (a
scan boulder stayed at 82% for 50, 20 and 6% targets).

Implementation notes that keep the look: xatlas sees only raw arrays (glTF Transform exports them and remaps every
attribute back, so materials, WebP or KTX2 textures, colours and morph targets survive); meshopt quantizes positions
at 16 bits (14 collapsed a small triangle on the jerrycan test).

Proof the gate can fail: an identity compare scores 0 (Hausdorff 0, IoU 1, angle 0, SSIM 1), and a 2% simplify of a
prop fails on Hausdorff, silhouette and normals. Numbers from the test set are in "Measured".

## Recipes

- Dataset tier or game prop: `run --profile dataset --lod 0.5,0.2,0.06 --textures ktx2`. Keep the source triangles in
  the LOD0 file.
- Broken download (holes, non-manifold, AI generated): `run --profile prop` and read the topology rows first. For
  physics or printing add `--watertight`; that copy drops UVs and materials on purpose.
- Clean quads for editing or rigging: `run --remesh quadriflow --faces 8000`. The quads land in `<stem>_quads.obj`
  (GLB stores triangles only). The run makes a watertight copy and gives QuadriFlow that surface; only when QuadriFlow
  refuses it does it fall back to a voxel copy (the report's `path` says which). Voxels lose parts thin in two
  dimensions such as rings and wires: on a Tripo grenade the voxel path missed the gate at 1.28-1.44% Hausdorff max,
  the surface path passed at 0.81% with 20k faces (at 8k it dropped the ring too). The surface is replaced, so the run unwraps with xatlas and bakes base colour,
  normal and roughness from the original. QRemeshify gives cleaner edge loops when it is installed in Blender
  (`--remesh qremeshify`). Metallic is not baked (the target is non-metal), and metallic, roughness and emissive are
  not gated; check `sheet.png` and the material by eye.
- Heavy simplify and LODs below 0.5: the run bakes a normal map from the original for each one when the UVs do not
  overlap and the mesh has one material; otherwise it notes the skip. A failed gate after that means the triangle
  count is too low for the silhouette: raise the ratio, do not loosen the threshold.
- Skinned or morph meshes: only repair, simplify and compression run; remesh, watertight and bake refuse.
- Never remesh or heavily simplify a scan or a hero asset blind: run `compare` on the result and open `sheet.png`.

## Tools

| Tool | Role | Licence |
|---|---|---|
| glTF Transform | pack, weld, dedup, prune, simplify call, meshopt, WebP, KTX2 call | MIT |
| meshoptimizer | simplify with error bound, LOD, meshopt compression | MIT |
| KhronosGroup glTF-Validator | spec gate | Apache-2.0 |
| trimesh | loading, topology counts, UV metrics | MIT |
| PyMeshLab | Hausdorff distance, watertight repair | GPL-3.0, called as a separate process |
| Manifold (manifold3d) | manifold check | Apache-2.0 |
| xatlas | UV unwrap | MIT |
| Blender QuadriFlow / QRemeshify | quad remesh | GPL |
| KTX-Software toktx | KTX2 encoding | Apache-2.0 |

Instant Meshes is a manual fallback for quads. ArmorPaint and Material Maker are GUI apps for hand texture painting; an
agent cannot drive them, so they are manual options only.

## Measured

Run on 2026-11-22 (Blender 5.3, glTF Transform 4.5.1, meshoptimizer 1.3.0). Hausdorff in % of the bounding-box
diagonal; normal angle in degrees; worst of six views.

| Case | Command | Tris in → out | Hausdorff max / p95 | IoU | Normal mean / p95 | SSIM | Result |
|---|---|---|---|---|---|---|---|
| Identity (barrel vs itself) | `compare` | same | 0 / 0 | 1.0 | 0 / 0 | 1.0 | pass |
| Destroy (barrel at 2%) | `compare` | 2% | 17.06 / 8.85 | 0.859 | 40.2 / 104 | 0.394 | fail, as it should |
| Scan, refuse | `--profile scan --simplify 0.3` | none | none | none | none | none | exit 2, refused |
| Scan boulder, KTX2 | `--profile scan --lod 0.5,0.2 --textures ktx2` | 66k → 66k | 0.0009 / 0.0004 | 1.0 | 0 / 0 | 1.0 | pass |
| Its LOD 0.5 (`compare`) | permissive | 50% | 0.22 / 0.07 | 0.998 | 4.5 / 12.1 | 0.985 | pass |
| Its LOD 0.2, no bake (`compare`) | permissive, seams open | 20% | 0.49 / 0.17 | 0.994 | 11.1 / 28.4 | 0.926 | fail close up; UVs fold to 63% overlap, unbakeable |
| Its LOD 0.2 as run now (`compare`) | seams protected + normal bake | 20% | 0.71 / 0.23 | 0.993 | 6.9 / 25.1 | 0.935 | fail close up: a far LOD only; 0 non-manifold (15 before fold removal) |
| Game floodlight, 8.7k non-manifold edges | `--simplify 0.3 --lod 0.05 --budget 150000` | 459k → 137k | 0.062 / 0.008 | 0.997 | 2.05 / 6.6 | 0.999 | pass; LOD 0.05 at 6.2%, 0.52 |
| Poly Haven jerrycan, WebP | `--simplify 0.5 --textures webp` | 20k → 10k | 0.109 / 0.019 | 1.0 | 2.09 / 5.1 | 0.969 | pass; 0 non-manifold (1 before fold removal) |
| Tripo grenade, bad winding | `--watertight --simplify 0.1 --textures webp` | 289k → 29k | 0.230 / 0.075 | 0.997 | 2.98 / 9.4 | 0.976 | pass |
| Tripo grenade remesh, 20k | `--remesh quadriflow --faces 20000` | 289k → 20k quads | 0.81 / 0.09 | 0.997 | 2.3 / 8.7 | 0.978 | pass (surface path) |
| Same at 8k | `--faces 8000` | 8k quads | 7.00 / 0.24 | 0.979 | 4.5 / 23.1 | 0.914 | fail: the pin ring collapses at this count |
| Voxel path at 20k (before) | | 19.3k quads | 1.28 / 0.14 | 0.994 | 2.9 / 11.9 | 0.970 | fail: ring lost in the voxel copy |

A pipeline using the module (8 low-poly, CAD and game models whose old 6% LOD sat at
64-100%, plus two skinned characters): 10 of 10 built, validator 0 errors on every LOD and mobile file, skins kept, shares
reached except where the level's error bound stopped it (then the record says so). With the deviation
budget all 64 levels of 16 low-poly scenes fit (numbers under "Deviation budget"). Close-up gates fail on 20% LODs
by design; the one model compared with its old file scored as well or better on every metric
(SSIM 0.69 against 0.62, measured before `Prune` was turned off).

What the failures taught: the floodlight first failed at 38.7 degrees of shading with colour and silhouette intact
(fixed by UV-weighted simplify); metal parts baked black until the base colour bake set metallic to 0; QuadriFlow on
a voxel copy loses rings and wires, so it now runs on the watertight surface; at 8k faces even that drops the ring,
and the gate says so, so raise `--faces` for thin parts. A 5% LOD with `Prune` on left empty primitives that the
validator rejected until they were removed. Crucible's own `simplifyGeometry` stopped at 96% on the boulder for
50%, 20% and 5% targets (codepawl/crucible#2985).
