// Shared simplify ladder for glTF Transform documents. No side effects on import: the caller passes its own
// meshoptimizer and @gltf-transform/functions, so mesh_gltf.mjs (mesh_prep) and the dataset pack pipeline run the
// same code with their own installed packages.
//
//   import { createMeshSimplifier } from './mesh_simplify.mjs';
//   const simplifier = createMeshSimplifier({ MeshoptSimplifier, functions });
//   await MeshoptSimplifier.ready;
//   const result = await simplifier.simplifyLadder(document, { ratio: 0.2, error: 0.03, maxDeviation: 1.5 });
//   // result.document is a simplified copy; result.mode names the pass, result.reached says if 1.25x the share was met,
//   // result.deviation is {max, p95} in % of the diagonal and result.withinBudget says if max fit maxDeviation.

import { surfaceDeviation, pieceIndex } from './mesh_deviation.mjs';

const TRIANGLES_MODE = 4;
// Error divisors simplifyLadder tries when a deviation budget is set.
const ERROR_STEPS = [1, 2, 4, 8, 16, 64];
// Passes that keep UV and vertex-colour seams, tried by simplifyLadder when the open pass breaks the budget.
const SEAM_SAFE_PASSES = ['seam-preserving', 'permissive, UV and colour seams protected'];
const PROTECT_VERTEX = 2; // meshopt_SimplifyVertex_Protect
// UV and normal weights on every pass: a position-only simplify slid vertices across a flat, normal-mapped lamp
// panel, which warped its UVs and turned the shading 38 degrees while colour and silhouette still matched.
// Vertex colours get the same weight as UVs so palette-coloured low-poly sets keep their colour borders.
const ATTRIBUTE_WEIGHTS = [['NORMAL', 0.5], ['TEXCOORD_0', 1.0], ['COLOR_0', 1.0]];
const TARGET_TOLERANCE = 1.25;

// Fragmented UV atlases (scans) and flat-shaded meshes stop the seam-preserving pass far above the target (a scan
// boulder stayed at 82% for 50, 20 and 6% targets), so Permissive mode collapses across seams, with UV-seam vertices
// protected (the meshoptimizer README's advice) or with every seam open. PreserveFolds keeps thin two-sided parts
// from collapsing. meshopt Prune is off by default: it deleted 8 of 11 whole objects (each over 3% of the diagonal)
// from a low-poly room at a 20% LOD, and every tested mesh reached its share without it. prune: true turns it on.
const PASSES = [
  { name: 'seam-preserving', flags: ['PreserveFolds'], protectUvSeams: false },
  { name: 'permissive, UV and colour seams protected', flags: ['Permissive', 'PreserveFolds'], protectUvSeams: true },
  { name: 'permissive', flags: ['Permissive', 'PreserveFolds'], protectUvSeams: false },
];

export function createMeshSimplifier({ MeshoptSimplifier, functions }) {
  function listPrimitives(document) {
    return document.getRoot().listMeshes().flatMap((mesh) => mesh.listPrimitives());
  }

  function triangleCount(document) {
    let triangles = 0;
    for (const primitive of listPrimitives(document)) {
      if (primitive.getMode() !== TRIANGLES_MODE) continue;
      const count = primitive.getIndices()?.getCount() ?? primitive.getAttribute('POSITION').getCount();
      triangles += count / 3;
    }
    return triangles;
  }

  function boundsDiagonal(document) {
    const scene = document.getRoot().getDefaultScene() ?? document.getRoot().listScenes()[0];
    const { min, max } = functions.getBounds(scene);
    return Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]);
  }

  // Simplify can remove every triangle of a small part (Prune makes it common). An empty primitive is legal glTF but leaves
  // zero-length buffer views that trimesh refuses to read and zero-count accessors the validator rejects (a 5% LOD
  // of a floodlight had four).
  async function removeEmptyPrimitives(document) {
    let removed = 0;
    for (const mesh of document.getRoot().listMeshes()) {
      for (const primitive of mesh.listPrimitives()) {
        const indices = primitive.getIndices();
        const count = indices ? indices.getCount() : primitive.getAttribute('POSITION')?.getCount() ?? 0;
        if (count === 0) {
          primitive.dispose();
          removed += 1;
        }
      }
      // A mesh needs at least one primitive; its nodes stay (they may be sockets or parents).
      if (mesh.listPrimitives().length === 0) mesh.dispose();
    }
    for (const accessor of document.getRoot().listAccessors()) {
      if (accessor.getCount() === 0) accessor.dispose();
    }
    if (removed) await document.transform(functions.prune({ keepLeaves: true, keepExtras: true }));
    return removed;
  }

  function meshBounds(mesh) {
    const low = [Infinity, Infinity, Infinity];
    const high = [-Infinity, -Infinity, -Infinity];
    for (const primitive of mesh.listPrimitives()) {
      const position = primitive.getAttribute('POSITION');
      if (!position) continue;
      const primitiveLow = position.getMin([]);
      const primitiveHigh = position.getMax([]);
      for (let axis = 0; axis < 3; axis += 1) {
        low[axis] = Math.min(low[axis], primitiveLow[axis]);
        high[axis] = Math.max(high[axis], primitiveHigh[axis]);
      }
    }
    return { low, high };
  }

  // Rotates the corner keys so the smallest comes first: the same face from any start corner gets one key, while
  // the reversed face (a two-sided card's back) gets another.
  function orientedKey(cornerKeys) {
    const start = cornerKeys.indexOf([...cornerKeys].sort()[0]);
    return [0, 1, 2].map((step) => cornerKeys[(start + step) % 3]).join('|');
  }

  // A fold is a face and its reversed twin on the same three positions. Simplify made 15 on a 20% scan LOD, each one
  // a non-manifold edge; an authored two-sided card looks the same, so folds are removed only when the input had none.
  function foldOffsets(primitive) {
    const indices = primitive.getIndices();
    const position = primitive.getAttribute('POSITION');
    const offsets = new Set();
    if (primitive.getMode() !== TRIANGLES_MODE || !indices || !position) return offsets;
    const source = indices.getArray();
    const offsetByKey = new Map();
    const corner = [0, 0, 0];
    for (let offset = 0; offset < source.length; offset += 3) {
      const cornerKeys = [0, 1, 2].map((step) => {
        position.getElement(source[offset + step], corner);
        return corner.join(',');
      });
      const key = orientedKey(cornerKeys);
      const reversedKey = orientedKey([cornerKeys[0], cornerKeys[2], cornerKeys[1]]);
      if (offsetByKey.has(reversedKey)) {
        offsets.add(offset);
        offsets.add(offsetByKey.get(reversedKey));
      }
      offsetByKey.set(key, offset);
    }
    return offsets;
  }

  function countFolds(document) {
    return listPrimitives(document).reduce((sum, primitive) => sum + foldOffsets(primitive).size / 2, 0);
  }

  function removeFolds(document) {
    let removed = 0;
    for (const primitive of listPrimitives(document)) {
      const offsets = foldOffsets(primitive);
      if (!offsets.size) continue;
      const source = primitive.getIndices().getArray();
      const kept = [];
      for (let offset = 0; offset < source.length; offset += 3) {
        if (!offsets.has(offset)) kept.push(source[offset], source[offset + 1], source[offset + 2]);
      }
      primitive.getIndices().setArray(new source.constructor(kept));
      removed += offsets.size;
    }
    return removed;
  }

  // Drops triangles that repeat an index, have no area, or repeat another triangle of the same primitive.
  // Works on index buffers only, so UVs, normals, skin weights and materials stay untouched.
  // With quantizeBits, also drops slivers whose corners land on the same cell of the mesh-bounds grid that meshopt
  // quantization will snap them to (they would turn into zero-area triangles in the compressed file).
  function dropBadTriangles(document, quantizeBits = 0) {
    const diagonal = boundsDiagonal(document) || 1;
    const minimumDoubleArea = (diagonal * 1e-7) ** 2;
    const counts = { repeated_index: 0, zero_area: 0, duplicate: 0, quantization_collapse: 0 };
    const corner = [0, 0, 0];
    for (const mesh of document.getRoot().listMeshes()) {
      const { low, high } = meshBounds(mesh);
      const steps = 2 ** quantizeBits - 1;
      const extent = Math.max(high[0] - low[0], high[1] - low[1], high[2] - low[2]) || 1;
      const snapped = (position, vertex) => {
        position.getElement(vertex, corner);
        return corner.map((value, axis) => Math.round(((value - low[axis]) / extent) * steps));
      };
      const collapsesOnGrid = (position, first, second, third) => {
        const pointOne = snapped(position, first);
        const pointTwo = snapped(position, second);
        const pointThree = snapped(position, third);
        const edgeOne = pointTwo.map((value, axis) => value - pointOne[axis]);
        const edgeTwo = pointThree.map((value, axis) => value - pointOne[axis]);
        return edgeOne[1] * edgeTwo[2] - edgeOne[2] * edgeTwo[1] === 0
          && edgeOne[2] * edgeTwo[0] - edgeOne[0] * edgeTwo[2] === 0
          && edgeOne[0] * edgeTwo[1] - edgeOne[1] * edgeTwo[0] === 0;
      };
      for (const primitive of mesh.listPrimitives()) {
        if (primitive.getMode() !== TRIANGLES_MODE) continue;
        const indices = primitive.getIndices();
        const position = primitive.getAttribute('POSITION');
        if (!indices || !position) continue;
        const source = indices.getArray();
        const kept = [];
        const seen = new Set();
        const cornerOne = [0, 0, 0];
        const cornerTwo = [0, 0, 0];
        const cornerThree = [0, 0, 0];
        for (let offset = 0; offset < source.length; offset += 3) {
          const first = source[offset];
          const second = source[offset + 1];
          const third = source[offset + 2];
          if (first === second || second === third || first === third) {
            counts.repeated_index += 1;
            continue;
          }
          position.getElement(first, cornerOne);
          position.getElement(second, cornerTwo);
          position.getElement(third, cornerThree);
          const edgeOne = [cornerTwo[0] - cornerOne[0], cornerTwo[1] - cornerOne[1], cornerTwo[2] - cornerOne[2]];
          const edgeTwo = [cornerThree[0] - cornerOne[0], cornerThree[1] - cornerOne[1], cornerThree[2] - cornerOne[2]];
          const cross = [
            edgeOne[1] * edgeTwo[2] - edgeOne[2] * edgeTwo[1],
            edgeOne[2] * edgeTwo[0] - edgeOne[0] * edgeTwo[2],
            edgeOne[0] * edgeTwo[1] - edgeOne[1] * edgeTwo[0],
          ];
          if (Math.hypot(cross[0], cross[1], cross[2]) <= minimumDoubleArea) {
            counts.zero_area += 1;
            continue;
          }
          if (quantizeBits && collapsesOnGrid(position, first, second, third)) {
            counts.quantization_collapse += 1;
            continue;
          }
          // Keyed by position, not index: simplify can leave a copy of a face whose vertices sit on the other side
          // of a UV seam (15 on a 20% scan LOD, each one a non-manifold edge).
          const key = orientedKey([cornerOne.join(','), cornerTwo.join(','), cornerThree.join(',')]);
          if (seen.has(key)) {
            counts.duplicate += 1;
            continue;
          }
          seen.add(key);
          kept.push(first, second, third);
        }
        if (kept.length !== source.length) indices.setArray(new source.constructor(kept));
      }
    }
    return counts;
  }

  // getElement denormalizes normalized accessors (quantized UVs, ushort colours), so the weights see real values.
  function floatArray(accessor) {
    const array = accessor.getArray();
    if (array instanceof Float32Array && !accessor.getNormalized()) return array;
    const count = accessor.getCount();
    const size = accessor.getElementSize();
    const result = new Float32Array(count * size);
    const element = new Array(size);
    for (let index = 0; index < count; index += 1) {
      accessor.getElement(index, element);
      for (let component = 0; component < size; component += 1) result[index * size + component] = element[component];
    }
    return result;
  }

  // Marks vertices that share a position with another vertex but carry a different UV: the two sides of a UV seam.
  // Protects vertices on UV and vertex-colour seams (same position, different value). Colour seams joined the UV
  // ones after Permissive collapses on a vertex-coloured monster kit swapped grey corners for their white twins:
  // 24.6 % of the surface turned from grey to white while only 1.4 % of the triangles went.
  function seamLocks(position, attributes) {
    const locks = new Uint8Array(position.getCount());
    if (!attributes.length) return locks;
    const firstAtPosition = new Map();
    const point = [];
    const values = [];
    const firstValues = [];
    for (let vertex = 0; vertex < position.getCount(); vertex += 1) {
      position.getElement(vertex, point);
      const key = point.join(',');
      const first = firstAtPosition.get(key);
      if (first === undefined) {
        firstAtPosition.set(key, vertex);
        continue;
      }
      for (const attribute of attributes) {
        attribute.getElement(vertex, values);
        attribute.getElement(first, firstValues);
        if (values.some((value, component) => value !== firstValues[component])) {
          locks[vertex] |= PROTECT_VERTEX;
          locks[first] |= PROTECT_VERTEX;
        }
      }
    }
    return locks;
  }

  // One meshopt pass over every triangle primitive; returns the largest relative error meshopt reports.
  function simplifyWeighted(document, ratio, error, flags, protectUvSeams = false) {
    let largestError = 0;
    for (const primitive of listPrimitives(document)) {
      const indices = primitive.getIndices();
      const position = primitive.getAttribute('POSITION');
      if (primitive.getMode() !== TRIANGLES_MODE || !indices || !position) continue;
      const vertexCount = position.getCount();
      const attributeSources = ATTRIBUTE_WEIGHTS
        .map(([name, weight]) => [primitive.getAttribute(name), weight])
        .filter(([accessor]) => accessor)
        .map(([accessor, weight]) => [accessor, accessor.getElementSize(), weight]);
      const stride = attributeSources.reduce((sum, [, size]) => sum + size, 0);
      const attributes = new Float32Array(Math.max(stride, 1) * vertexCount);
      const weights = [];
      let offset = 0;
      for (const [accessor, size, weight] of attributeSources) {
        const values = floatArray(accessor);
        for (let vertex = 0; vertex < vertexCount; vertex += 1) {
          for (let component = 0; component < size; component += 1) attributes[vertex * stride + offset + component] = values[vertex * size + component];
        }
        for (let component = 0; component < size; component += 1) weights.push(weight);
        offset += size;
      }
      const sourceIndices = Uint32Array.from(indices.getArray());
      const targetCount = Math.max(3, Math.floor((sourceIndices.length * ratio) / 3) * 3);
      const seamAttributes = ['TEXCOORD_0', 'COLOR_0'].map((semantic) => primitive.getAttribute(semantic)).filter(Boolean);
      const locks = protectUvSeams ? seamLocks(position, seamAttributes) : null;
      const [result, resultError] = stride === 0
        ? MeshoptSimplifier.simplify(sourceIndices, floatArray(position), 3, targetCount, error, flags)
        : MeshoptSimplifier.simplifyWithAttributes(sourceIndices, floatArray(position), 3, attributes, stride, weights, locks, targetCount, error, flags);
      largestError = Math.max(largestError, resultError);
      indices.setArray(vertexCount > 65535 ? result : Uint16Array.from(result));
      functions.compactPrimitive(primitive);
    }
    return largestError;
  }

  // Runs the passes on copies of the source and keeps one. Seam-preserving wins whenever it reaches the target.
  // Between the permissive passes the seam-protected one wins whenever it reaches the target: open seams folded a
  // scan boulder's UVs into 63% overlap (nothing could be baked) and swapped vertex colours on a monster kit, which
  // costs more than the slightly lower Hausdorff of the open pass (0.49% against 0.71% on that boulder). The open
  // pass is kept only when the protected one cannot reach the share.
  // The error bound is never raised: a pass that cannot reach the share within it simply stops early.
  async function simplifyOnce(source, { ratio, error, purpose = 'geometry', passNames = null, prune = false }) {
    const trianglesBefore = triangleCount(source);
    let chosen = null;
    for (const pass of PASSES.filter((candidatePass) => !passNames || passNames.includes(candidatePass.name))) {
      const candidate = functions.cloneDocument(source);
      await candidate.transform(functions.weld());
      const flags = prune ? [...pass.flags, 'Prune'] : pass.flags;
      const resultError = simplifyWeighted(candidate, ratio, error, flags, pass.protectUvSeams);
      await candidate.transform(functions.prune({ keepLeaves: true, keepExtras: true }));
      const triangles = triangleCount(candidate);
      const reached = triangles <= trianglesBefore * ratio * TARGET_TOLERANCE;
      const better = !chosen
        || (reached && !chosen.reached)
        || (reached === chosen.reached && (reached ? resultError < chosen.resultError : triangles < chosen.triangles));
      if (better) chosen = { document: candidate, mode: pass.name, reached, resultError, triangles };
      if (pass.name === 'seam-preserving' && reached) break;
      if (pass.protectUvSeams && reached) break;
    }
    const { document } = chosen;
    const dropped = dropBadTriangles(document);
    dropped.folds = countFolds(source) === 0 ? removeFolds(document) : 0;
    dropped.empty_primitives = await removeEmptyPrimitives(document);
    const trianglesAfter = triangleCount(document);
    return {
      document,
      mode: chosen.mode,
      reached: chosen.reached,
      simplifyError: chosen.resultError,
      trianglesBefore,
      trianglesAfter,
      share: trianglesBefore ? trianglesAfter / trianglesBefore : 1,
      dropped,
    };
  }

  // World-space triangles of every triangle primitive, as one flat array of 9 numbers per triangle.
  function worldTriangles(document) {
    return worldGeometry(document).triangles;
  }

  // Triangles plus the colour of each corner in the same order (COLOR_0 times the base colour factor, rgb only;
  // textures are not sampled).
  function worldGeometry(document) {
    const values = [];
    const colours = [];
    const corner = [0, 0, 0];
    const colour = [1, 1, 1, 1];
    const scene = document.getRoot().getDefaultScene() ?? document.getRoot().listScenes()[0];
    const nodes = [];
    scene?.traverse((node) => nodes.push(node));
    for (const node of nodes) {
      const mesh = node.getMesh();
      if (!mesh) continue;
      const matrix = node.getWorldMatrix();
      for (const primitive of mesh.listPrimitives()) {
        const position = primitive.getAttribute('POSITION');
        if (primitive.getMode() !== TRIANGLES_MODE || !position) continue;
        const indices = primitive.getIndices();
        const count = indices ? indices.getCount() : position.getCount();
        const colourAttribute = primitive.getAttribute('COLOR_0');
        const factor = primitive.getMaterial()?.getBaseColorFactor() ?? [1, 1, 1, 1];
        for (let offset = 0; offset < count; offset += 1) {
          const vertex = indices ? indices.getScalar(offset) : offset;
          position.getElement(vertex, corner);
          if (colourAttribute) colourAttribute.getElement(vertex, colour);
          else colour.fill(1);
          colours.push(colour[0] * factor[0], colour[1] * factor[1], colour[2] * factor[2]);
          const [x, y, z] = corner;
          values.push(
            matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
            matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
            matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
          );
        }
      }
    }
    return { triangles: Float64Array.from(values), colours: Float64Array.from(colours) };
  }

  // simplifyOnce, gated on the deviation people see. meshoptimizer's error is a local bound, not a bound on how far
  // the result moves from the source: at error 0.08 a Google Poly shed lost its porch roof (13.8 % of the diagonal)
  // and cozy-kitchen its shelf props. With maxDeviation (percent of the diagonal, max distance from points on the
  // source surface to the result) the error is divided by ERROR_STEPS until the result fits; if none fits, the
  // result at the smallest error is kept and withinBudget is false. Without maxDeviation it is simplifyOnce plus
  // the measurement.
  // maxDeviation may also be { max, piece, colour, pieces } (pieces caps pieces_broken, the % of connected pieces
  // whose own samples moved or changed colour): piece caps piece_p95 (distance in % of each point's own
  // connected piece, so a cup is judged against a cup, not the whole tavern) and colour caps colour_changed (% of
  // the surface whose vertex colour moved). Both were added after a 2 % scene budget still turned a tavern's
  // lanterns and bottles into blobs and dropped a painting's colour pattern in a kitchen.
  async function simplifyLadder(source, { maxDeviation = null, ...options }) {
    const budget = typeof maxDeviation === 'number' ? { max: maxDeviation } : maxDeviation;
    const sourceGeometry = worldGeometry(source);
    const pieces = budget?.piece !== undefined || budget?.pieces !== undefined ? pieceIndex(sourceGeometry.triangles) : null;
    const compareColours = budget?.colour !== undefined || budget?.pieces !== undefined;
    const fits = (deviation) => !budget
      || ((budget.max === undefined || deviation.max <= budget.max)
        && (budget.piece === undefined || deviation.piece_p95 <= budget.piece)
        && (budget.colour === undefined || deviation.colour_changed <= budget.colour)
        && (budget.pieces === undefined || deviation.pieces_broken <= budget.pieces));
    let result = null;
    const errors = budget ? ERROR_STEPS.map((divisor) => options.error / divisor) : [options.error];
    const measure = (candidate, error) => {
      const resultGeometry = worldGeometry(candidate.document);
      candidate.deviation = surfaceDeviation(sourceGeometry.triangles, resultGeometry.triangles, 6000, {
        pieces,
        referenceColours: compareColours ? sourceGeometry.colours : null,
        candidateColours: compareColours ? resultGeometry.colours : null,
      });
      candidate.errorUsed = error;
      candidate.withinBudget = fits(candidate.deviation);
      return candidate;
    };
    for (const error of errors) {
      result = measure(await simplifyOnce(source, { ...options, error }), error);
      if (result.withinBudget || !budget) return result;
      // The open permissive pass wins simplifyOnce whenever only it reaches the share, and at any error it may still
      // swap colours across seams (a monster kit stayed at 24 % changed down to error / 64). A seam-safe pass that
      // keeps more triangles but fits the budget is the better level.
      if (result.mode === 'permissive') {
        const seamSafe = measure(await simplifyOnce(source, { ...options, error, passNames: SEAM_SAFE_PASSES }), error);
        if (seamSafe.withinBudget) return seamSafe;
      }
    }
    return result;
  }

  return { triangleCount, boundsDiagonal, floatArray, removeEmptyPrimitives, dropBadTriangles, countFolds, removeFolds, simplifyOnce, simplifyLadder, worldTriangles, worldGeometry };
}
