---
name: 2d-generalist
description: "Design, animate, texture, and composite Vox, Johnny Harris, and WSJ style editorial explainer motion graphics across 2D, 2.5D, and 3D using installed free tools (Blender, DaVinci Resolve Fusion, Remotion + Three.js/SVG, FFmpeg) or optional open-source GIS/vector tools. Use when asked to \"create a Vox style video\", \"Vox map or chart animation\", \"2D/3D editorial motion graphics\", \"newspaper highlight and torn paper collage\", \"2d generalist\", or \"2D motion graphics\"."
license: MIT
---

# 2D Generalist

Use this skill to design, animate, texture, and composite editorial motion graphics in the style of **Vox** (*Atlas*, *By Design*, *Earworm*, *Missing Chapter*) and **Flat Pack FX** across **2D, 2.5D, and 3D** using tools already installed on the user's machine (or recommending free tools when missing).

## Mode Routing

| Mode | Scope (2D / 2.5D / 3D) | Primary Reference |
| --- | --- | --- |
| `audit` | Check installed free 2D/3D tools vs optional downloads | [`references/2d-3d-toolchain-matrix.md`](references/2d-3d-toolchain-matrix.md) |
| `design` | Visual hierarchy, asymmetric scale, Blueprint Aesthetic, palettes | [`references/vox-psychology-and-design.md`](references/vox-psychology-and-design.md) |
| `map` | 2D vector/satellite maps, 2.5D embossed/extruded layers, 3D terrain and GeoJSON routes (convert KML with `ogr2ogr`) | [`references/maps-and-geodata-2d-3d.md`](references/maps-and-geodata-2d-3d.md) |
| `chart-timeline` | Pre-drawn ruler timelines, 2D/3D bar/line graphs, dot-matrix repeaters, waveforms | [`references/charts-timelines-and-data.md`](references/charts-timelines-and-data.md) |
| `archival-collage` | Dual highlighters, newspaper zoom/flicker, torn borders, 2.5D parallax, 3D slide projector | [`references/archival-collage-and-camera.md`](references/archival-collage-and-camera.md); highlighters and torn borders in [`references/vox-psychology-and-design.md`](references/vox-psychology-and-design.md) §3 and §6 |
| `thumbnail` | Vector thumbnails in Inkscape, brand logos as sticker outlines with soft shadows | [`references/inkscape-thumbnails-and-logos.md`](references/inkscape-thumbnails-and-logos.md) |
| `texture-look` | Grain, paper, halftone, dither, CRT, VHS, colour misregistration, engraving, boil, flat shading, stacked shadows and glows, colour split | [`references/textures-retro-and-shading.md`](references/textures-retro-and-shading.md) |
| `fx-type` | Goo, smoke, fire, liquid, rain, loops, infinite zoom, kaleidoscopes, mattes, transitions, kinetic type, graphics into footage | [`references/2d-fx-type-and-compositing.md`](references/2d-fx-type-and-compositing.md) |

**Before step 1, run the intent brief** (`references/intent-brief.md`): fill purpose, format, subject, look and constraints from the request, ask only about what is missing (at most 4 questions, options with a recommended default), write `brief.md`, show a cheap preview before the first expensive step, and check the result against the brief before delivery. A piece that misses the user's goal is a failed piece.

## End-to-End Workflow

1. **Audit Toolchain (`audit`)**
   - Run `uv run --no-project python scripts/check_vox_toolchain.py` to detect installed 2D/3D tools (**Blender**, **DaVinci Resolve / Fusion**, **Remotion + Three.js/SVG**, **FFmpeg**) and list 1-line free install commands (`winget`) for any missing optional tools (**QGIS**, **Inkscape**, **Krita**).
2. **Establish Hierarchy & Surface (`design`)**
   - Apply **Asymmetric Scale Tension** (one dominant anchor, generous off-white `#F4F1EA` or blueprint slate `#1B222C` negative space, connecting path). Perform the *Look-Away / Look-Back Test* before animating.
   - Build the **3 Pillars of Visual Authority**: **Surface** (warm paper fibers + static grain), **Ink** (`Multiply` / `Color Burn` bleed + luma matte + roughen edges + `0.5–1.5px` softness), and **Life** (`Posterize Time` at `8–12 fps` for graphical elements or `2–4 fps` background texture boil; a `texture-look` or `fx-type` recipe may set its own rate, and camera moves are never posterized).
3. **Generate Procedural Assets (`scripts/generate_vox_assets.py`)**
   - Run `uv run --no-project python scripts/generate_vox_assets.py` to generate SVG filter definitions (dual-pass torn paper borders, ink bleed, crossed 45° halftone luma mattes, paper grain) and proportional ruler timeline layouts.
4. **Build Scene in Chosen 2D / 2.5D / 3D Engine (`map`, `chart-timeline`, `archival-collage`)**
   - **Code / Web 2D & 3D:** Remotion + SVG filters (`<feTurbulence>` + `<feDisplacementMap>`) + Three.js / React Three Fiber (`35mm` camera, DOF, Z-planes).
   - **Node Compositor 2D & 2.5D:** DaVinci Resolve Fusion (`FastNoise` + `Displace`, `sRender` repeaters, `Paint` trim strokes, `ImagePlane3D` + `Camera3D`).
   - **Full 3D & 2D-in-3D:** Blender 5.2 (Grease Pencil strokes with `Noise`/`Build` modifiers, Geometry Nodes proportional timelines/bar charts, 3D displaced terrain maps, Cycles/EEVEE `35mm` Depth of Field + Compositor lens/grain pass).
5. **Apply Finishing Pass & Validate (`scripts/validate_vox_recipe.py`)**
   - Add subtle 35mm Depth of Field (or feathered adjustment-layer focus mask), radial Chromatic Aberration, Vignette, static grain, a light unsharp pass and Posterize Time cadence.
   - Run `uv run --no-project python scripts/validate_vox_recipe.py --spec <recipe.json>` to verify compliance with all Vox visual laws.

For any step done in Blender (geometry nodes, shaders, rigging, weight paint, NLA, bpy), load the `use-3d-software` skill for the exact nodes and current 5.x names. For the edit, captions, retime, transitions, grade and export in any editor (Resolve, CapCut, Premiere, Kdenlive, FFmpeg), load `edit-video`.
Craft skills for single steps: `draw-and-paint-art` (drawing, figures, painting in Krita), `paint-stylized-backgrounds` (backgrounds, paint-over, parallax, moving foliage and water), `animate-characters` (character motion, frame by frame, cut-out) and `rig-characters` (cut-out puppets).

## Core Vox Visual Laws (Non-Negotiable)

- **No Sterile Digital Canvas:** Never use pure `#FFFFFF` or `#000000` backgrounds. Use warm paper (`#F4F1EA`), archival cream (`#EFECE6`), or blueprint slate (`#1B222C`, or another deep desaturated slate or navy) with static grain.
- **Dual-Pass Torn Paper Borders:** Cutouts on busy backgrounds require an off-white paper border (`Simple Choker` / morphological dilate) roughened with **two passes**: Pass 1 (`Spiky` / large scale scissor cuts) + Pass 2 (`Roughen` / fine paper fiber edge) + `Hard Light` fabric/paper texture clipped to the cutout.
- **Print Citation Halftones:** Apply crossed `+45°` / `-45°` halftone dot luma mattes (split into highlight and shadow mattes) dialed down to the threshold of perception (`8%–18%` opacity) so modern news cutouts feel printed and fact-checked.
- **Pre-Drawn Ruler Timeline Law:** Never space unequal time intervals evenly. Draw an evenly spaced ruler/tick scale first, then place events at their true proportional coordinates so clusters and gaps tell the story.
- **Dual Highlighter Law:**
  - *Digital/Screen Text:* Clean `#FFE600` stroke, `Multiply` blend mode, stroke height **shorter than letter cap-height** (~75–85%), non-highlighted text dimmed to `~30%` opacity.
  - *Archival/Book Page:* 3-pass roughened edges (horizontal marker streaks + border + rough edge) + `Bulge` turbulent displacement, placed in 3D space with a `35mm` camera and shallow Depth of Field tracking the line.
- **Camera Speed Graph:** All 2D/3D camera pans and zooms must use a `35mm` focal length equivalent, Null controller parenting, and a **Continuous Bezier** bell-curve speed graph (slow ease-in -> fast snap -> slow settle), never linear keyframes. An infinite zoom is the one exception: exponential scale, so the zoom speed looks constant.

## Scripts & References

- Toolchain audit: [`scripts/check_vox_toolchain.py`](scripts/check_vox_toolchain.py)
- Asset & SVG filter generator: [`scripts/generate_vox_assets.py`](scripts/generate_vox_assets.py)
- Recipe validator: [`scripts/validate_vox_recipe.py`](scripts/validate_vox_recipe.py)
- Unit tests: [`scripts/test_vox_skill.py`](scripts/test_vox_skill.py)
