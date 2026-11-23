// Surface deviation between two triangle soups (flat arrays, 9 world-space numbers per triangle): points sampled on
// the reference by area, each one's distance to the nearest candidate triangle. This direction catches what a
// simplify deletes (a porch roof, lamp posts, shelf props), which meshoptimizer's own error bound lets through: on a
// Google Poly shed, error 0.08 removed the porch roof at 13.8 % of the diagonal (measured 2026-11-23).
// Returns max and p95 in percent of the reference diagonal. No dependencies, deterministic.

// Diagonal of the connected piece each triangle belongs to (pieces joined by shared corner positions), floored at
// floorShare of the whole model. A scene diagonal hides damage to small props: on a tavern, 2 % of the scene let
// lanterns, cups and bottles turn into blobs, because 2 % of the scene is about a whole cup.
const COLOUR_CHANGE = 0.1;
const PIECE_SAMPLES = 8;
const PIECE_BROKEN_SAMPLES = 3;
const PIECE_SHAPE_CHANGE = 0.05;

export function pieceScales(triangles, floorShare = 0.03) {
  return pieceIndex(triangles, floorShare).scales;
}

// Connected pieces of a triangle soup: pieceOf (piece number per triangle), pieceCount and scales (see pieceScales).
export function pieceIndex(triangles, floorShare = 0.03) {
  const count = triangles.length / 9;
  const parent = new Int32Array(count * 3);
  for (let index = 0; index < parent.length; index += 1) parent[index] = index;
  const find = (index) => {
    while (parent[index] !== index) {
      parent[index] = parent[parent[index]];
      index = parent[index];
    }
    return index;
  };
  const union = (first, second) => {
    const rootFirst = find(first);
    const rootSecond = find(second);
    if (rootFirst !== rootSecond) parent[rootFirst] = rootSecond;
  };
  const diagonal = referenceDiagonal(triangles) || 1;
  const step = diagonal * 1e-5;
  const cornerByPosition = new Map();
  for (let corner = 0; corner < count * 3; corner += 1) {
    const base = corner * 3;
    const key = `${Math.round(triangles[base] / step)},${Math.round(triangles[base + 1] / step)},${Math.round(triangles[base + 2] / step)}`;
    const existing = cornerByPosition.get(key);
    if (existing === undefined) cornerByPosition.set(key, corner);
    else union(corner, existing);
    if (corner % 3) union(corner, corner - 1);
  }
  const bounds = new Map();
  for (let triangle = 0; triangle < count; triangle += 1) {
    const root = find(triangle * 3);
    let box = bounds.get(root);
    if (!box) {
      box = [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity];
      bounds.set(root, box);
    }
    for (let corner = 0; corner < 3; corner += 1) {
      for (let axis = 0; axis < 3; axis += 1) {
        const value = triangles[triangle * 9 + corner * 3 + axis];
        box[axis] = Math.min(box[axis], value);
        box[axis + 3] = Math.max(box[axis + 3], value);
      }
    }
  }
  const scales = new Float64Array(count);
  const pieceOf = new Int32Array(count);
  const pieceNumbers = new Map();
  for (let triangle = 0; triangle < count; triangle += 1) {
    const root = find(triangle * 3);
    const box = bounds.get(root);
    scales[triangle] = Math.max(Math.hypot(box[3] - box[0], box[4] - box[1], box[5] - box[2]), diagonal * floorShare);
    if (!pieceNumbers.has(root)) pieceNumbers.set(root, pieceNumbers.size);
    pieceOf[triangle] = pieceNumbers.get(root);
  }
  return { scales, pieceOf, pieceCount: pieceNumbers.size };
}

// Colour at a point inside a triangle, from per-corner colours (9 numbers per triangle: rgb for each corner).
function colourAt(triangles, colours, triangle, x, y, z, target) {
  const base = triangle * 9;
  const v0 = [triangles[base + 3] - triangles[base], triangles[base + 4] - triangles[base + 1], triangles[base + 5] - triangles[base + 2]];
  const v1 = [triangles[base + 6] - triangles[base], triangles[base + 7] - triangles[base + 1], triangles[base + 8] - triangles[base + 2]];
  const v2 = [x - triangles[base], y - triangles[base + 1], z - triangles[base + 2]];
  const dot = (first, second) => first[0] * second[0] + first[1] * second[1] + first[2] * second[2];
  const d00 = dot(v0, v0);
  const d01 = dot(v0, v1);
  const d11 = dot(v1, v1);
  const d20 = dot(v2, v0);
  const d21 = dot(v2, v1);
  const denominator = d00 * d11 - d01 * d01;
  const weightSecond = denominator ? (d11 * d20 - d01 * d21) / denominator : 0;
  const weightThird = denominator ? (d00 * d21 - d01 * d20) / denominator : 0;
  const weightFirst = 1 - weightSecond - weightThird;
  for (let channel = 0; channel < 3; channel += 1) {
    target[channel] = weightFirst * colours[base + channel] + weightSecond * colours[base + 3 + channel] + weightThird * colours[base + 6 + channel];
  }
}

// options.scales (pieceScales of the reference) adds piece_p95 and piece_p99; options.referenceColours and
// options.candidateColours (per-corner rgb, same layout as the triangles) add colour_changed: the share of the
// surface, in %, whose colour moved by more than 0.1 in linear rgb. Vertex-coloured low-poly sets lose a painted
// pattern or a red door without moving any geometry, so a shape metric alone reads 0 there.
export function surfaceDeviation(referenceTriangles, candidateTriangles, sampleCount = 6000, options = {}) {
  const { referenceColours = null, candidateColours = null, pieces = null } = options;
  const scales = options.scales ?? pieces?.scales ?? null;
  const referenceCount = referenceTriangles.length / 9;
  const candidateCount = candidateTriangles.length / 9;
  if (!referenceCount) return { max: 0, p95: 0 };
  if (!candidateCount) return { max: 100, p95: 100 };
  const low = [Infinity, Infinity, Infinity];
  const high = [-Infinity, -Infinity, -Infinity];
  for (const triangles of [referenceTriangles, candidateTriangles]) {
    for (let index = 0; index < triangles.length; index += 3) {
      for (let axis = 0; axis < 3; axis += 1) {
        low[axis] = Math.min(low[axis], triangles[index + axis]);
        high[axis] = Math.max(high[axis], triangles[index + axis]);
      }
    }
  }
  const diagonal = referenceDiagonal(referenceTriangles) || 1;
  const grid = buildTriangleGrid(candidateTriangles, low, high);
  const { points, owners } = sampleSurface(referenceTriangles, sampleCount);
  const distances = new Float64Array(points.length / 3);
  const pieceRelative = new Float64Array(points.length / 3);
  const referenceColour = [0, 0, 0];
  const candidateColour = [0, 0, 0];
  let colourChanged = 0;
  const compareColours = Boolean(referenceColours && candidateColours);
  // Coincident faces of different colours (z-fighting duplicates, decals, two-sided cards) make the colour at a
  // point ambiguous on both sides: a monster kit whose hex tiles carry a grey and a white top face read 24 % changed
  // when simplify kept only the white one. So a point counts as changed only when no colour present there in the
  // reference is close to any colour present there in the result.
  const referenceGrid = compareColours ? buildTriangleGrid(referenceTriangles, low, high) : null;
  const referenceNearColours = [];
  for (const searchGrid of [grid, referenceGrid]) {
    if (!searchGrid) continue;
    searchGrid.keepNear = compareColours;
    searchGrid.tieDistance = diagonal * 1e-4;
  }
  // Distance from a point on the reference to the result; sets colourDifference when colours are compared.
  let colourDifference = 0;
  const measurePoint = (x, y, z) => {
    colourDifference = 0;
    if (compareColours) {
      nearestDistance(referenceGrid, referenceTriangles, x, y, z);
      referenceNearColours.length = 0;
      for (let entry = 0; entry < referenceGrid.near.length; entry += 5) {
        if (referenceGrid.near[entry + 1] > referenceGrid.tieDistance) continue;
        colourAt(referenceTriangles, referenceColours, referenceGrid.near[entry], x, y, z, referenceColour);
        referenceNearColours.push(referenceColour[0], referenceColour[1], referenceColour[2]);
      }
    }
    const distance = nearestDistance(grid, candidateTriangles, x, y, z);
    if (compareColours && referenceNearColours.length) {
      let smallestDifference = Infinity;
      const limit = distance * 1.5 + grid.tieDistance;
      for (let entry = 0; entry < grid.near.length; entry += 5) {
        if (grid.near[entry + 1] > limit) continue;
        colourAt(candidateTriangles, candidateColours, grid.near[entry], grid.near[entry + 2], grid.near[entry + 3], grid.near[entry + 4], candidateColour);
        for (let colourIndex = 0; colourIndex < referenceNearColours.length; colourIndex += 3) {
          const difference = Math.hypot(
            referenceNearColours[colourIndex] - candidateColour[0],
            referenceNearColours[colourIndex + 1] - candidateColour[1],
            referenceNearColours[colourIndex + 2] - candidateColour[2],
          );
          smallestDifference = Math.min(smallestDifference, difference);
        }
      }
      colourDifference = smallestDifference;
    }
    return distance;
  };
  for (let pointIndex = 0; pointIndex < distances.length; pointIndex += 1) {
    const base = pointIndex * 3;
    distances[pointIndex] = measurePoint(points[base], points[base + 1], points[base + 2]);
    if (scales) pieceRelative[pointIndex] = distances[pointIndex] / scales[owners[pointIndex]];
    if (colourDifference > COLOUR_CHANGE) colourChanged += 1;
  }
  // Per piece: a share of the surface hides a ruined painting or shield, which is 1 % of a kitchen. Every piece gets
  // PIECE_SAMPLES points of its own; a piece is broken when PIECE_BROKEN_SAMPLES of them moved more than
  // PIECE_SHAPE_CHANGE of the piece's size or changed colour. pieces_broken is the % of pieces broken.
  let piecesBroken = 0;
  if (pieces) {
    const piecePoints = samplePieces(referenceTriangles, pieces, PIECE_SAMPLES);
    for (let piece = 0; piece < pieces.pieceCount; piece += 1) {
      let damaged = 0;
      for (let sample = 0; sample < PIECE_SAMPLES; sample += 1) {
        const base = (piece * PIECE_SAMPLES + sample) * 4;
        const distance = measurePoint(piecePoints[base], piecePoints[base + 1], piecePoints[base + 2]);
        const shapeChanged = distance / scales[piecePoints[base + 3]] > PIECE_SHAPE_CHANGE;
        if (shapeChanged || colourDifference > COLOUR_CHANGE) damaged += 1;
      }
      if (damaged >= PIECE_BROKEN_SAMPLES) piecesBroken += 1;
    }
  }
  distances.sort();
  const toPercent = (value) => Number(((value / diagonal) * 100).toFixed(4));
  const result = {
    max: toPercent(distances[distances.length - 1]),
    p95: toPercent(distances[Math.floor(distances.length * 0.95)]),
  };
  if (referenceColours && candidateColours) result.colour_changed = Number(((colourChanged / distances.length) * 100).toFixed(3));
  if (pieces) result.pieces_broken = Number(((piecesBroken / pieces.pieceCount) * 100).toFixed(3));
  if (scales) {
    // Distance in % of the sampled point's own piece: p95 says how much of the surface lost its shape locally.
    pieceRelative.sort();
    result.piece_p95 = Number((pieceRelative[Math.floor(pieceRelative.length * 0.95)] * 100).toFixed(3));
    result.piece_p99 = Number((pieceRelative[Math.floor(pieceRelative.length * 0.99)] * 100).toFixed(3));
  }
  return result;
}

function referenceDiagonal(triangles) {
  const low = [Infinity, Infinity, Infinity];
  const high = [-Infinity, -Infinity, -Infinity];
  for (let index = 0; index < triangles.length; index += 3) {
    for (let axis = 0; axis < 3; axis += 1) {
      low[axis] = Math.min(low[axis], triangles[index + axis]);
      high[axis] = Math.max(high[axis], triangles[index + axis]);
    }
  }
  return Math.hypot(high[0] - low[0], high[1] - low[1], high[2] - low[2]);
}

// Area-weighted samples from a fixed linear congruential sequence, so a rerun gives the same numbers.
function sampleSurface(triangles, sampleCount) {
  const count = triangles.length / 9;
  const cumulativeArea = new Float64Array(count);
  let total = 0;
  for (let triangle = 0; triangle < count; triangle += 1) {
    total += triangleArea(triangles, triangle * 9);
    cumulativeArea[triangle] = total;
  }
  let state = 12345;
  const random = () => {
    state = (state * 1103515245 + 12345) % 2147483648;
    return state / 2147483648;
  };
  const points = new Float64Array(sampleCount * 3);
  const owners = new Int32Array(sampleCount);
  for (let sample = 0; sample < sampleCount; sample += 1) {
    const target = random() * total;
    let lowIndex = 0;
    let highIndex = count - 1;
    while (lowIndex < highIndex) {
      const middle = (lowIndex + highIndex) >> 1;
      if (cumulativeArea[middle] < target) lowIndex = middle + 1;
      else highIndex = middle;
    }
    let first = random();
    let second = random();
    if (first + second > 1) {
      first = 1 - first;
      second = 1 - second;
    }
    const base = lowIndex * 9;
    owners[sample] = lowIndex;
    for (let axis = 0; axis < 3; axis += 1) {
      const origin = triangles[base + axis];
      const towardSecond = triangles[base + 3 + axis] - origin;
      const towardThird = triangles[base + 6 + axis] - origin;
      points[sample * 3 + axis] = origin + first * towardSecond + second * towardThird;
    }
  }
  return { points, owners };
}

// PIECE_SAMPLES area-weighted points per piece, as x, y, z, owner triangle (4 numbers per point), deterministic.
function samplePieces(triangles, pieces, perPiece) {
  const count = triangles.length / 9;
  const trianglesOfPiece = Array.from({ length: pieces.pieceCount }, () => []);
  for (let triangle = 0; triangle < count; triangle += 1) trianglesOfPiece[pieces.pieceOf[triangle]].push(triangle);
  let state = 54321;
  const random = () => {
    state = (state * 1103515245 + 12345) % 2147483648;
    return state / 2147483648;
  };
  const points = new Float64Array(pieces.pieceCount * perPiece * 4);
  for (let piece = 0; piece < pieces.pieceCount; piece += 1) {
    const members = trianglesOfPiece[piece];
    const cumulative = new Float64Array(members.length);
    let total = 0;
    for (let index = 0; index < members.length; index += 1) {
      total += triangleArea(triangles, members[index] * 9);
      cumulative[index] = total;
    }
    for (let sample = 0; sample < perPiece; sample += 1) {
      const target = random() * total;
      let chosen = 0;
      while (chosen < members.length - 1 && cumulative[chosen] < target) chosen += 1;
      let first = random();
      let second = random();
      if (first + second > 1) {
        first = 1 - first;
        second = 1 - second;
      }
      const base = members[chosen] * 9;
      const out = (piece * perPiece + sample) * 4;
      for (let axis = 0; axis < 3; axis += 1) {
        const origin = triangles[base + axis];
        points[out + axis] = origin + first * (triangles[base + 3 + axis] - origin) + second * (triangles[base + 6 + axis] - origin);
      }
      points[out + 3] = members[chosen];
    }
  }
  return points;
}

function triangleArea(triangles, base) {
  const edgeOne = [triangles[base + 3] - triangles[base], triangles[base + 4] - triangles[base + 1], triangles[base + 5] - triangles[base + 2]];
  const edgeTwo = [triangles[base + 6] - triangles[base], triangles[base + 7] - triangles[base + 1], triangles[base + 8] - triangles[base + 2]];
  return 0.5 * Math.hypot(
    edgeOne[1] * edgeTwo[2] - edgeOne[2] * edgeTwo[1],
    edgeOne[2] * edgeTwo[0] - edgeOne[0] * edgeTwo[2],
    edgeOne[0] * edgeTwo[1] - edgeOne[1] * edgeTwo[0],
  );
}

// Uniform grid over both meshes' bounds; each candidate triangle is listed in every cell its bounding box touches.
function buildTriangleGrid(triangles, low, high) {
  const count = triangles.length / 9;
  const cellsPerAxis = Math.max(1, Math.min(48, Math.round(Math.cbrt(count) * 1.2)));
  const cellSize = [0, 1, 2].map((axis) => Math.max(high[axis] - low[axis], 1e-9) / cellsPerAxis);
  const cells = new Map();
  const cellOf = (value, axis) => Math.min(cellsPerAxis - 1, Math.max(0, Math.floor((value - low[axis]) / cellSize[axis])));
  for (let triangle = 0; triangle < count; triangle += 1) {
    const base = triangle * 9;
    const from = [0, 1, 2].map((axis) => cellOf(Math.min(triangles[base + axis], triangles[base + 3 + axis], triangles[base + 6 + axis]), axis));
    const to = [0, 1, 2].map((axis) => cellOf(Math.max(triangles[base + axis], triangles[base + 3 + axis], triangles[base + 6 + axis]), axis));
    for (let cellX = from[0]; cellX <= to[0]; cellX += 1) {
      for (let cellY = from[1]; cellY <= to[1]; cellY += 1) {
        for (let cellZ = from[2]; cellZ <= to[2]; cellZ += 1) {
          const key = (cellX * cellsPerAxis + cellY) * cellsPerAxis + cellZ;
          let list = cells.get(key);
          if (!list) {
            list = [];
            cells.set(key, list);
          }
          list.push(triangle);
        }
      }
    }
  }
  return { cells, cellsPerAxis, cellOf, smallestCell: Math.min(...cellSize), visitMark: new Int32Array(count), visitStamp: 0, near: [], keepNear: false, tieDistance: 0 };
}

// Searches shells of cells outward from the point's cell until the best distance found is closer than any
// triangle in the next shell can be.
function nearestDistance(grid, triangles, x, y, z) {
  const centre = [grid.cellOf(x, 0), grid.cellOf(y, 1), grid.cellOf(z, 2)];
  const size = grid.cellsPerAxis;
  grid.visitStamp += 1;
  const stamp = grid.visitStamp;
  grid.near.length = 0;
  let best = Infinity;
  for (let ring = 0; ring < size; ring += 1) {
    for (let cellX = Math.max(0, centre[0] - ring); cellX <= Math.min(size - 1, centre[0] + ring); cellX += 1) {
      for (let cellY = Math.max(0, centre[1] - ring); cellY <= Math.min(size - 1, centre[1] + ring); cellY += 1) {
        for (let cellZ = Math.max(0, centre[2] - ring); cellZ <= Math.min(size - 1, centre[2] + ring); cellZ += 1) {
          const shellDistance = Math.max(Math.abs(cellX - centre[0]), Math.abs(cellY - centre[1]), Math.abs(cellZ - centre[2]));
          if (shellDistance !== ring) continue;
          const list = grid.cells.get((cellX * size + cellY) * size + cellZ);
          if (!list) continue;
          for (const triangle of list) {
            if (grid.visitMark[triangle] === stamp) continue;
            grid.visitMark[triangle] = stamp;
            const distance = pointTriangleDistance(triangles, triangle * 9, x, y, z);
            if (distance < best) best = distance;
            if (grid.keepNear && distance <= best * 1.5 + grid.tieDistance) {
              grid.near.push(triangle, distance, closestPoint[0], closestPoint[1], closestPoint[2]);
            }
          }
        }
      }
    }
    // Every triangle not yet seen lies outside shells 0..ring, so at least ring cells away.
    if (best <= ring * grid.smallestCell) break;
  }
  return best;
}

// Closest point of the last pointTriangleDistance call, read by nearestDistance for the colour lookup.
const closestPoint = new Float64Array(3);

// Closest point on a triangle (Ericson, Real-Time Collision Detection, section 5.1.5).
function pointTriangleDistance(triangles, base, x, y, z) {
  const ax = triangles[base];
  const ay = triangles[base + 1];
  const az = triangles[base + 2];
  const abx = triangles[base + 3] - ax;
  const aby = triangles[base + 4] - ay;
  const abz = triangles[base + 5] - az;
  const acx = triangles[base + 6] - ax;
  const acy = triangles[base + 7] - ay;
  const acz = triangles[base + 8] - az;
  const distanceTo = (px, py, pz) => {
    closestPoint[0] = px;
    closestPoint[1] = py;
    closestPoint[2] = pz;
    return Math.hypot(x - px, y - py, z - pz);
  };
  const apx = x - ax;
  const apy = y - ay;
  const apz = z - az;
  const d1 = abx * apx + aby * apy + abz * apz;
  const d2 = acx * apx + acy * apy + acz * apz;
  if (d1 <= 0 && d2 <= 0) return distanceTo(ax, ay, az);
  const bpx = apx - abx;
  const bpy = apy - aby;
  const bpz = apz - abz;
  const d3 = abx * bpx + aby * bpy + abz * bpz;
  const d4 = acx * bpx + acy * bpy + acz * bpz;
  if (d3 >= 0 && d4 <= d3) return distanceTo(ax + abx, ay + aby, az + abz);
  const vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) {
    const along = d1 / (d1 - d3);
    return distanceTo(ax + along * abx, ay + along * aby, az + along * abz);
  }
  const cpx = apx - acx;
  const cpy = apy - acy;
  const cpz = apz - acz;
  const d5 = abx * cpx + aby * cpy + abz * cpz;
  const d6 = acx * cpx + acy * cpy + acz * cpz;
  if (d6 >= 0 && d5 <= d6) return distanceTo(ax + acx, ay + acy, az + acz);
  const vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) {
    const along = d2 / (d2 - d6);
    return distanceTo(ax + along * acx, ay + along * acy, az + along * acz);
  }
  const va = d3 * d6 - d5 * d4;
  if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) {
    const along = (d4 - d3) / (d4 - d3 + (d5 - d6));
    const bx = ax + abx;
    const by = ay + aby;
    const bz = az + abz;
    return distanceTo(bx + along * (acx - abx), by + along * (acy - aby), bz + along * (acz - abz));
  }
  const denominator = 1 / (va + vb + vc);
  const v = vb * denominator;
  const w = vc * denominator;
  return distanceTo(ax + abx * v + acx * w, ay + aby * v + acy * w, az + abz * v + acz * w);
}
