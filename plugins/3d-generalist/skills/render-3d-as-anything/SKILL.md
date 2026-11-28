---
name: render-3d-as-anything
description: "Render any live 3D Crucible scene as typography, sheet music, blueprints, terminal logs, embroidery, circuit traces, or contours using a lit+depth user pass and Split wipe (\"3D blueprint\")."
license: MIT
---

# Render 3D as Anything

Render any moving 3D world in `@codepawlhq/crucible` as live vector graphics: poetry, musical notation, cyanotype blueprints, terminal telemetry, thread stitches, PCB traces, or topographic isolines, paired with a pixel-aligned `Medium <-> Split <-> 3D` comparison wipe.

## Route by task

| When you need | Read |
| --- | --- |
| Dual Crucible renderer, `userPass` depth shader, world curves, and anti-glitch orbit math | [references/pipeline-and-stability.md](references/pipeline-and-stability.md) |
| Choosing and implementing typography, sheet music, blueprint, terminal, embroidery, PCB, or contour styles | [references/medium-recipes.md](references/medium-recipes.md) |
| GPU capture, 4-panel QA stills, 5-frame orbit stability gate, and 1080p60 export | [references/qa-and-capture.md](references/qa-and-capture.md) |

## Architecture

1. Run two synced Crucible renderers at identical viewport size, pixel ratio, camera matrix, and FOV:
   - `sampleRenderer`: wraps `CrucibleRenderer` with `installUserPasses` to encode surface lighting (`RGB`) and eye distance (`Alpha`, 8-bit quantized) into a low-res offscreen RGBA target (`~560x350` at desktop).
   - `solidRenderer`: renders the full lit PBR + HDRI + bloom 3D scene clipped by CSS `clip-path: inset(0 0 0 calc(var(--split) * 100%))`.
2. Pour the chosen medium onto a transparent 2D canvas over `sampleRenderer` in world-space coordinates projected by `viewProjection`, sampling `sampleRenderer` only for visibility, surface normal/tint, and dynamic shadows/spotlights.
3. Build multi-scale visual hierarchy per organ (`buildGuideOrgans`): bold `1.3x..1.5x` primary silhouettes, `0.75x..0.85x` structural body fills, and `0.45x..0.55x` micro-details (keys, hardware pins, labels, contours) so the 3D subject is recognizable in one second without reading a single word.

## Non-negotiable orbit stability rules

Never ship an animated orbit shot until every item below holds:

1. **Tight `depthSpan` (`~8..12 m` around hero)**: an 8-bit alpha channel encodes `254` distance levels. Setting `depthSpan = 24 m` produces ~`9.5 cm` quantization steps that fight `depthTol` and make tokens blink during orbit; set `depthNear = Math.max(0.3, distance - 3.0)` and `depthSpan = 9.0` for hero objects.
2. **Never use a screen-space occupancy grid on dense curves**: skipping a glyph because a neighbor pixel is occupied triggers a domino chain where foreshortened tokens pop, swap indices, or jump glyphs during camera orbit.
3. **World-space polyline slots (`worldStep`)**: bind every glyph index permanently to a distance along the 3D spline (`worldDist = slotIndex * worldStep`) so symbols stay glued to physical 3D geometry instead of sliding along screen length.
4. **Continuous `foreshortenFade` instead of binary culling**: compute `pxPerMeter = tangentMag / worldTangentProbeStep` and fade even/odd slots smoothly via `smoothRange` as projected step shrinks below `unitSize`, eliminating hard pop thresholds.
5. **5-tap depth cross + wide grazing `depthTol` (`0.24..0.30`)**: sample center plus `(+/-1, 0), (0, +/-1)` pixels and fade `visibilityAlpha` across `depthTol * 0.55 .. depthTol * 1.15` so silhouette edges and curved shells never strobe.
6. **Fixed painter `ZONE_ORDER`**: sort curve organs strictly by fixed semantic layer (`stage < body < support < interior < detail < silhouette < overlay`), never by distance to `cameraEye`, which flips draw priority mid-orbit.
7. **Closed perimeters & 5-frame orbit gate**: wrap every rim, lid, base, and bench rectangle with explicitly closed edges (`closed: true` or explicit closing segments) so silhouette outlines stay sealed from every yaw/pitch, and pass [references/qa-and-capture.md](references/qa-and-capture.md) before exporting `1080p60`.
