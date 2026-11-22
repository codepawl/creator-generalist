# Sprite stacking

Status: first build on 2026-11-20 (Trainspotting trial, voxelized gaussian splats of crowd-photo objects, drawn in
Crucible). Numbers marked "measured" come from that build. The rest are still guesses: replace them after the next one.

Sources: X trend of November 2026 (a 6k-like post and two follow-ups). Sprite Stacker and vox2slice on itch.io.

## What it is

An object is cut into horizontal pixel-art slices. Each frame draws the slices from the bottom up. Each slice is
moved up on screen by a fixed step and turned by the same yaw. The eye reads the stack as a solid 3D object in pixel
art. Ground objects with a strong top silhouette work best (rovers, landers, cars, houses). Tall thin objects need
many slices and read worse.

## From a model or splat to voxels

1. Scale the model so its footprint is 48 voxels wide (measured: a 48 x 42 x 51 grid of a statue gives about 9k
   visible faces and reads clearly at 96 px). The height in voxels is the slice count.
2. Voxelize. Each voxel takes the colour of the nearest measured surface. Close small gaps (one closing pass) and fill
   the inside, so a slice seen at a low angle shows no holes. Give the inside cells the darkest palette colour.
   Measured: after closing and filling, holes were 0.08% of the silhouette.
3. Smooth the colour field over 3 cells before quantizing when the colours come from photos or a scan. Neighbouring
   voxels that land on different palette entries are what shimmers when the grid turns (measured below).
4. Bake light by face direction in bands. Measured values that read well: top 1.0, the two side pairs 0.84 and 0.7,
   bottom 0.5. Draw the faces unlit, so the palette stays exact.
5. Quantize all colours to one palette of 8 to 12 colours. A model with flat grey materials needs colours by
   part before this step, or the stack reads as grey mush.
6. For a 2D stack, write one PNG per slice, or one sheet with the slices in a row. Existing tools do this step too
   (Sprite Stacker imports glTF). Our value is the batch run over a whole pack and the look, not the converter.

Missing views: an object rebuilt from photos taken on one side does not get holes in the stack. Steps 2 and 5 close
them. It gets a wrong or smeared shape on the unseen side. Measured: a mirror fill of the seen side did not change
the hole share (0.07% before, 0.08% after). Judge the far side by eye, and keep the turn inside the photographed arc.

Splats trained on crowd photos are a poor source for a stack you show up close. A trial in November 2026 was dropped
for this reason. Splats were trained from about 150-370 crowd photos per object of statues, ships and planes. They
read well as small tiles or from far away, but up close the owner said the stack looked like noise. Each cell mixes
splats of different colour, so the stack shows the noise one voxel at a time. Measured on three heroes at 160 px:

| Setting | Speckle | Shimmer | Look |
| --- | --- | --- | --- |
| Footprint 80, 16 colours, colour from the strongest splat | 0.52-0.67 | 0.30-0.67 | Read as noise |
| Footprint 40, smooth 3 cells, 8 colours | 0.10-0.21 | 0.10-0.40 | Clean lumps, no detail |

Speckle is the share of object pixels that differ from 3 or more of their 4 neighbours. Smoothing removed the noise
and also the detail: the horse lost its head, and the red hull of a ferry went brown. A thin band of strong colour
is lost to cell averaging (5% of the ferry splats were red, and only 4% of the stack pixels came out red), while the
pixel splat look of the same splat showed 14-24% red. Use clean meshes or scans for close-up stacks, and keep
photo-trained splats at tile size.

## Drawing

- Draw at a low internal size and scale up by a whole number with nearest neighbour. Use the 8x upscale and the h264
  settings in `SKILL.md`, step 2. Measured: 96 px internal shown at 4x.
- Camera elevation 35 degrees reads as a stack (measured). For a 2D canvas stack, the step between slices is 1
  internal pixel (guessed). Change it to tilt the camera.
- Add a one-pixel dark outline around the outside of the whole stack, not around each slice.
- A contact shadow under the stack keeps it on the ground.

## Aliasing

The usual stack rotates each slice image, and the pixels shimmer as the object turns. Viewers complain about this.
Do not rotate the image. Rotate the voxel grid, and sample it with nearest neighbour for each output pixel. Every
output pixel is then one whole voxel.

Check: count the share of object pixels that change colour between neighbouring frames of a slow turn
(`scripts/shimmer.py`, which also reports the share of the silhouette that is a hole). Compare runs only at the same internal size,
turn step and elevation. Measured on a dragon statue at 96 px, 1 degree per frame and elevation 35:

| Drawing | Shimmer |
| --- | --- |
| Pixel splat (gaussian splat, pixel post pass) | 0.43 |
| Voxel stack in Crucible | 0.37 |
| Voxel stack, colour smoothed over 3 cells | 0.30 |
| Voxel stack, smoothed over 5 cells, 8 colours | 0.27 |

Most of what remains is the outline moving, which every turn has.

## In Crucible

For a scene built from signed distance functions, `voxelizeModel` in `scripts/voxel-splats.js` gives the voxels. For a
mesh, a GLB or a trained splat, Crucible has no voxel helper in 0.20.0 or 0.21.0 (codepawl/crucible#2745). Voxelize
it in Python and draw the voxels yourself.

Build one part per palette colour and face direction from the exposed cube faces only, with
`material: { tag: 'unlit' }`. Render it with
`renderer.render({ eye, target, projection: 'orthographic', orthographicHeight })` and `samples: 1`.

Unlit colours still go through the view transform. The default ACES curve washed a photo palette out: a bronze statue
came out light grey. Convert the palette from sRGB to linear, import `build/view-transform-shader.js` and pass
`viewTransform: 'neutral'` to the renderer. On two trained statues and ships this cut the median face error from about 5
to 2 display levels (measured 2026-11-20). Keep the 2D canvas stack only when it is the subject of the piece (a "how sprite stacking
works" breakdown), and say why in the project notes.
