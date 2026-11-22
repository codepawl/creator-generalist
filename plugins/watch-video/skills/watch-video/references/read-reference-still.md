# Read a reference still before rebuilding it

<!-- skill-navigation:start -->
## Reading map

- [Why measure first](#why-measure-first)
- [1. Camera and depth](#1-camera-and-depth)
- [2. Zoom tiles, one region at a time](#2-zoom-tiles-one-region-at-a-time)
- [3. Masks for every instance](#3-masks-for-every-instance)
- [4. Scene list](#4-scene-list)
- [5. Build in stages, check each stage](#5-build-in-stages-check-each-stage)
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
