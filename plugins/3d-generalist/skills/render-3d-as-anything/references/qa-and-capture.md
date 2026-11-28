# QA Stills, Orbit Stability Gate, and 1080p60 Capture

<!-- skill-navigation:start -->
## Reading map

- Overview: [QA Stills, Orbit Stability Gate, and 1080p60 Capture](#qa-stills-orbit-stability-gate-and-1080p60-capture)
- GPU Chrome capture flags: [Headless GPU Chrome launch](#headless-gpu-chrome-launch)
- Mandatory 4-panel QA gate: [4-panel visual QA sheet](#4-panel-visual-qa-sheet)
- Consecutive-frame orbit check: [5-frame orbit stability strip gate](#5-frame-orbit-stability-strip-gate)
- Smooth cursor recording & lossless 1080p60 pipe: [Preview and 1080p60 master capture](#preview-and-1080p60-master-capture)
<!-- skill-navigation:end -->

## Headless GPU Chrome launch

Every automated still and video capture launches real Chrome with hardware D3D11/GPU acceleration and blocks only audio playback during frame stepping:

```js
const browser = await chromium.launch({
  executablePath: chromePath,
  args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist', '--disable-audio-output'],
});
```

Wait explicitly for `document.title === 'ready'` (never fixed sleeps) so textures, HDRI maps, custom passes, and async fonts finish uploading before frame `0` renders. Fail loudly (`process.exitCode = 1`) if any `console.error` or `pageerror` fires during capture.

## 4-panel visual QA sheet

Before rendering a video, run `tools/shoot.mjs` and inspect a 2x2 stitched QA sheet covering:

1. `01_hero_medium.png`: full medium mode (`chromeless=1`, `split=0`) checking immediate silhouette readability, negative space separation, and typographic/glyph scale hierarchy.
2. `02_split_50.png`: interactive UI visible, `split=0.5`, verifying pixel-exact alignment between the 2D vector medium and the 3D Crucible render across the center divider, plus clean header/pill bar layout with zero wrap glitches.
3. `03_orbit_back.png`: secondary rear/side orbit angle (`yaw` shifted `+0.8..1.2 rad`) checking depth occlusion, back-side perimeter sealing, and leg/base grounding.
4. `04_solid_3d.png`: full 3D mode (`split=1`) checking PBR lighting, floor seam dissolve/fog falloff, cast shadows, and backdrop mood.

## 5-frame orbit stability strip gate

Static stills cannot catch mid-motion glyph swapping or depth quantization blinking. After shooting any preview (`540p` or `1080p`), extract 5 consecutive cropped frames across the fastest camera orbit beat and inspect them side by side in a horizontal strip:

```bash
ffmpeg -y -ss 5.45 -t 0.50 -i out/preview/preview_540p.mp4 \
  -vf fps=12,crop=480:360:240:90,scale=320:240,tile=5x1 -frames:v 1 \
  out/preview/orbit_stability_strip.jpg
```

Pass criteria across all 5 neighboring tiles:
- Every hero glyph keeps the exact same musical/textual symbol identity across frames (only screen projection glides smoothly; no domino swap).
- Closed outlines (lids, rims, rails, benches) remain unbroken without strobing dark holes.
- Forefront curves stay painted continuously above distant rings (`ZONE_ORDER` respected).

## Preview and 1080p60 master capture

1. Drive camera, time, `split`, and synthetic cursor strictly monotonically from `elapsedSeconds = frameIndex / framesPerSecond` via `window.renderFrame(time, overrides)`. Scale cursor drag offsets proportionally by `viewWidth` / `viewHeight` (never raw `px` constants) so `540p` previews and `1080p60` masters hit identical UI targets.
2. Render a fast `960x540 @ 24 fps` JPEG-piped preview first (`~15 s` for `24 s` duration) for timing, choreography, and orbit-strip sign-off.
3. Export the `1920x1080 @ 60 fps` master piping lossless PNG buffers (`--format png`) into `libx264` (`-preset medium -crf 16 -pix_fmt yuv420p -movflags +faststart`) muxed with `48 kHz` stereo AAC (`192k`) normalized to `-14.0 LUFS`, then verify exact streams (`1920x1080`, `60/1`, `yuv420p`, exact frame count) with `ffprobe` and inspect the full `6x4` contact sheet plus `1080p60` orbit strip.
