# Medium Recipes for Non-Pixel 3D Rendering

<!-- skill-navigation:start -->
## Reading map

- Overview: [Medium Recipes for Non-Pixel 3D Rendering](#medium-recipes-for-non-pixel-3d-rendering)
- Recipe 1: [Live typography and poetry](#recipe-1-live-typography-and-poetry)
- Recipe 2: [Live sheet music and instruments](#recipe-2-live-sheet-music-and-instruments)
- Recipe 3: [Architectural blueprint and cyanotype](#recipe-3-architectural-blueprint-and-cyanotype)
- Recipe 4: [Terminal telemetry and live code logs](#recipe-4-terminal-telemetry-and-live-code-logs)
- Recipe 5: [Embroidery, cross-stitch, and textile](#recipe-5-embroidery-cross-stitch-and-textile)
- Recipe 6: [PCB circuit traces and topographic contours](#recipe-6-pcb-circuit-traces-and-topographic-contours)
<!-- skill-navigation:end -->

Every medium plugs into the same `renderFrame` spine: swap glyph geometry, underlay guides (staves, dimension lines, grid lines, copper pads), palette mapping from lit `rgb`, and event-driven highlights (MIDI activity, cursor hover, shader pulse). Always build multi-scale visual contrast (`1.4x` silhouette, `0.8x` secondary form, `0.45x` interior micro-details) and leave generous clean background darkness or paper space so the 3D subject pops in under one second.

## Recipe 1: Live typography and poetry

- **World slots:** Keep each 3D curve populated with domain-authentic multi-phrase verse cycles paired to architectural zones (rims, ribs, steps, waves, terrain ridges). Bind each slot index cleanly to one character without dynamic wrapping mid-orbit.
- **Reveal / scramble effect:** When text edits live or presets cycle, run a symmetric decode sequence: rapid ASCII spinner `['|', '/', '-', '\\', '+', ':', '.', '*']` -> quiet dot valley -> staggered character settle driven by world coordinates so waves of glyphs resolve spatially across the model.
- **Atmosphere & accents:** Populate sparse sky dome stars (`alpha = 0` void only) with subtle twinkle (`Math.sin(time * speed + phase)`) and optional warm highlight bloom near hero emissives (lantern beams, lamps, furnaces) sampled from the lifted `rgb` buffer.

## Recipe 2: Live sheet music and instruments

- **Underlay world staves:** Before pouring glyphs, draw continuous 1-line, 3-line, or 5-line vector staves projected along normal offsets (`perpX = -ty`, `perpY = tx`) broken cleanly by `sampleDepthBuffer` gaps and screen jump checks (`screenJump > 42`).
- **Crisp vector notation:** Draw analytical canvas paths rather than fallback system music fonts (which vary across OS font caches): treble/bass clefs, whole/half/quarter heads (rotated ellipse tilted `-0.38 rad`), upward/downward stems, eighth flags, beamed eighth pairs, sharps, flats, rests, barlines, and `pp`/`espr.` expression marks.
- **Audio & performance sync:** Map real MIDI note timing (`scores.mjs`) to 3D moving keys, plucking strings (`stringGlow` decay), and local spotlight color shifts in `computeTokenColor` so active notes illuminate nearby staves gold (`rgb(255, 224, 138)`) right on the beat. Render synced WAV audio at `48 kHz` (`-14.0 LUFS`) via multi-sample `CubicSpline` interpolation before final capture.

## Recipe 3: Architectural blueprint and cyanotype

- **Palette & ground:** Deep Prussian cyanotype canvas (`#061a36`) with crisp drafting chalk white (`rgba(235, 246, 255, alpha)`) for primary cutaways/silhouettes and muted cyan (`rgba(116, 194, 246, alpha)`) for structural mullions and grids.
- **Underlay & glyphs:** Replace musical staves with crisp double orthographic framing ticks, architectural dimension arrows at open curve endpoints (`|<- 4.20 m ->|`), leader callout elbows, and cross-hatch density proportional to shadow darkness (`1.0 - luminance`).
- **Scale & crispness:** Use tabular monospace figures for real engineering coordinates read straight from world curve distances (`worldCurve.worldLength.toFixed(2)`).

## Recipe 4: Terminal telemetry and live code logs

- **Palette & ground:** CRT obsidian void (`#05090d`), phosphor emerald/amber luminance ramp driven by lit `rgb`, with optional faint `1 px` scanlines on the background only (never covering text contrast).
- **World streams:** Pour continuous monospace hex offsets, packet headers, register names (`R0..R15`), and opcode glyphs anchored strictly to world slots (`worldStep` sized to fixed character advance) so text flows cleanly along cable bundles, server racks, or terrain ribs.
- **Activity mapping:** Drive bright white/amber cursor blocks (`activeCursor`) along data buses at packet timing intervals (`flowOffset = time * streamSpeed`) cleanly modulated by `foreshortenFade` at grazing turns.

## Recipe 5: Embroidery, cross-stitch, and textile

- **Palette & ground:** Warm unbleached linen ground (`#1a1714` or textured parchment `#f4efe2`) paired with saturated thread tones sampled from the 3D albedo/lit `rgb` buffer, clamped to a curated 12-thread floss palette so colors look woven rather than digital.
- **Glyph & stroke geometry:** Draw X cross-stitches (`X`) or dense chain-stitch capsule segments aligned (`tx, ty`) along contour loops with subtle per-thread shadow (`+1 px` darker drop offset) and specular thread sheen along the stitch midpoint.
- **Hierarchy:** Bold satin border stitches (`1.4x` stroke width) tracing exterior outlines, open chain stitches (`0.8x`) filling inner planes, and fine seed stitches (`0.45x`) across recessed textures.

## Recipe 6: PCB circuit traces and topographic contours

- **Circuit traces:** Quantize polyline tangents in projection or generate Manhattan + 45-degree chamfered spline guides (`buildGuideOrgans`) along structural shells, rendering glossy ENIG gold/copper trace strokes with circular plated through-hole via pads at major `slotIndex % 8 === 0` intersections. Pulse active signal packets down copper nets synced to animation beats.
- **Topographic contours:** Slice meshes at fixed elevation intervals (`worldPoint.y = k * contourStep`) plus curvature ridges; draw hair-thin isolines with indexed major contours every 5th ring labeled by exact elevation (`+120 m`) placed at locally flat tangent runs (`Math.abs(probe.tx) > 0.7`).
