// Finds flat surfaces that fight for the same depth (z-fighting): two thin parts, flat along the same axis, whose
// faces overlap and lie within `tolerance` metres of each other. It checks all three axes, so it catches a sign on a
// windscreen or a poster on a wall as well as paint on a road. Run it in the page once the world is built:
//   import { findCoplanarPairs } from './coplanar-check.js';
//   console.table(findCoplanarPairs(parts));
// `parts` are Crucible parts, { name, geometry: { positions }, matrix, material?, visible? }, with `matrix` the 16-number
// column-major world matrix, as passed to CrucibleRenderer; a part or nested arrays of parts also work. Each part's
// bounds come from its vertices in world space. Skipped: hidden parts (part.visible === false or
// part.visibility?.visible === false), skinned parts (part.skin), instanced parts (part.instances) and see-through
// materials (material.opacity below 0.5). Pairs are named by part.name, '(unnamed)' when it has none.
// Fix every pair it reports: remove the hidden surface, or move the layers at least 3 cm apart.
// Dependencies: none. Copy this file into the app next to your render code.

const FLAT_RATIO = 0.05;
const AXES = [0, 1, 2];
const AXIS_NAMES = ['x', 'y', 'z'];

function flattenParts(parts) {
  return Array.isArray(parts) ? parts.flatMap(flattenParts) : [parts];
}

/** World bounds { min, max } of a part from its vertices, or null when it has none. */
function worldBounds(part) {
  const { positions } = part.geometry;
  const matrix = part.matrix;
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let offset = 0; offset < positions.length; offset += 3) {
    const localX = positions[offset];
    const localY = positions[offset + 1];
    const localZ = positions[offset + 2];
    for (const axis of AXES) {
      const world = matrix[axis] * localX + matrix[axis + 4] * localY + matrix[axis + 8] * localZ + matrix[axis + 12];
      min[axis] = Math.min(min[axis], world);
      max[axis] = Math.max(max[axis], world);
    }
  }
  return min[0] === Infinity ? null : { min, max };
}

/** The axes along which this box is thin, each with the two other axes that span its face. */
function flatAxes(box) {
  const size = AXES.map((axis) => box.max[axis] - box.min[axis]);
  const result = [];
  for (const axis of AXES) {
    const others = AXES.filter((other) => other !== axis);
    const span = Math.max(size[others[0]], size[others[1]]);
    if (size[others[0]] <= 0 || size[others[1]] <= 0) continue;
    if (size[axis] <= FLAT_RATIO * span || size[axis] <= 0.3) result.push({ axis, others });
  }
  return result;
}

function overlapArea(first, second, others) {
  const [one, two] = others;
  const overlapOne = Math.min(first.max[one], second.max[one]) - Math.max(first.min[one], second.min[one]);
  const overlapTwo = Math.min(first.max[two], second.max[two]) - Math.max(first.min[two], second.min[two]);
  if (overlapOne <= 0 || overlapTwo <= 0) return 0;
  return overlapOne * overlapTwo;
}

/** The smallest distance between a face of one box and the same-facing face of the other, along the axis. */
function faceGap(first, second, axis) {
  const maxGap = Math.abs(first.max[axis] - second.max[axis]);
  const minGap = Math.abs(first.min[axis] - second.min[axis]);
  return Math.min(maxGap, minGap);
}

function isCandidate(part) {
  if (part.visible === false || part.visibility?.visible === false || part.skin || part.instances) return false;
  return !(part.material && part.material.opacity < 0.5);
}

export function findCoplanarPairs(parts, { tolerance = 0.03, minimumArea = 0.05 } = {}) {
  const flats = [];
  for (const part of flattenParts(parts)) {
    if (!isCandidate(part)) continue;
    const box = worldBounds(part);
    if (!box) continue;
    const axes = flatAxes(box);
    if (axes.length) flats.push({ name: part.name || '(unnamed)', box, axes });
  }
  const pairs = [];
  for (let first = 0; first < flats.length; first++) {
    for (let second = first + 1; second < flats.length; second++) {
      for (const { axis, others } of flats[first].axes) {
        if (!flats[second].axes.some((entry) => entry.axis === axis)) continue;
        const gap = faceGap(flats[first].box, flats[second].box, axis);
        if (gap >= tolerance) continue;
        const area = overlapArea(flats[first].box, flats[second].box, others);
        if (area < minimumArea) continue;
        pairs.push({ first: flats[first].name, second: flats[second].name, axis: AXIS_NAMES[axis], gapCm: +(gap * 100).toFixed(1), overlapM2: +area.toFixed(2) });
        break;
      }
    }
  }
  return pairs.sort((left, right) => right.overlapM2 - left.overlapM2);
}
