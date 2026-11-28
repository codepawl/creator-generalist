# Crucible Dual-Pass Pipeline and Orbit Stability

<!-- skill-navigation:start -->
## Reading map

- Overview & index: [Crucible Dual-Pass Pipeline and Orbit Stability](#crucible-dual-pass-pipeline-and-orbit-stability)
- Dual-renderer architecture & Split sync: [Dual Crucible setup](#dual-crucible-setup)
- Offscreen `userPass` GLSL shader: [DEPTH_ENCODE_FRAGMENT](#depth_encode_fragment)
- Occlusion sampling & world curves: [5-tap depth sampling and world curves](#5-tap-depth-sampling-and-world-curves)
- Eliminating orbit flicker and glyph popping: [Anti-glitch orbit stabilization](#anti-glitch-orbit-stabilization)
<!-- skill-navigation:end -->

## Dual Crucible setup

Run two `CrucibleRenderer` instances inside one synchronized frame loop so the 2D vector medium canvas and the photoreal 3D canvas align pixel for pixel across `Split`:

1. **Offscreen sample pass (`sampleRenderer`)**: sized around `40-50%` of display resolution (e.g., `560x350` for `1280x800`), keeping GPU readback fast (`readPixels` ~1 ms). Enable `installUserPasses(sampleRenderer)` with one lighting/depth pass.
2. **Foreground 3D pass (`solidRenderer`)**: full viewport resolution with PBR textures, HDRI lighting, bloom/tonemapping, and procedural environment shaders (`materialHook`). Clip its container CSS with `clip-path: inset(0 0 0 calc(var(--split) * 100%))` and translate `#split-divider` to `left: calc(var(--split) * 100%)`.
3. **Matrix parity**: share the exact same `computeOrbitEye(yaw, pitch, distance, target)`, `fov`, near/far planes, and scene time `t` between both renderers and the 2D `CanvasRenderingContext2D` overlay. Build a column-major `viewProjection` matrix (`perspective * lookAt`) on the CPU matching Crucible's vertical FOV and aspect ratio.
4. **Chromeless preview mode (`?chromeless=1`)**: hide chrome cleanly while preserving layout bounds so automated captures match interactive screen recordings.

## DEPTH_ENCODE_FRAGMENT

Encode lifted surface radiance into `rgb` (so spotlights, key glow, reflections, and shadow pools drive medium color and brightness automatically) and camera-space linear eye distance into `alpha`:

```glsl
vec4 userPass(vec2 uv) {
  float depthValue = depthAt(uv);
  if (depthValue >= 0.9999) {
    return vec4(0.0);
  }
  vec3 rawLit = texture(sceneColor, uv).rgb;
  vec3 lifted = pow(clamp(rawLit * 1.48, 0.0, 1.0), vec3(0.88));
  vec3 ambientFloor = vec3(0.24, 0.31, 0.42);
  vec3 lit = max(lifted, ambientFloor);
  lit = lit / (1.0 + 0.08 * max(lit.r, max(lit.g, lit.b)));
  float eyeDist = length(worldPointAt(uv) - cameraEye);
  float horizonFade = 1.0 - smoothstep(28.0, 68.0, eyeDist);
  lit *= horizonFade;
  float normDist = clamp((eyeDist - depthNear) / depthSpan, 0.0, 1.0);
  float encDepth = (255.0 - floor(normDist * 253.0 + 0.5)) / 255.0;
  return vec4(clamp(lit, 0.0, 1.0), encDepth);
}
```

Crucial rules for uniforms:
- `alphaByte = 0` means sky/void background (no geometry hit).
- Keep `alphaByte >= 2` strictly for valid geometry hits (`255 - round(normDist * 253)` spans `2..255`).
- Set `depthNear = Math.max(0.3, state.distance - 3.0)` and `depthSpan = 9.0` for hero objects (`~3.5 cm` per 8-bit step instead of `~9.5 cm` at `24.0 m`).

## 5-tap depth sampling and world curves

Single-pixel depth lookup fails along sharp silhouettes, thin rails, and curved lips because nearest rounding hits background `0` or an adjacent deeper surface by half a pixel.

Always use a 5-tap cross centered at `(screenX * scaleX, height - 1 - screenY * scaleY)`:
- Probe offsets `[[0, 0], [-1, 0], [1, 0], [0, -1], [0, 1]]`.
- Ignore taps with `alphaByte < 2`, recording `hasAnyForeground = true` whenever any valid tap exists.
- Among foreground taps passing `curveViewDist <= frontDist + depthTol * 1.15`, select the closest delta to `curveViewDist`.
- Compute smooth grazing visibility attenuation:

```js
let visibilityAlpha = 1.0;
if (depthTol > 0 && curveViewDist > bestFrontDist + depthTol * 0.55) {
  const rampSpan = Math.max(1e-4, depthTol * 0.60);
  visibilityAlpha = Math.max(0.0, Math.min(1.0, 1.0 - (curveViewDist - (bestFrontDist + depthTol * 0.55)) / rampSpan));
}
```

- Return codes: `0` = clear sky/void (safe for ambient sky particles), `1` = visible surface hit (with `outStatus.alpha` and surface `rgba`), `2` = occluded behind foreground geometry (cull non-overlay tokens).

World polyline indexing (`buildWorldCurve` / `evalWorldCurve`):
- Subdivide input 3D polyline points into segments shorter than `maxBridge` and accumulate exact 3D arc length `worldLength`.
- Evaluate `(worldPoint, worldTangent)` at exact meter distance `worldDist` along the 3D curve (linearly interpolated along the segment for crisp sharp corners without midpoint sag).
- Lock screen orientation from `worldTangent` projected `+0.025 m` ahead:

```js
function projectLockedTangent(worldCurve, worldPoint, worldTangent, viewProjection, cameraEye, viewWidth, viewHeight, outScreen) {
  const screenPos = projectPointToScreen(viewProjection, cameraEye, worldPoint, viewWidth, viewHeight);
  if (!screenPos) return false;
  const stepAhead = [
    worldPoint[0] + worldTangent[0] * 0.025,
    worldPoint[1] + worldTangent[1] * 0.025,
    worldPoint[2] + worldTangent[2] * 0.025,
  ];
  const nextScreenPos = projectPointToScreen(viewProjection, cameraEye, stepAhead, viewWidth, viewHeight);
  if (!nextScreenPos) return false;
  const deltaX = nextScreenPos.x - screenPos.x;
  const deltaY = nextScreenPos.y - screenPos.y;
  const tangentMag = Math.hypot(deltaX, deltaY);
  if (tangentMag < 1e-4) return false;
  const unitX = deltaX / tangentMag;
  const unitY = deltaY / tangentMag;
  const rawSign = worldCurve.isVertical ? (unitY >= 0 ? 1 : -1) : (unitX >= 0 ? 1 : -1);
  outScreen.x = screenPos.x;
  outScreen.y = screenPos.y;
  outScreen.dist = screenPos.distance;
  outScreen.tx = unitX * rawSign;
  outScreen.ty = unitY * rawSign;
  outScreen.rawSign = rawSign;
  outScreen.pxPerMeter = tangentMag / 0.025;
  return true;
}
```

## Anti-glitch orbit stabilization

Four root causes create visible flickering, blinking, or glyph swapping during smooth camera orbits. Fix all four simultaneously:

1. **Remove screen-space `occupancyGrid` on curve glyphs**:
   - *Why it fails:* When a curved surface rotates slightly, two neighbors move `0.5 px` closer; whichever previously lost the occupancy stamp now loses or flips its bounding check, shifting all downstream glyphs by 1 slot in a visible domino wave.
   - *Fix:* Place symbols purely at fixed world-space intervals `worldDist = slotIndex * worldStep`. Control density statically with `worldStep` per zone (`0.145 * fontScale` for bold silhouettes, `0.115 * fontScale` for body fills, `0.088 * fontScale` for fine interior details).
2. **Even/odd continuous `foreshortenFade` instead of binary drop**:
   - *Fix:* Measure `projectedStepPx = probe.pxPerMeter * worldStep`. Fade odd slots out first as surfaces turn edge-on, keeping even slots legible longer:
   ```js
   const foreshortenFade = (slotIndex & 1) === 0
     ? smoothRange(unitSize * 0.32, unitSize * 0.72, projectedStepPx)
     : smoothRange(unitSize * 0.78, unitSize * 1.28, projectedStepPx);
   ```
   - Combine with smooth tangent-flip damping on closed loops: `turnFade = worldCurve.closed ? smoothRange(0.06, 0.26, Math.abs(probe.tx)) : 1.0`. Skip only when combined alpha drops under `0.04`.
3. **Fixed painter `ZONE_ORDER` (no `cameraEye` anchor sort)**:
   - *Why it fails:* Sorting equal-priority organs by `hypot(anchor - cameraEye)` swaps front-to-back draw order the instant two anchors cross equal distance during an orbit.
   - *Fix:* Define a deterministic layer order table (`ZONE_ORDER`) and preserve original definition index as tie-breaker:
   ```js
   const ZONE_ORDER = {
     stage: 0,
     body: 1,
     bench: 2,
     structure: 3,
     interior: 4,
     detail: 5,
     silhouette: 6,
     overlay: 7,
   };
   ```
4. **Closed structural perimeters & generous curved `depthTol`**:
   - Close lid contours (`closed: true`), base plinths, and rectangular furniture rims completely so no corner appears open when viewed from diagonal angles.
   - Set `depthTol` to `0.26..0.30` on broad shells/silhouettes/stage and `0.22..0.24` on compact interior mechanisms.
