# Read a reference still before rebuilding it

<!-- skill-navigation:start -->
## Reading map

- [Why measure first](#why-measure-first)
- [1. Camera and depth](#1-camera-and-depth)
- [2. Zoom tiles, one region at a time](#2-zoom-tiles-one-region-at-a-time)
- [3. Masks for every instance](#3-masks-for-every-instance)
- [4. Scene list](#4-scene-list)
- [5. Build in stages, check each stage](#5-build-in-stages-check-each-stage)
- [6. Close the last gaps, one region per round](#6-close-the-last-gaps-one-region-per-round)
- [Limits and sources](#limits-and-sources)
<!-- skill-navigation:end -->

Use this before building any 3D scene that must match one picture (a game still, a film frame, a client frame). Do
steps 1 to 4 in order before the first model goes in. The build list on the frames (`recipe.md`, "Build list on the
reference frames") is the picture the user checks. This file is how that list gets its numbers.

## Why measure first

Agents that rebuild a picture by rendering and comparing (VIGA, arXiv 2601.11109; SEIG, arXiv 2606.02580) let the
vision model read the target by eye. Both papers name the same weak point: the model's sense of where things are in
3D. SEIG also found that a wrong early stage (layout, camera) traps every later stage. In the GTA V rebuild of
2026-11-21 the same thing happened: a guessed camera, a tree put on the hill instead of in front of the lens, poles
placed by eye, a road missed. So camera, depth and positions are measured, and the eye is kept for naming things.

## 1. Camera and depth

Run MoGe-2 (Microsoft, metric depth, points and field of view from one picture):
`scripts/read_geometry.py <image> <out> name=x,y ...` (install line in its
docstring, through the GPU queue). It writes the horizontal and vertical field of view, the camera's height over the
ground below it, a depth picture and, for each named frame point, its position in metres and its distance.

- Set the scene camera's field of view and height from this, not from a guess.
- Name a point for every fixed object (pole tops, the car, the tree base, the road at several spots) and place each by
  its measured distance along the camera ray.
- Read the depth picture: a thing much brighter than its neighbours is much nearer, even when it looks small.
- Trust the order of distances more than the metres. Far land and sky come out with wide error.

## 2. Zoom tiles, one region at a time

Small objects are where readers fail. Cut the picture into overlapping zoomed tiles with frame coordinates printed on
them: `uv run --no-project --with pillow python scripts/zoom_tiles.py <image> <out> --grid 4x3 --zoom 1.5`. Use
`--grid 6x4 --zoom 2` for a busy frame.

Give the overview and every tile to one image-reading subagent, so the pictures stay out of the main context. Ask, per object: what it is, its frame box read off the
printed grid, what it is in front of and behind, a distance class with the cue used, its design (shape, count, lean,
colour, surface), and what holds it up. Then the road or path as ordered points, the sky (sun, birds, contrails), the
coast and the water. Each line is marked seen or inferred. A region the reader is unsure about gets a closer tile
(`--grid` with more cells) and a second read.

## 3. Masks for every instance

Do this whenever colour or texture will be scored, and when a frame has many repeated things. Every picture uses
the colours and the depth scale of `scripts/label_palette.py`, so one colour means one label in every output and a
depth picture always runs from 1 m (red) to 2000 m (dark blue) with a legend in metres (`scripts/depth_view.py`).

`scripts/segment_still.py <image> <out> "bird. utility pole. car. pine tree. bush. rock." --depth <npz>`
(install line in its docstring):

- Every pixel gets a label from EoMT-DINOv3 (ADE20K, MIT), mapped onto the shared set. With the step 1 depth,
  "mountain" nearer than 40 m becomes rock and tree pixels with sky depth become sky. Add `--near-is-rock <metres>`
  when the foreground is known rock: EoMT called the GTA V shelf "earth" and "road".
- Small things come from SAM 3 (Meta, SAM licence, Hugging Face access request the user clicks) run on the whole
  frame and on 6 overlapping tiles, then SAM 2.1 cuts a mask per box. Boxes seen twice, or nested in a larger box of
  the same label (a thing cut by a tile edge), are dropped. Tiles raised the birds found from 20 to about 35 of 38.
- `scripts/compare_detectors.py` puts a new detector on the same picture before it replaces the default. On
  2026-11-22 SAM 3 won: the only one with the pier, car, fence and bushes all in place, and no false "pine tree" on
  the bare crown. MM-Grounding-DINO large (Apache-2.0) is the open fallback. OWLv2 found the pier but few pines.
  LLMDet large and Grounding DINO base boxed the bare crown as "pine tree". Rex-Omni was skipped: IDEA licence.
- `scripts/find_thin_lines.py` finds what no detector labels: contrails (thin, pale, sky on both sides, away from
  the sun's glow rays). Dark wires at 960 px are one faint pixel and were not found; read them from a zoomed tile.

Check the outputs by eye before scoring with them: one image reader on the overlays against the still. The first
OneFormer pass looked fine as numbers and was wrong where it mattered (near rock and far ridges one class, sky inside
the tree crown counted as tree, a pier post called a person).

For a hero object that has no model anywhere, SAM 3D Objects turns one masked object into a textured mesh, but it
needs about 32 GB of graphics memory, so it runs on a rented box (`manage-paid-compute`).

## 4. Scene list

Merge steps 1 to 3 into one table, one row per part: name, frame box, distance in metres, what it stands on, design
details, source (model or code), seen or inferred. Check it for things that cannot be: a tree on water, a pole with no
ground, a road that ends in the air. Draw it on the frame with `scripts/build_list.py` and send the sheet to the user.

## 5. Build in stages, check each stage

Build in this order and compare with the reference after each stage, on a side-by-side and a 50/50 blend:

1. Camera and sun (field of view, height, pitch, sun spot).
2. Layout: ground, skyline, coast, road path, every fixed object as a grey block at its measured spot.
3. Shapes: real models in place of the blocks.
4. Materials and small details (texture, pebbles, ruts, wires, birds, contrails).
5. Light and colour, measured in numbers (sky, sun ring, water).

Fix a stage before starting the next. A wrong stage 2 cannot be saved by stage 4. When a stage has two plausible
readings, render both and keep the one closer to the reference.

Look first, then score. `scripts/overlay_reference.py <reference> <render> <out> [--crop x0,y0,x1,y1 --zoom 2]` writes
a 50/50 blend, the reference's edges (cyan) over the render's (magenta), a flip GIF and a strip of all four. Look at
the strip yourself, the whole frame and a 2x crop of each hero area, before any number. On the GTA V still
(2026-11-22) DreamSim held at 0.21 for twenty rounds and the sampled ground height said the tree stood 14 cm in rock,
while the overlay showed the tree hanging over the sea and the switchback road melted into one tan plain. Numbers
rank close renders; they do not show what is missing or floating.

Then score every render in numbers and fix the largest gap first:

- `scripts/score_similarity.py <reference> <renders...>`: DreamSim (MIT) and LPIPS, lower is closer. One number
  per version. On the GTA V rebuild it tracked the eye's ranking from v2 (0.64) to v33 (0.22).
- `scripts/measure_look.py <reference> <render> <mask folder> [depth.npz]`: per region median, lit and shade
  colour, CIELAB lightness, warmth and tint, chroma, contrast, texture energy and feature size. Whole frame: tone
  curve, five dominant colours, layout SSIM at 1/8 size, warmth and chroma in near, middle and far depth bands,
  grain, vignette, bloom, sharpness, sun position, haze colour.
- `scripts/split_light.py <out> <reference> <render> --masks <mask folder>`: Marigold IID Lighting splits each
  picture into material colour and light, per region. It tells "the material is wrong" from "the light is wrong".
  On the GTA V still the rock material matched while the near rock got 50% too much light, so the fix was less fill
  light, not a darker texture. A region whose render pixels show a different thing (layout miss) gives a false
  material gap: fix layout first.

## 6. Close the last gaps, one region per round

After stage 5 the render is close everywhere and wrong in a few places. Each round:

1. Look at the overlay strip, then give the reference, the render and the edge overlay to one image reader. Ask for the
   three biggest mismatches in the region you are fixing, with frame coordinates.
2. Measure each one with `scripts/probe_still.py` (`edges`, `columns`, `colours`, `bands`, `mask`, `glow`; usage
   in its docstring). Act only on a gap that the reader and the probe both show.
3. Make one change per gap behind an environment flag, render as `vNN-<change>`, and probe again. Keep the flag only
   if the overlay and the probe both improve. A regression is then one flag away.

Who to trust for what (GTA V rounds v77 to v96, 2026-11-22):

- The reader finds what is missing, extra or wrongly shaped. It caught the grey sky and the spiky tree crown, which
  box means did not show. It reads downscaled images, so its positions can be 0.05 off: it put the sun glow at
  (0.57, 0.35) where `glow` measured (0.52, 0.31), matching the reference. Take positions and values from probes.
- A box mean that crosses a skyline mixes sky with ground and gives a false gap. Run `columns` first to find the
  row where the sky ends.
- Check the render's pixel size before you compare texture. A 960x540 `scene_look` request came back 720x405, and
  the upscale cut fine texture in every region to a third of the reference's. A 1920x1080 render job, scored at
  960x540, raised it (rock 2.5 to 3.2, tree crown 10 to 16 on `probe_still.py regions`).
- When a score jumps, diff the two renders before you believe it. After a renderer upgrade the edge score went from
  6.7 to 8.7 px while the frames differed by 1.6/255 on average. One global edge threshold let a slightly more
  contrasty road push the soft foreground edges out. `probe_still.py edges` now thresholds each cell on its own.
- Log every number per round and let the overlay decide between them. Warm haze lifted the far ridges toward the
  reference (band mean 82 to 97, against 108) and improved DreamSim. The old global edge score said it cost edge
  match. The per-cell score showed no cost (3.75 to 3.62 px), so that "trade-off" was a measuring error.

What worked, and what did not:

- Repeated things (birds, pines, posts): place one per instance mask, at the mask's centre, top, base and crown
  width. Random clusters in a box made blobs where the reference shows single spires with sky between them (pine
  box brightness 56 to 98, against 113).
- A mask whose base ray reaches far land has a hidden foot. Place that instance where a typical height (20 m for a
  pine) spans its mask, not where the ray meets the ground: the far hit put spires 600 m out as a squat bush row.
- Small flat things seen edge-on vanish. The birds were 12 levels darker than the sky against 115 in the reference.
  Pitch them toward the camera, thicken them, and measure their contrast with the sky around them.
- Make anything brighter than the sky (contrails, thin cloud, a glow) an emissive card with texture alpha. Put it on
  the camera's rays about 400 m out and cut it with the far-mountain mask. Lit tubes rendered as dark grey bars. Fog hid a card
  placed 3.4 km out. Crucible's unlit flatten drops vertex alpha (codepawl/crucible#2948), so the shape lives in the
  texture alpha.
- A sea's colour is mostly the sky it reflects. Water brightness 2.2 to 0.45 moved its mean only from 93,102,104 to
  88,89,90 (reference 73,80,90). Diff two renders after a change: when the mean difference is under 1/255, the
  knob does nothing in that path. Ambient occlusion radius and strength changed nothing in a render job either.
- Tone mapping removes colour from a bright sky. A strong warm tint in the HDRI moved red minus blue near the
  sun only from +16 to +20 in the frame. The reference has +65. Check sky colour with `colours`, not the HDRI file.
- A bare tree's crown shape comes from the generator's angles (downAngle, attractUp, curve), not from more scale.
  Twig radius decides whether twigs show at all at 960 px: the default thin twigs left the upper crown empty.
- Do not tune toward a dark-pixel share alone. A crown with thicker twigs matched the reference's 60-80% dark share
  per cell, and the reader saw a black bramble: the reference twigs are mid brown with sky between them. Match the
  tone with `colours` too, and let the reader judge the silhouette and limb structure.
- Crucible MCP refuses a `scene_create` that sends more than 64 MiB of assets. Compress big meshes first with
  `npx @gltf-transform/cli meshopt in.glb out.glb --quantize-position 16 --quantization-volume mesh`: generated terrain
  went from 28.6 MB to 4.8 MB. A local server can raise the cap with `--max-asset-bytes` (crucible#2841, after 0.22.0).
  Coarser terrain cells saved almost nothing: most of the bytes were in the near tiles.
  The catalog also stops at 64 non-image files in `--assets`, unused ones included (crucible#2989): stage old variants
  out of the folder.
- Before tuning a region, find out which geometry fills it. Tint one mesh pure red, render, and count the red pixels
  inside the region mask. The near-rock mesh covered only 57% of the reference's rock mask; boulders and terrain
  filled the rest, so changes to that one mesh moved the region's numbers only a little.
- Fine texture lost under a dark material is a contrast problem, not a tiling problem. A scan whose spread is 0.12
  of its mean vanishes once a dark colour multiplies it. Raise the map's contrast in log space, keeping its mean
  (`scripts/boost_texture_contrast.py`), and darken with the material colour after. Darkening alone cut the
  grain again (4.2 to 3.6). Texture gains stall near half the reference's value.
- Game screenshots are sharpened. When even the flat sky has more fine detail in the reference than in the render,
  add the engine's sharpen pass (Crucible `effects.stylize.sharpen`). Sharpen 1.0 at 1920 px raised rock grain
  from 3.9 to 5.7 and gave the best DreamSim. It also over-sharpened the sea's ripples (10.2 against 4.5).
- A texture metric can rise while the material reads wrong. Grain went 3.0 to 5.7 and the reader still saw hay and
  fur: top-down UVs had smeared the scan into streaks on steep faces. The fix (UVs projected from the camera) already
  existed behind a flag that the base flags did not set. Have a reader name the material ("stone", "hay", "plastic")
  before tuning numbers, and print the flags a round actually ran with.
- A whole-region mean hides contrast. The rock mask's mean and even its top 5% matched the reference while the
  boulders did not separate: per depth band, the reference ran p10 5-9 to p90 45-84, the render p10 12-20 to p90
  31-54. Print p10 and p90 per band. A reader called the render "far too dark"; the numbers said too flat. Trust
  the reader on what is wrong in form, the band numbers on which way the values must move.
- When darker albedo does not lower a region's p10, the shadow floor comes from ambient and sky light, not from
  the material: albedo 0.55 to 0.28 moved p10 from 16 to 15. Fix the light, not the colour.
  Look for a colour-grade lift first: a lift of 0.009 to 0.018 plus ambient 0.3 was the floor. Removing both crushed
  the rock to near black (p10 1-3); half of each landed in the reference's band. Once the value bands match and a
  reader still sees one slope, the gap is shape, and more light only adds a visible pool.
- Shape added to a surface in shadow does not show. Boulder domes (watershed of the reference's bright tops, each
  pushed toward the camera) were invisible until the key light reached the rock: raising it from 14 to 30 degrees
  lifted the rock's p90 from 52 to 71. Check that a region is sunlit in the render before adding form to it.
- Reader scores drift about one point between runs on the same image. Count a one-point change as noise; ask for
  what changed and where, and pair it with the band numbers.
  Absolute scores do not carry across sheets: the reader re-anchors on each one (one render scored 5, then 3).
  To compare versions, put them on one sheet and ask for a ranking.
- Before tuning a mesh you added (sink, width, colour), find which mesh owns which pixels. Render three low-res
  frames (old state, the old mesh moved, the new mesh added), take masks from the pixel differences, and measure the
  reference and the render inside each mask. Four rounds of boulder tuning ran on two wrong guesses ("the mound
  is black", "the tint is clamped"). The masks showed the boulders were too bright and red (48,34,28 against
  24,25,28) and the vacated area already matched. A reader's "too dark" can mean low contrast or a colour cast.
- Replacing a depth-built shelf with separate boulder models gave silhouettes (reader 3 to 5) but lost the
  reference-driven light and dark pattern (correlation 0.65 to 0.3). Domes inside the same mesh keep both.
- A fine crack net that survives normal-scale and tint changes comes from the base texture itself: swapping the
  cracked scan for a smooth worn-rock texture removed it with no loss in pattern match. A material tint does not
  remove a warm cast that comes from the sun colour; measure the band means before and after to tell which it is.
- Black stair-step dashes on a mesh built from depth are usually holes, not cracks or shadow: the builder leaves a
  cell open across a depth jump, and a steep surface seen at a grazing angle passes a tight ratio (1.12) between
  neighbours. Count black pixels in the spot per change: painted cracks off and a soft sun left 558 and 560, an
  edge ratio of 1.5 left 124. Rule out the cheap causes by measurement before guessing a shadow-map fault.
- A depth mesh's outline steps at its cell size: 3 px cells drew a staircase against the road and the sea. Build
  the depth grid at 1 px and keep the coarser data (lightness, domes) on its own grid, read with bilinear blending
  and normals averaged over 3 px. A nearest read printed a 3x3 block grid and raw per-pixel normals drew scanlines.
- When a region's score does not move under colour changes, check coverage before colour. Two colour flags changed 2%
  of the frame and left the road and ground medians the same, because the road mesh covered only 32-38% of the
  reference's road pixels. Hiding the mesh in one low-res frame shows where it lands; compare it with the reference
  mask column by column (top and bottom edge per frame x) to find missing bends and offset legs.
- A segmentation class mask is a hint, not the target. The "road" mask took in the bank, the power-line slope and
  shadowed dirt below the road. Have a reader trace the true edges on a crop with both outlines drawn before fitting.
- A switchback bend near the camera reads as one wide dirt area, both legs plus the ground inside the bend. Two
  constant-width strips with terrain between them left that area grass. Fill the bend's interior as road dirt, then
  match its colour and tyre tracks: a flat fill raised the road median from 73,56,34 to 106,67,37
  (reference 103,80,70) but read as a smooth orange block. Tyre-track arcs parallel to the road were written and not yet
  rendered.
- On a mesh built from the reference's own depth, the reference's lightness rank per grid cell can drive albedo
  (lit faces) and cut grooves (gaps), so light and dark land in its places: correlation inside the rock mask went
  0.51 to 0.66 (`tools/rock_lightness.py` in the project).

## Limits and sources

- MoGe-2 is trained on real photos. Game frames with heavy haze or bloom can push far distances out by a wide margin.
  On the GTA V still (2026-11-21) it read a 102 degree horizontal view where the hand fit used 72. Its distance
  order matched the eye reading (tree 17 m, car 54 m, poles and hairpin about 92 m). When its field of view
  disagrees with a fit, render both and keep the one whose skyline and road land on the reference. On that still
  the render at MoGe's lens lost the road, the car and the near pole behind an oversized foreground; the 44 degree
  fit won on every part. Take the lens from a fit to the skyline and horizon, and from MoGe take only the distance order.
- The tile read on the same still found what earlier whole-frame reads missed: a third pole at the right edge, a
  rock ledge in front of the car, the fence posts, a pier behind the boulder, 30 or more birds and both contrails.
  It still called the sun hidden, while a brightness measurement put it at (0.515, 0.318). Measure what can be measured.
- Every-pixel labels: `scripts/segment_still.py` first runs OneFormer (ADE20K, 150 classes, MIT) so no region is left
  unlabelled, then the text-prompted instances. On the GTA V still it called the near rock shelf and the far ridges one
  "mountain" (49% of the frame): split such a class by depth from step 1 (near is rock, far is mountain). No single
  model names everything right; coverage comes from OneFormer, small things from the prompted pass, distances from depth.
- Depth models checked 2026-11-22: Depth Anything 3 Metric-L (Apache-2.0) and Depth Pro had the best metric error
  with a known focal length (about 12% AbsRel on Middlebury, NODAR Orin benchmark, 2026-10); MoGe-2 (MIT) has the best
  shape once scale is fixed (3.8% with oracle scale) but the worst estimated focal length. Apple's Depth Pro 2
  (2026-11, github.com/apple-aiml-research/ml-depth-pro-2, sizes 24M to 872M plus a focal-length estimator) ranks first
  in its own paper, but its weights are licensed for non-commercial research only: ask the user before using it on
  work that is posted or sold. Marigold IID Appearance (prs-eth, OpenRAIL++) splits a picture into albedo, roughness
  and metal, trained on interiors, so treat outdoor results as a hint for material targets.
- A reader still misnames tiny things. Anything the build depends on is read from a closer tile.
- Sources: MoGe (github.com/microsoft/moge), SAM 3 (github.com/facebookresearch/sam3), SAM 3D
  (ai.meta.com/blog/sam-3d), VIGA (arxiv.org/abs/2601.11109), SEIG (arxiv.org/abs/2606.02580).
