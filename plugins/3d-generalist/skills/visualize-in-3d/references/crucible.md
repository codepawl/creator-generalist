# Crucible, the engine for every output

[Crucible](https://github.com/codepawl/crucible) is a WebGL2 engine that draws every output of this skill: live apps,
films and stills. In an app it is a library (`CrucibleRenderer` with parts and a camera frame); for films and stills
an agent drives it through an MCP server that takes a scene as a JSON recipe, returns PNG previews and review grids,
and renders stills and MP4 video on the GPU or the CPU with bounded memory. It has addons for terrain, scanned
vegetation and grass, baked liquid, vehicles on paths, skinned characters with IK, HDRI light, baked room light, a
live game loop, input and player controllers. Reading map: When to use what, Setup, A live app, From the plan file
to a film, Faults seen. Its own docs are at https://crucible.codepawl.com/docs.html and in plain text at
https://crucible.codepawl.com/llms.txt.

## When to use what

| Output | How |
|---|---|
| Live app, lesson app, quick prototype, embed, game | Crucible as a library in the app (see A live app). People click, steer and read a dashboard. The app's 30 s film is recorded from the app itself. |
| Documentary film, action short, cutaway film, showcase film, layer build film | Crucible recipe through MCP, with `references/film.md`. |
| Stills, posters, thumbnails, a model turntable | Crucible recipe through MCP. |
| Real land, forests, grass, water or liquid, vehicles on roads | Crucible addons, in a recipe or imported into the app. |

The helpers in `scripts/` (`frame-guard.js`, `coplanar-check.js`, `human-arm.js`, `pixel-pass.js`) take Crucible parts,
camera frames and poses; read each file's header for its inputs. three.js may still help beside Crucible for plain
math (curves, geometry), but nothing renders through a three.js renderer. A look or feature Crucible lacks is filed at
https://github.com/codepawl/crucible/issues and built as a user pass or material hook meanwhile.

## Setup

1. In the project: `npm install @codepawlhq/crucible`. It needs Node 20.19 or later and an installed Chrome or
   Chromium. It downloads no browser.
2. Add the MCP server. In Claude Code:
   `claude mcp add crucible-scene -- npx --package @codepawlhq/crucible crucible-mcp --backend gpu --memory 256`.
   On Windows, MCP clients start npm launchers badly: point `command` at `node` and `args` at
   `<project>/node_modules/@codepawlhq/crucible/bin/crucible-mcp.mjs` with absolute paths. Other clients take the same `command` and
   `args`. Raise `--memory` (32 to 384 MiB) for textured scenes: a 1080p frame needs about 175 MiB on its own.
3. Pass `--assets <absolute folder>` for GLB models (up to 64 files, 16 MiB each) and `--audio <absolute folder>`
   for the soundtrack. Restart the server after a GLB changes, because asset IDs bind the file contents.
4. Install its two skills, which hold the recipe contract and the render presets:
   `npx skills add codepawl/crucible` (`build-crucible-scene` and `render-crucible-media`). Read them before the first recipe.

## A live app

The app imports Crucible like any library (Vite, pinned versions). Blender models from Pass 1 load as GLB:

```js
import { CrucibleRenderer } from '@codepawlhq/crucible';
import { loadGltf } from '@codepawlhq/crucible/addons/gltf';
import { createRuntime } from '@codepawlhq/crucible/addons/runtime';

const world = await loadGltf('models/world.glb');
const renderer = new CrucibleRenderer(canvas, world.parts, { depth: true, samples: 4 });
const runtime = createRuntime(renderer, {
  mode: 'both',
  fixedRate: 60,
  frame: (context) => ({ eye: [14, 9, 18], target: [0, 1, 0], time: context.elapsedSeconds }),
  systems: [inputSystem, simulationSystem],
});
runtime.start();
```

- Move and recolour parts with `renderer.updateParts(parts)`; call `renderer.resize()` when the canvas changes size.
- Input, rebinding and replay: the Crucible docs `input.md`. Walk, drive and fly controllers and camera rigs:
  `player.md`. A playable scene from a recipe: `game.md`. Characters: `skeleton-pose.md` (clip layers and IK).
- The film recorded from the app does not use the runtime: each frame is `renderer.render({ ...camera, time })` from
  a pure function of time, so a frame at 12.5 s is the same in every take.
- Looks the engine builds in: toon bands and outlines (`line-art.md`), user post passes for pixel, dither and custom
  outlines (`user-passes.md`), material hooks for dissolves and cutouts.

## From the plan file to a film

1. **Stage.** Turn each real part in the plan file into a recipe node at its real size. Blender builds and ready
   models from Pass 1 go in the `--assets` folder as GLB and load with `scene_create_asset`. Primitive stand-ins
   are for blocking only, as everywhere in this skill.
2. **Look.** Set lights, fog and the environment map for the look in `looks.md`. A closed room needs `bake`, or it
   renders flat and grey: `scene_inspect` reports `closed-room-without-bake`.
3. **Motion.** Write the beats as clips and the cut list as the recipe `timeline` (shots with a camera, depth of
   field and `dip` fades). The timeline owns the clock, so every frame is a function of its time, as this skill
   requires.
4. **Review.** Use `scene_look` while building and `scene_review` (up to four labelled shots in one grid) for each
   self-review round. For a look choice, apply two or three variants as `branch`es, review them side by side, show
   the user the grid, and keep the winner with `scene_restore`. Check every `scene_apply` result for
   `renderSucceeded`.
5. **Preview, then final.** Submit a fast render job of the whole cut at low size first, with the soundtrack
   (`settings.audio`), and show it to the user. Render full quality only after they sign off. Two limits shape a long
   film: a timeline holds at most 60 s, and a video job at most 900 frames (30 s at 30 fps, 37.5 s at 24 fps).
   - Within one timeline, render it as jobs that start where the last one ended (`settings.timeline.start` plus
     `duration`). Frames keep no state, so the picture joins without a jump.
   - Past 60 s, render the next part after `scene_apply` with `set-timeline` (its shots carry on the motion clock with
     `motionStart`), then submit with the new revision.
   - Join the parts with the ffmpeg concat demuxer, copying the video, and lay the whole soundtrack once over the
     result: `ffmpeg -f concat -safe 0 -i parts.txt -i score.wav -map 0:v -map 1:a -c:v copy -c:a aac -shortest film.mp4`.
     Each job still gets `settings.audio` with its `offset`, so it checks its own sync (fails over 50 ms).
   Measured on an RTX 3060, a 70 s film at 640x360 and 24 fps as three jobs: about 12 to 14 s of render per job, picture
   joins with no jump, the decoded sound 4 to 20 ms from each cut.
6. **Keep the recipe.** `scene_export_recipe` into the project, so a fix starts from the same scene. Release
   finished jobs with `scene_render_release` and the scene with `scene_dispose`.

Captions, title cards and the sound mix follow `film.md` and `documentary.md` as for any film. Run the generic
checks in `self-review.md` on the rendered MP4, because a grid of stills cannot show motion faults.

## Faults seen

- A grey, flat interior: the room has no `bake`.
- A job that runs out of memory on a textured 1080p scene: `--memory` left at the default.
- A model that keeps its old look after a Blender fix: the server still holds the old asset ID. Restart it.
- A long film rendered as one job: the job is refused past 60 s or 900 frames. Split it on the timeline.
- A click or drop-out at every join: the parts were joined with their own AAC tracks, and each one adds a few
  milliseconds of encoder padding (the tone fell to near silence for 5 ms at each join). Copy the video only and lay the
  soundtrack once over the joined film.

File an engine bug at https://github.com/codepawl/crucible/issues with the recipe, the steps and one still.
