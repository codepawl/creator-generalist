// Frame guard for Crucible apps: measures where the film's subjects land on screen, every frame, so a render fails on the
// faults a viewer sees first (a creature cut by the frame edge, shrunk to a few pixels, or buried under smoke), and checks
// that resting objects and hands really touch what they rest on. Three guards live here, each used inside renderAt(time).
//
// Inputs are Crucible data, not a scene graph. A part is { name, geometry: { positions, indices, skinIndices?, skinWeights? },
// matrix, material, skin?, visible? } with `matrix` the 16-number column-major WORLD matrix, as passed to CrucibleRenderer.
// Wherever the API takes an "object" it takes one part, or an array of parts (arrays may nest), so a former group is simply
// the array of its parts. A part is hidden when part.visible === false or part.visibility?.visible === false (the renderer's
// own test); hidden parts are skipped everywhere. The camera is the frame object passed to renderer.render(frame):
// { eye, target, up = [0, 1, 0], fov = 45, near = 0.1, far = 100, projection = 'perspective' | 'orthographic',
// orthoScale = 4, focalLength, sensorWidth, shift }. The projection below repeats src/camera.js applyProjection and
// gl-matrix lookAt exactly, with no import, so a screen box matches the rendered pixels.
//
// 1. Screen guard. In renderAt(time):
//      const report = measureSubjects(frame, subjects, { width: 384, height: 216, margin: 6 });
//      frameLog.push({ time, report });
//    Then at the end of a render: const faults = findFaults(frameLog, { minHeightPixels: 24 });
//    `subjects` is a list of { name, object, occluders? } where occluders are parts (smoke, steam, beams) whose screen
//    boxes count against the subject's visible share. screenBox(frame, object, width, height) is the box of the world bounds
//    of the visible parts, projected: { left, right, top, bottom } in pixels, or null when nothing is visible. A box that
//    reaches behind the camera plane spans the whole plane (infinite edges), so it reads as outside the frame.
//
// 2. Contact guard (measureContacts): for objects that rest on a surface (papers, a mug, a folder on a desk), checks every
//    frame that nothing sinks into the surface or sits so close that it z-fights:
//      const contacts = measureContacts([{ name: 'invoice', object: invoiceParts, surface: deskParts }], { minimumGap: 0.0003 });
//      if (contacts.some((entry) => !entry.ok)) { /* log it with the time and fail the render */ }
//    `surface` is a horizontal mesh (one part, an array of parts, or a scene query from createSceneQuery, whose top is found
//    by a ray from above), a world height (number) or a function (worldX, worldZ) => worldY. For parts the file builds a
//    scene query once per surface and keeps it, so the ray reads each part's matrix as it is at call time; skinned or morphed
//    parts never block that ray (Crucible's scene query skips them). Every vertex of every visible part of `object` is taken
//    to world space and compared with the surface below it. A vertex lower than the surface is a 'penetration'; one above it
//    by less than `minimumGap` is a 'z-fight'. Parts with part.contactIgnore === true are skipped. Each result is
//    { name, ok, lowestGap, vertexCount, faults: [{ kind, gap, worldPosition }] }, faults capped by maxFaultsPerObject.
//    Skinned parts (a rigged character lying on a bed) are sampled posed: Crucible has no CPU posed-vertex helper, so
//    worldVertex blends part.skin.jointMatrices (the mesh-local palette) over the four skinIndices and skinWeights, then
//    applies part.matrix, as the GPU shader and the path tracer do. Update the palette (pose.apply) before calling it.
//    Morph targets are not applied. A pair may also set side: 'below' (the object must stay under the surface, e.g. a body
//    under a blanket; the gap is surface minus vertex) and vertexFilter(part, vertexIndex) => boolean to measure only some
//    vertices (e.g. not the hands).
//
// 3. Grip guard (registerGrip / measureGrips): a hand that holds, pulls or turns something must TOUCH it. A hand animated to
//    be "near" a prop reads as floating, so every hand-on-object moment registers a grip and the render fails when they
//    separate.
//      1. Name a socket on the prop: { part, localPoint } is a point in the prop part's local space (a panel's edge, a
//         lever's tip) that moves with part.matrix.
//      2. Name a contact on the hand: { pose, joint, localPoint } is a point in the local space of a skeleton joint
//         (the palm or finger crook that should touch the socket), read from pose.jointWorld(joint). localPoint defaults
//         to [0, 0, 0]. Either side may also be a function () => [x, y, z] in world space, or a fixed world point [x, y, z].
//      3. Once, at build time: registerGrip({ name: 'panel-edge', contact: { pose, joint: 'rightHand', localPoint },
//         socket: { part: panel, localPoint: [0.5, 0, 0] }, from: 126.5, to: 127.1 }).
//         from/to are the seconds in which the hand is fully on the prop, not the approach or the release.
//      4. Each frame, after two-bone IK has put the contact on the socket (pose.apply(time) first): const results =
//         measureGrips(time). Fail the render when any result has ok false (distance in metres, GRIP_LIMIT = 1 cm). Each
//         result is { name, distance, active, ok }.
//    The prop's motion stays time-driven and the arm follows it. When the arm cannot reach, the body turns, leans and
//    steps; look at that move in the shot, since a lunge across a low camera blacks out the frame. A push near the hinge
//    needs less reach than the edge.
//
// Dependencies: "@codepawlhq/crucible" (tested with 0.21.0), only for the scene query used by surface parts. Copy this
// file into the app next to your render code; the app must resolve that package (import map or bundler).
import { createSceneQuery } from '@codepawlhq/crucible/addons/scene-query';

function isHidden(part) {
  return part.visible === false || part.visibility?.visible === false;
}

/** Flattens a part, or arrays of parts, into the list of parts that are not hidden. */
function visibleParts(object) {
  if (!object) {
    return [];
  }
  if (Array.isArray(object)) {
    return object.flatMap(visibleParts);
  }
  return isHidden(object) ? [] : [object];
}

function isSkinned(part) {
  const { skinIndices, skinWeights } = part.geometry;
  return Boolean(part.skin?.jointMatrices && skinIndices && skinWeights);
}

const posedPoint = [0, 0, 0];

/** Calls visit(x, y, z, vertexIndex) with the world position of every vertex of the part, posed when it is skinned. */
function forEachWorldVertex(part, visit) {
  const { positions, skinIndices, skinWeights } = part.geometry;
  const matrix = part.matrix;
  const vertexCount = positions.length / 3;
  const palette = isSkinned(part) ? part.skin.jointMatrices : null;
  for (let vertexIndex = 0; vertexIndex < vertexCount; vertexIndex += 1) {
    let localX = positions[vertexIndex * 3];
    let localY = positions[vertexIndex * 3 + 1];
    let localZ = positions[vertexIndex * 3 + 2];
    if (palette) {
      const bindX = localX;
      const bindY = localY;
      const bindZ = localZ;
      let totalWeight = 0;
      posedPoint[0] = 0;
      posedPoint[1] = 0;
      posedPoint[2] = 0;
      for (let influence = 0; influence < 4; influence += 1) {
        const weight = skinWeights[vertexIndex * 4 + influence];
        if (!(weight > 0)) {
          continue;
        }
        const joint = skinIndices[vertexIndex * 4 + influence] * 16;
        totalWeight += weight;
        posedPoint[0] += weight * (palette[joint] * bindX + palette[joint + 4] * bindY + palette[joint + 8] * bindZ + palette[joint + 12]);
        posedPoint[1] += weight * (palette[joint + 1] * bindX + palette[joint + 5] * bindY + palette[joint + 9] * bindZ + palette[joint + 13]);
        posedPoint[2] += weight * (palette[joint + 2] * bindX + palette[joint + 6] * bindY + palette[joint + 10] * bindZ + palette[joint + 14]);
      }
      if (totalWeight > 0) {
        localX = posedPoint[0] / totalWeight;
        localY = posedPoint[1] / totalWeight;
        localZ = posedPoint[2] / totalWeight;
      }
    }
    visit(
      matrix[0] * localX + matrix[4] * localY + matrix[8] * localZ + matrix[12],
      matrix[1] * localX + matrix[5] * localY + matrix[9] * localZ + matrix[13],
      matrix[2] * localX + matrix[6] * localY + matrix[10] * localZ + matrix[14],
      vertexIndex,
    );
  }
}

/** World bounds { min: [x, y, z], max: [x, y, z] } of the visible parts, or null when they hold no vertex. */
function worldBounds(object) {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (const part of visibleParts(object)) {
    forEachWorldVertex(part, (x, y, z) => {
      min[0] = Math.min(min[0], x);
      min[1] = Math.min(min[1], y);
      min[2] = Math.min(min[2], z);
      max[0] = Math.max(max[0], x);
      max[1] = Math.max(max[1], y);
      max[2] = Math.max(max[2], z);
    });
  }
  return min[0] === Infinity ? null : { min, max };
}

function normalized(vector) {
  const length = Math.hypot(vector[0], vector[1], vector[2]);
  return [vector[0] / length, vector[1] / length, vector[2] / length];
}

/** Builds project(x, y, z) => { pixelX, pixelY, inFront } with Crucible's view and projection matrices for a width x height image. */
function createProjector(camera, width, height) {
  const aspect = width / height;
  const eye = camera.eye;
  const up = camera.up ?? [0, 1, 0];
  const backAxis = normalized([eye[0] - camera.target[0], eye[1] - camera.target[1], eye[2] - camera.target[2]]);
  const rightAxis = normalized([
    up[1] * backAxis[2] - up[2] * backAxis[1],
    up[2] * backAxis[0] - up[0] * backAxis[2],
    up[0] * backAxis[1] - up[1] * backAxis[0],
  ]);
  const upAxis = [
    backAxis[1] * rightAxis[2] - backAxis[2] * rightAxis[1],
    backAxis[2] * rightAxis[0] - backAxis[0] * rightAxis[2],
    backAxis[0] * rightAxis[1] - backAxis[1] * rightAxis[0],
  ];
  const [shiftX, shiftY] = camera.shift ?? [0, 0];
  const orthographic = camera.projection === 'orthographic';
  let fieldOfViewDegrees = camera.fov ?? 45;
  if (camera.focalLength !== undefined) {
    fieldOfViewDegrees = (2 * Math.atan(((camera.sensorWidth ?? 36) / aspect / camera.focalLength) / 2) * 180) / Math.PI;
  }
  const focalScale = 1 / Math.tan((fieldOfViewDegrees * Math.PI) / 360);
  const halfHeight = (camera.orthographicHeight ?? camera.orthoScale ?? 4) / 2;

  return (x, y, z) => {
    const offsetX = x - eye[0];
    const offsetY = y - eye[1];
    const offsetZ = z - eye[2];
    const viewX = rightAxis[0] * offsetX + rightAxis[1] * offsetY + rightAxis[2] * offsetZ;
    const viewY = upAxis[0] * offsetX + upAxis[1] * offsetY + upAxis[2] * offsetZ;
    const viewZ = backAxis[0] * offsetX + backAxis[1] * offsetY + backAxis[2] * offsetZ;
    let ndcX;
    let ndcY;
    let inFront = true;
    if (orthographic) {
      ndcX = viewX / (halfHeight * aspect) - 2 * shiftX;
      ndcY = viewY / halfHeight - 2 * shiftY;
    } else {
      const clipW = -viewZ;
      inFront = clipW > 0;
      ndcX = (focalScale / aspect * viewX + 2 * shiftX * viewZ) / clipW;
      ndcY = (focalScale * viewY + 2 * shiftY * viewZ) / clipW;
    }
    return { pixelX: (ndcX * 0.5 + 0.5) * width, pixelY: (1 - (ndcY * 0.5 + 0.5)) * height, inFront };
  };
}

export function screenBox(camera, object, width, height) {
  const bounds = worldBounds(object);
  if (!bounds) {
    return null;
  }
  const project = createProjector(camera, width, height);
  let left = Infinity;
  let right = -Infinity;
  let top = Infinity;
  let bottom = -Infinity;
  for (let index = 0; index < 8; index += 1) {
    const { pixelX, pixelY, inFront } = project(
      index & 1 ? bounds.max[0] : bounds.min[0],
      index & 2 ? bounds.max[1] : bounds.min[1],
      index & 4 ? bounds.max[2] : bounds.min[2],
    );
    if (!inFront) {
      return { left: -Infinity, right: Infinity, top: -Infinity, bottom: Infinity };
    }
    left = Math.min(left, pixelX);
    right = Math.max(right, pixelX);
    top = Math.min(top, pixelY);
    bottom = Math.max(bottom, pixelY);
  }
  return { left, right, top, bottom };
}

function overlapArea(first, second) {
  const overlapWidth = Math.max(0, Math.min(first.right, second.right) - Math.max(first.left, second.left));
  const overlapHeight = Math.max(0, Math.min(first.bottom, second.bottom) - Math.max(first.top, second.top));
  return overlapWidth * overlapHeight;
}

function boxArea(rectangle) {
  return Math.max(0, rectangle.right - rectangle.left) * Math.max(0, rectangle.bottom - rectangle.top);
}

// Visible share is approximate: occluder boxes are rectangles and may overlap each other, so the
// share is a floor. Only count occluders that are actually opaque this frame (dissolve below 0.5).
export function measureSubjects(camera, subjects, { width, height, margin = 4 }) {
  return subjects.map(({ name, object, occluders = [] }) => {
    const rectangle = screenBox(camera, object, width, height);
    if (!rectangle) {
      return { name, hidden: true };
    }
    const outside =
      rectangle.left < margin ||
      rectangle.top < margin ||
      rectangle.right > width - margin ||
      rectangle.bottom > height - margin;
    let coveredArea = 0;
    for (const occluder of occluders) {
      const occluderBox = screenBox(camera, occluder, width, height);
      if (occluderBox) {
        coveredArea += overlapArea(rectangle, occluderBox);
      }
    }
    const area = boxArea(rectangle);
    const visibleShare = area > 0 ? Math.max(0, 1 - coveredArea / area) : 0;
    return {
      name,
      rectangle,
      heightPixels: rectangle.bottom - rectangle.top,
      outside,
      visibleShare,
    };
  });
}

// Faults that last longer than `graceSeconds` in a row. A subject meant to leave the frame
// (an exit, a recall) is listed in `allowed` as { name, from, to }.
export function findFaults(frameLog, { minHeightPixels = 24, minVisibleShare = 0.5, graceSeconds = 0.3, allowed = [] } = {}) {
  const faults = [];
  const openRuns = new Map();
  const isAllowed = (name, time) => allowed.some((entry) => entry.name === name && time >= entry.from && time <= entry.to);
  const closeRun = (key, endTime) => {
    const run = openRuns.get(key);
    if (run && endTime - run.start > graceSeconds) {
      faults.push({ ...run, end: endTime });
    }
    openRuns.delete(key);
  };
  for (const { time, report } of frameLog) {
    for (const subject of report) {
      if (subject.hidden || isAllowed(subject.name, time)) {
        continue;
      }
      const problems = {
        outside: subject.outside,
        tiny: subject.heightPixels < minHeightPixels,
        covered: subject.visibleShare < minVisibleShare,
      };
      for (const [kind, present] of Object.entries(problems)) {
        const key = `${subject.name}:${kind}`;
        if (present && !openRuns.has(key)) {
          openRuns.set(key, { name: subject.name, kind, start: time });
        } else if (!present) {
          closeRun(key, time);
        }
      }
    }
  }
  const lastTime = frameLog.length ? frameLog[frameLog.length - 1].time : 0;
  for (const key of [...openRuns.keys()]) {
    closeRun(key, lastTime);
  }
  return faults;
}

const DOWN = [0, -1, 0];
// Keyed by the surface value the caller passes, so a desk built once is indexed once.
const surfaceQueries = new WeakMap();

function queryForSurface(surface) {
  if (typeof surface.raycast === 'function') {
    return surface;
  }
  let query = surfaceQueries.get(surface);
  if (!query) {
    query = createSceneQuery(Array.isArray(surface) ? surface.flat(Infinity) : [surface]);
    surfaceQueries.set(surface, query);
  }
  return query;
}

function surfaceHeightBelow(surface, worldX, worldY, worldZ) {
  if (typeof surface === 'number') {
    return surface;
  }
  if (typeof surface === 'function') {
    return surface(worldX, worldZ);
  }
  const hit = queryForSurface(surface).raycast({ origin: [worldX, worldY + 1000, worldZ], direction: DOWN, maxDistance: 3000 });
  return hit ? hit.point[1] : null;
}

// pairs: [{ name, object, surface, side = 'above', vertexFilter }]. options: { minimumGap = 0.0002, penetrationTolerance = 0, maxFaultsPerObject = 3 }.
export function measureContacts(pairs, { minimumGap = 0.0002, penetrationTolerance = 0, maxFaultsPerObject = 3 } = {}) {
  return pairs.map(({ name, object, surface, side = 'above', vertexFilter }) => {
    const faults = [];
    let lowestGap = Infinity;
    let vertexCount = 0;
    for (const part of visibleParts(object)) {
      if (part.contactIgnore || part.userData?.contactIgnore) {
        continue;
      }
      forEachWorldVertex(part, (worldX, worldY, worldZ, vertexIndex) => {
        if (vertexFilter && !vertexFilter(part, vertexIndex)) {
          return;
        }
        const surfaceY = surfaceHeightBelow(surface, worldX, worldY, worldZ);
        if (surfaceY === null) {
          return;
        }
        vertexCount += 1;
        const gap = side === 'below' ? surfaceY - worldY : worldY - surfaceY;
        lowestGap = Math.min(lowestGap, gap);
        const kind = gap < -penetrationTolerance ? 'penetration' : gap < minimumGap ? 'z-fight' : null;
        if (kind && faults.length < maxFaultsPerObject) {
          faults.push({ kind, gap, worldPosition: [worldX, worldY, worldZ] });
        }
      });
    }
    return { name, ok: faults.length === 0, lowestGap, vertexCount, faults };
  });
}

const registeredGrips = [];
export const GRIP_LIMIT = 0.01;

function describesWorldPoint(source) {
  return (
    typeof source === 'function' ||
    (Array.isArray(source) && source.length === 3) ||
    Boolean(source?.part?.matrix) ||
    typeof source?.pose?.jointWorld === 'function'
  );
}

export function registerGrip({ name, hand, contact, socket, from, to }) {
  for (const [label, source] of [['contact', contact], ['socket', socket]]) {
    if (!describesWorldPoint(source)) {
      throw new TypeError(`registerGrip ${name}: ${label} must be { part, localPoint }, { pose, joint, localPoint }, a world point or a function.`);
    }
  }
  const existing = registeredGrips.findIndex((grip) => grip.name === name);
  if (existing >= 0) {
    registeredGrips.splice(existing, 1);
  }
  registeredGrips.push({ name, hand, contact, socket, from, to });
}

/** Rotates a point by the quaternion [x, y, z, w] (Crucible's joint rotation order). */
function rotateByQuaternion([pointX, pointY, pointZ], [quaternionX, quaternionY, quaternionZ, quaternionW]) {
  const crossX = quaternionY * pointZ - quaternionZ * pointY + quaternionW * pointX;
  const crossY = quaternionZ * pointX - quaternionX * pointZ + quaternionW * pointY;
  const crossZ = quaternionX * pointY - quaternionY * pointX + quaternionW * pointZ;
  return [
    pointX + 2 * (quaternionY * crossZ - quaternionZ * crossY),
    pointY + 2 * (quaternionZ * crossX - quaternionX * crossZ),
    pointZ + 2 * (quaternionX * crossY - quaternionY * crossX),
  ];
}

/** The world position of a grip point source: a function, a world point, { part, localPoint } or { pose, joint, localPoint }. */
function worldPointOf(source) {
  if (typeof source === 'function') {
    return source();
  }
  if (Array.isArray(source)) {
    return source;
  }
  const [localX, localY, localZ] = source.localPoint ?? [0, 0, 0];
  if (source.part) {
    const matrix = source.part.matrix;
    return [
      matrix[0] * localX + matrix[4] * localY + matrix[8] * localZ + matrix[12],
      matrix[1] * localX + matrix[5] * localY + matrix[9] * localZ + matrix[13],
      matrix[2] * localX + matrix[6] * localY + matrix[10] * localZ + matrix[14],
    ];
  }
  const { position, rotation } = source.pose.jointWorld(source.joint);
  const rotated = rotateByQuaternion([localX, localY, localZ], rotation);
  return [position[0] + rotated[0], position[1] + rotated[1], position[2] + rotated[2]];
}

export function measureGrips(time, { limit = GRIP_LIMIT } = {}) {
  return registeredGrips.map((grip) => {
    if (time < grip.from || time > grip.to) {
      return { name: grip.name, distance: null, active: false, ok: true };
    }
    const contactPoint = worldPointOf(grip.contact);
    const socketPoint = worldPointOf(grip.socket);
    const distance = Math.hypot(contactPoint[0] - socketPoint[0], contactPoint[1] - socketPoint[1], contactPoint[2] - socketPoint[2]);
    return { name: grip.name, distance, active: true, ok: distance <= limit };
  });
}
