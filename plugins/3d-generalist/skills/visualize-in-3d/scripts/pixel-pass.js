// Pixel pass for Crucible: a real 3D scene drawn at full size and then reduced to a low-res pixel grid by one user post
// pass (docs/user-passes.md in the crucible repo): nearest-neighbour blocks, outlines from depth edges, light crease lines
// from normal edges, optional palette quantising with Bayer dither. Beside it: toon light as material fields, a
// dither-dissolve material hook and a camera frame snapped to the pixel grid. Used by the "pixel diorama" look
// (references/looks.md). No three.js: it imports nothing.
//
// Copy this file into an app (src/pixel-pass.js). Needs @codepawlhq/crucible 0.21 or newer.
//
//   import { CrucibleRenderer } from '@codepawlhq/crucible';
//   import { installUserPasses } from '@codepawlhq/crucible/addons/user-pass';
//   import { installRenderPasses } from '@codepawlhq/crucible/addons/render-passes';   // toon light and the crease
//   import { installLineArt } from '@codepawlhq/crucible/addons/line-art';             // object list need these two
//   // A recipe with a material snippet needs: await loadAgentSceneModules(recipe) before createAgentScene.
//   const renderer = new CrucibleRenderer(canvas, scene.parts, { depth: true, samples: 4, ground: false, pixelRatio: 1 });
//   installLineArt(installRenderPasses(renderer));
//   installUserPasses(renderer);
//   const pixelPass = createPixelPass({ pixelScale: 5, outlineColor: 0x1b1722, palette: [0xf4f1e8, 0x5b8c4a] });
//   // canvas width and height must be multiples of pixelScale (1920x1080 with 5 gives a 384x216 grid)
//   const frame = snapOrthographicFrame({ focus: [0, 0, 0], azimuthDegrees: -135, elevationDegrees: 30,
//       distance: 120, viewHeight: 40, canvasHeight: 1080, pixelScale: 5 });
//   pixelPass.render(renderer, frame);                    // every frame instead of renderer.render(frame)
//
// A recipe works too: put `pixelPass.descriptor(frame)` into `postPasses`.
// Materials: { color, ...toonMaterialFields(3) } and, for fades, { snippet: dissolve.snippet } (see createDitherDissolve).

export const MAXIMUM_PALETTE_COLORS = 12;

// 4096 bytes of code is the limit for a pass, comments not counted. Uniforms (16 at most): edge = (depth threshold in
// world units, normal threshold 0..2, crease darkness, outline tint), outlineColor, forward (camera view direction),
// paletteInfo = (colour count, dither strength) and colour0..colour11 for the palette.
const PIXEL_PASS_FRAGMENT = /* glsl */ `
const float bayer[16] = float[16](0.0, 8.0, 2.0, 10.0, 12.0, 4.0, 14.0, 6.0, 3.0, 11.0, 1.0, 9.0, 15.0, 7.0, 13.0, 5.0);
const vec2 offsets[4] = vec2[4](vec2(1.0, 0.0), vec2(-1.0, 0.0), vec2(0.0, 1.0), vec2(0.0, -1.0));

// Full-size pixel uv at the middle of a low-res cell, so colour, depth and normal all read the same pixel.
vec2 pixelUv(vec2 cell) {
  vec2 full = vec2(textureSize(sceneColor, 0));
  vec2 inside = clamp(cell, vec2(0.0), resolution - 1.0);
  return (floor((inside + 0.5) * full / resolution) + 0.5) / full;
}

// Distance along the view direction; the background counts as very far.
float depthOf(vec2 cell) {
  vec2 uv = pixelUv(cell);
  if (depthAt(uv) >= 1.0) return 10000.0;
  return dot(worldPointAt(uv) - cameraEye, forward);
}

vec3 snapToPalette(vec3 colour, vec2 cell) {
  if (paletteInfo.x < 0.5) return colour;
  vec3 colours[12] = vec3[12](colour0, colour1, colour2, colour3, colour4, colour5, colour6, colour7, colour8, colour9, colour10, colour11);
  ivec2 corner = ivec2(mod(cell, 4.0));
  vec3 biased = colour + ((bayer[corner.y * 4 + corner.x] + 0.5) / 16.0 - 0.5) * paletteInfo.y;
  vec3 best = colours[0];
  float bestDistance = 1.0e9;
  for (int index = 0; index < 12; index++) {
    vec3 difference = biased - colours[index];
    float distanceSquared = dot(difference, difference);
    if (float(index) < paletteInfo.x && distanceSquared < bestDistance) {
      bestDistance = distanceSquared;
      best = colours[index];
    }
  }
  return best;
}

vec4 userPass(vec2 uv) {
  vec2 cell = floor(gl_FragCoord.xy);
  vec2 centreUv = pixelUv(cell);
  vec3 colour = texture(sceneColor, centreUv).rgb;
  float centreDepth = depthOf(cell);
  vec3 centreNormal = worldNormalAt(centreUv);
  float nearestDepth = centreDepth;
  vec3 nearestColour = colour;
  float crease = 0.0;
  for (int index = 0; index < 4; index++) {
    vec2 neighbour = cell + offsets[index];
    float neighbourDepth = depthOf(neighbour);
    if (neighbourDepth < nearestDepth) {
      nearestDepth = neighbourDepth;
      nearestColour = texture(sceneColor, pixelUv(neighbour)).rgb;
    }
    if (abs(neighbourDepth - centreDepth) < edge.x && length(worldNormalAt(pixelUv(neighbour)) - centreNormal) >= edge.y) crease = 1.0;
  }
  // No creases on the background or on parts listed in the pass's objects (smoke, dust).
  if (centreDepth > 5000.0 || objectSlotAt(centreUv) >= 0) crease = 0.0;
  // The outline is the cell behind a clearly nearer neighbour, so it sits just outside the silhouette.
  float isOutline = step(edge.x, centreDepth - nearestDepth);
  vec3 lineColour = mix(outlineColor, nearestColour * 0.35, edge.w);
  colour = snapToPalette(mix(colour, colour * (1.0 - edge.z), crease), cell);
  return vec4(mix(colour, lineColour, isOutline), 1.0);
}
`;

function hexToDisplayColor(hex) {
  return [((hex >> 16) & 255) / 255, ((hex >> 8) & 255) / 255, (hex & 255) / 255];
}

// Creates the pass. Options: pixelScale (screen pixels per low-res pixel, 1 to 20), outlineColor (hex), outlineTint
// (0 flat outline colour, 1 the darkened colour of the near object), depthEdgeThreshold (world units),
// normalEdgeThreshold (0..2), creaseDarkness (0 = no inner lines), palette (up to 12 hex sRGB colours or null),
// paletteDither (0 off, about 0.1 to 0.3 visible), creaseExcludedParts (up to 16 part names that get no crease lines).
export function createPixelPass(options = {}) {
  const pixelScale = options.pixelScale ?? 5;
  if (!(pixelScale >= 1 && pixelScale <= 20)) throw new RangeError('pixelScale must be between 1 and 20 (a Crucible pass scale is 0.05 to 1).');
  const pass = {
    pixelScale,
    name: 'pixel-pass',
    scale: 1 / pixelScale,
    fragment: PIXEL_PASS_FRAGMENT,
    uniforms: {
      edge: [options.depthEdgeThreshold ?? 0.55, options.normalEdgeThreshold ?? 0.9, options.creaseDarkness ?? 0.22, options.outlineTint ?? 0.35],
      outlineColor: hexToDisplayColor(options.outlineColor ?? 0x1b1722),
      forward: [0, 0, -1],
      paletteInfo: [0, 0],
    },
    ...(options.creaseExcludedParts?.length ? { objects: [...options.creaseExcludedParts] } : {}),
  };
  for (let slot = 0; slot < MAXIMUM_PALETTE_COLORS; slot++) pass.uniforms[`colour${slot}`] = [0, 0, 0];

  // Hex sRGB colours, or null to switch quantising off. Colours past the twelfth are ignored.
  pass.setPalette = (hexColors, ditherStrength = pass.uniforms.paletteInfo[1]) => {
    const colors = (hexColors ?? []).slice(0, MAXIMUM_PALETTE_COLORS);
    colors.forEach((hex, slot) => { pass.uniforms[`colour${slot}`] = hexToDisplayColor(hex); });
    pass.uniforms.paletteInfo = [colors.length, ditherStrength];
  };
  if (options.palette) pass.setPalette(options.palette, options.paletteDither ?? 0);

  // The pass as Crucible takes it (recipe `postPasses` entry or `renderer.userPasses.set` item), with the view direction of `frame`.
  pass.descriptor = (frame) => {
    if (frame) pass.uniforms.forward = viewDirection(frame);
    const { name, scale, fragment, uniforms, objects } = pass;
    return { name, scale, fragment, uniforms: { ...uniforms }, ...(objects ? { objects } : {}) };
  };

  // Draws `frame` through the pass. Call it every frame instead of renderer.render(frame).
  pass.render = (renderer, frame) => {
    // The pass reads part ids from the object ID pass, which Crucible draws only when asked, and before the beauty frame.
    if (pass.objects) renderer.render({ ...frame, pass: 'objectId' });
    renderer.userPasses.set([pass.descriptor(frame)]);
    renderer.render(frame);
  };
  return pass;
}

function viewDirection(frame) {
  const { eye, target } = frame;
  const direction = [target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]];
  const length = Math.hypot(...direction);
  return direction.map((component) => component / length);
}

// Toon light is native in Crucible: spread these fields into a material. `tones` flat bands from `darkest` to 1,
// as grey weights on the light (add a tint with your own toonColors). Raise the ambient light to lift the dark side.
export function toonMaterialFields(tones = 3, darkest = 0.5) {
  const levels = Array.from({ length: tones }, (_, tone) => (tones === 1 ? 1 : darkest + (1 - darkest) * (tone / (tones - 1))));
  return { toon: tones, toonColors: levels.map((level) => [level, level, level]) };
}

// Ordered 4x4 Bayer dissolve as a material fragment hook. The cell is `pixelScale` screen pixels, so the dither cells
// line up with the pixel grid. Parts of one group fade together (every material that carries the same code shares
// one `amount`); give a second fading set its own `group` number. Put `dissolve.snippet` in a material and call
// dissolve.setAmount(scene, renderer, [materialIds], 0.5) each frame (0 solid, 1 gone; no recompile, about 1 ms).
// The shadow of a dissolving part dithers on the shadow map's own pixel grid, so it fades softly, not in blocks.
export function createDitherDissolve({ pixelScale = 5, group = 0 } = {}) {
  const marker = `dissolveGroup${group}`;
  const snippet = {
    uniforms: { amount: 0, cellSize: pixelScale },
    fragment: `
const float ${marker} = 1.0;
const float bayer[16] = float[16](0.0, 8.0, 2.0, 10.0, 12.0, 4.0, 14.0, 6.0, 3.0, 11.0, 1.0, 9.0, 15.0, 7.0, 13.0, 5.0);
void materialHook(inout vec3 color, inout float alpha, vec2 uv, vec3 worldPosition) {
  ivec2 cell = ivec2(gl_FragCoord.xy / cellSize) & 3;
  if ((bayer[cell.y * 4 + cell.x] + 0.5) / 16.0 < amount) discard;
}`,
  };
  // Sets the amount on these recipe materials with the scene's own edit and hands the new parts to the renderer. Writing
  // the uniform on a part in place does nothing: Crucible keeps one value per snippet code, set when a material is made.
  const setAmount = (scene, renderer, materialIds, amount) => {
    scene.apply(
      materialIds.map((id) => ({ type: 'set-material', id, snippet: { ...snippet, uniforms: { ...snippet.uniforms, amount } } })),
      { expectedRevision: scene.revision },
    );
    renderer.replaceParts(scene.parts);
  };
  return { snippet, setAmount };
}

// A camera frame for renderer.render(frame): orthographic, looking at `focus` from the compass azimuth and elevation
// (degrees). The target slides along the camera's own right and up axes onto whole low-res pixels, so every world
// texel stays on one image texel while `focus` moves continuously, which removes shimmer. The camera therefore steps
// in whole low-res pixels; unlike the three.js version there is no sub-pixel residual that slides the upscaled image.
export function snapOrthographicFrame({ focus, azimuthDegrees, elevationDegrees, distance, viewHeight, canvasHeight, pixelScale }) {
  const azimuth = (azimuthDegrees * Math.PI) / 180;
  const elevation = (elevationDegrees * Math.PI) / 180;
  const towardCamera = [Math.sin(azimuth) * Math.cos(elevation), Math.sin(elevation), Math.cos(azimuth) * Math.cos(elevation)];
  const right = normalise(cross([0, 1, 0], towardCamera));
  const up = normalise(cross(towardCamera, right));

  const unitsPerPixel = viewHeight / Math.round(canvasHeight / pixelScale);
  const rightOffset = Math.round(dot(focus, right) / unitsPerPixel) * unitsPerPixel - dot(focus, right);
  const upOffset = Math.round(dot(focus, up) / unitsPerPixel) * unitsPerPixel - dot(focus, up);
  const target = focus.map((component, axis) => component + right[axis] * rightOffset + up[axis] * upOffset);
  const eye = target.map((component, axis) => component + towardCamera[axis] * distance);
  return { eye, target, up: [0, 1, 0], near: 0.5, far: distance * 2.2, projection: 'orthographic', orthoScale: viewHeight };
}

function dot(first, second) {
  return first[0] * second[0] + first[1] * second[1] + first[2] * second[2];
}

function cross(first, second) {
  return [
    first[1] * second[2] - first[2] * second[1],
    first[2] * second[0] - first[0] * second[2],
    first[0] * second[1] - first[1] * second[0],
  ];
}

function normalise(vector) {
  const length = Math.hypot(...vector);
  return vector.map((component) => component / length);
}
