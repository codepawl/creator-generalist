// glTF side of mesh_prep: inspect, clean, simplify, LOD, compress, decode and validate with glTF Transform,
// meshoptimizer and the Khronos glTF-Validator. mesh_prep.py installs the packages into a cache folder and passes it
// as MESH_PREP_NODE_DEPS; every command prints one JSON object on stdout.
//
//   node mesh_gltf.mjs inspect  <in>
//   node mesh_gltf.mjs clean    <in> <out>                         dedup, weld, drop degenerate and duplicate triangles
//   node mesh_gltf.mjs simplify <in> <out> <ratio> <error>         meshopt simplify, attributes kept
//   node mesh_gltf.mjs compress <in> <out> <keep|webp|ktx2> <max_edge> [toktx]
//   node mesh_gltf.mjs plain    <in> <out>                         one plain GLB: .gltf packed, meshopt and quantization decoded
//   node mesh_gltf.mjs validate <in>
//   node mesh_gltf.mjs uv-export <in> <folder>                     raw positions and indices of primitives without UVs
//   node mesh_gltf.mjs uv-apply  <in> <folder> <out>               write xatlas results back, every attribute remapped
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { createMeshSimplifier } from './mesh_simplify.mjs';

const dependencyFolder = process.env.MESH_PREP_NODE_DEPS;
if (!dependencyFolder) throw new Error('MESH_PREP_NODE_DEPS is not set; run this through mesh_prep.py');
const requireFromDependencies = createRequire(path.join(dependencyFolder, 'package.json'));

async function importDependency(name) {
  return import(pathToFileURL(requireFromDependencies.resolve(name)).href);
}

const { NodeIO, Logger } = await importDependency('@gltf-transform/core');
const { ALL_EXTENSIONS, KHRTextureBasisu, EXTMeshoptCompression, KHRMeshQuantization } = await importDependency('@gltf-transform/extensions');
const functions = await importDependency('@gltf-transform/functions');
const { MeshoptDecoder, MeshoptEncoder, MeshoptSimplifier } = await importDependency('meshoptimizer');

await Promise.all([MeshoptDecoder.ready, MeshoptEncoder.ready, MeshoptSimplifier.ready]);
const io = new NodeIO()
  .registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({ 'meshopt.decoder': MeshoptDecoder, 'meshopt.encoder': MeshoptEncoder });
io.setLogger(new Logger(Logger.Verbosity.ERROR));
const {
  triangleCount,
  boundsDiagonal,
  floatArray,
  removeEmptyPrimitives,
  dropBadTriangles,
  simplifyLadder,
} = createMeshSimplifier({ MeshoptSimplifier, functions });

const TRIANGLES_MODE = 4;
// 14 bits (the glTF Transform default) collapsed a sliver on a Poly Haven jerrycan; 16 costs a few percent of size.
const POSITION_BITS = 16;
const COLOUR_SLOTS = new Set(['baseColorTexture', 'emissiveTexture']);
// Same encodings as the CodePawl dataset packs: ETC1S for colour and data maps, UASTC with RDO for normal maps.
const KTX2_ENCODINGS = {
  colour: ['--encode', 'etc1s', '--clevel', '0', '--qlevel', '128', '--assign_oetf', 'srgb', '--assign_primaries', 'bt709'],
  data: ['--encode', 'etc1s', '--clevel', '0', '--qlevel', '128', '--assign_oetf', 'linear', '--assign_primaries', 'none'],
  normal: ['--encode', 'uastc', '--uastc_quality', '1', '--uastc_rdo_l', '2', '--zcmp', '18', '--assign_oetf', 'linear', '--assign_primaries', 'none'],
};

function print(result) {
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

function describe(document) {
  const root = document.getRoot();
  const primitives = root.listMeshes().flatMap((mesh) => mesh.listPrimitives());
  let vertices = 0;
  for (const primitive of primitives) vertices += primitive.getAttribute('POSITION')?.getCount() ?? 0;
  const textures = root.listTextures().map((texture) => {
    const size = texture.getSize();
    return { mime: texture.getMimeType(), width: size?.[0] ?? null, height: size?.[1] ?? null, bytes: texture.getImage()?.byteLength ?? 0 };
  });
  return {
    triangles: triangleCount(document),
    vertices,
    meshes: root.listMeshes().length,
    primitives: primitives.length,
    non_triangle_primitives: primitives.filter((primitive) => primitive.getMode() !== TRIANGLES_MODE).length,
    primitives_without_uv: primitives.filter((primitive) => !primitive.getAttribute('TEXCOORD_0')).length,
    primitives_without_normals: primitives.filter((primitive) => !primitive.getAttribute('NORMAL')).length,
    skins: root.listSkins().length,
    morph_targets: primitives.reduce((sum, primitive) => sum + primitive.listTargets().length, 0),
    animations: root.listAnimations().length,
    materials: root.listMaterials().length,
    textures,
    extensions: root.listExtensionsUsed().map((extension) => extension.extensionName),
  };
}

async function writeDocument(document, outputPath) {
  await removeEmptyPrimitives(document);
  fs.mkdirSync(path.dirname(path.resolve(outputPath)), { recursive: true });
  await io.write(outputPath, document);
  return { bytes: fs.statSync(outputPath).size, ...describe(document) };
}

function textureKind(document, texture) {
  const slots = document.getGraph().listParentEdges(texture).map((edge) => edge.getName());
  if (slots.some((slot) => COLOUR_SLOTS.has(slot))) return 'colour';
  if (slots.includes('normalTexture')) return 'normal';
  return 'data';
}

function multipleOfFour(edge) {
  return Math.max(4, Math.round(edge / 4) * 4);
}

async function swapTexturesToKtx2(document, maxEdge, toktxPath) {
  const sharp = (await importDependency('sharp')).default;
  const temporaryFolder = fs.mkdtempSync(path.join(os.tmpdir(), 'mesh-prep-ktx-'));
  const textures = document.getRoot().listTextures();
  for (const [index, texture] of textures.entries()) {
    const kind = textureKind(document, texture);
    const edgeLimit = kind === 'normal' ? Math.min(maxEdge, 1024) : maxEdge;
    const image = sharp(Buffer.from(texture.getImage()));
    const { width, height } = await image.metadata();
    const scale = Math.min(1, edgeLimit / Math.max(width, height));
    const { isOpaque } = await image.stats();
    let resized = image.resize(multipleOfFour(width * scale), multipleOfFour(height * scale), { fit: 'fill' });
    if (isOpaque) resized = resized.removeAlpha();
    const pngPath = path.join(temporaryFolder, `${index}.png`);
    const ktxPath = path.join(temporaryFolder, `${index}.ktx2`);
    await resized.png().toFile(pngPath);
    execFileSync(toktxPath, ['--t2', ...KTX2_ENCODINGS[kind], '--threads', '2', '--genmipmap', ktxPath, pngPath], { windowsHide: true });
    texture.setImage(fs.readFileSync(ktxPath)).setMimeType('image/ktx2');
  }
  for (const extension of document.getRoot().listExtensionsUsed()) {
    if (extension.extensionName === 'EXT_texture_webp') extension.dispose();
  }
  if (textures.length > 0) document.createExtension(KHRTextureBasisu).setRequired(true);
  fs.rmSync(temporaryFolder, { recursive: true, force: true });
}

async function validate(inputPath) {
  const validator = await importDependency('gltf-validator');
  const bytes = new Uint8Array(fs.readFileSync(inputPath));
  const folder = path.dirname(path.resolve(inputPath));
  const report = await validator.validateBytes(bytes, {
    uri: path.basename(inputPath),
    maxIssues: 200,
    externalResourceFunction: (uri) => Promise.resolve(new Uint8Array(fs.readFileSync(path.join(folder, decodeURIComponent(uri))))),
  });
  const messages = report.issues.messages
    .filter((message) => message.severity <= 1)
    .slice(0, 12)
    .map((message) => `${message.severity === 0 ? 'error' : 'warning'} ${message.code}: ${message.message} ${message.pointer ?? ''}`.trim());
  return {
    errors: report.issues.numErrors,
    warnings: report.issues.numWarnings,
    infos: report.issues.numInfos,
    messages,
  };
}

const [command, ...rest] = process.argv.slice(2);

if (command === 'inspect') {
  const document = await io.read(rest[0]);
  print({ ...describe(document), diagonal: boundsDiagonal(document) });
} else if (command === 'clean') {
  const document = await io.read(rest[0]);
  const before = triangleCount(document);
  await document.transform(functions.dedup(), functions.weld());
  const dropped = dropBadTriangles(document);
  await document.transform(functions.prune({ keepLeaves: true, keepExtras: true }));
  print({ triangles_before: before, dropped, ...(await writeDocument(document, rest[1])) });
} else if (command === 'simplify') {
  const [inputPath, outputPath, ratioText, errorText, purpose = 'geometry', maxDeviationText] = rest;
  const ratio = Number(ratioText);
  const error = Number(errorText);
  // The pass ladder and its reasons live in mesh_simplify.mjs, shared with the dataset pack pipeline.
  // maxDeviation (% of the diagonal): the error is lowered until the result stays that close to the source.
  const maxDeviation = maxDeviationText ? Number(maxDeviationText) : null;
  const result = await simplifyLadder(await io.read(inputPath), { ratio, error, purpose, maxDeviation });
  const written = await writeDocument(result.document, outputPath);
  print({
    triangles_before: result.trianglesBefore,
    ratio,
    error,
    mode: result.mode,
    dropped: result.dropped,
    simplify_error: Number(result.simplifyError.toFixed(5)),
    error_used: result.errorUsed,
    deviation: result.deviation,
    within_budget: result.withinBudget,
    achieved_ratio: Number((written.triangles / result.trianglesBefore).toFixed(4)),
    ...written,
  });
} else if (command === 'compress') {
  const [inputPath, outputPath, textureMode, maxEdgeText, toktxPath] = rest;
  const maxEdge = Number(maxEdgeText);
  const document = await io.read(inputPath);
  if (textureMode === 'webp') {
    const sharp = (await importDependency('sharp')).default;
    await document.transform(functions.textureCompress({ encoder: sharp, targetFormat: 'webp', resize: [maxEdge, maxEdge] }));
  } else if (textureMode === 'ktx2') {
    if (!toktxPath || !fs.existsSync(toktxPath)) throw new Error('KTX2 needs the toktx executable from KTX-Software; set MESH_PREP_TOKTX');
    await swapTexturesToKtx2(document, maxEdge, toktxPath);
  }
  const dropped = dropBadTriangles(document, POSITION_BITS);
  await document.transform(functions.meshopt({ encoder: MeshoptEncoder, level: 'medium', quantizePosition: POSITION_BITS }));
  print({ textures: textureMode, dropped, ...(await writeDocument(document, outputPath)) });
} else if (command === 'plain') {
  const document = await io.read(rest[0]);
  await document.transform(functions.dequantize());
  for (const extension of document.getRoot().listExtensionsUsed()) {
    const name = extension.extensionName;
    if (name === EXTMeshoptCompression.EXTENSION_NAME || name === KHRMeshQuantization.EXTENSION_NAME) extension.dispose();
  }
  const ktx2Textures = document.getRoot().listTextures().filter((texture) => texture.getMimeType() === 'image/ktx2').length;
  print({ ktx2_textures_not_viewable: ktx2Textures, ...(await writeDocument(document, rest[1])) });
} else if (command === 'uv-export') {
  const [inputPath, folder] = rest;
  const document = await io.read(inputPath);
  fs.mkdirSync(folder, { recursive: true });
  const entries = [];
  document.getRoot().listMeshes().forEach((mesh, meshIndex) => {
    mesh.listPrimitives().forEach((primitive, primitiveIndex) => {
      if (primitive.getMode() !== TRIANGLES_MODE || primitive.getAttribute('TEXCOORD_0') || !primitive.getIndices()) return;
      const name = `m${meshIndex}_p${primitiveIndex}`;
      const position = primitive.getAttribute('POSITION');
      fs.writeFileSync(path.join(folder, `${name}_positions.f32`), Buffer.from(floatArray(position).buffer));
      fs.writeFileSync(path.join(folder, `${name}_indices.u32`), Buffer.from(Uint32Array.from(primitive.getIndices().getArray()).buffer));
      entries.push({ name, mesh: meshIndex, primitive: primitiveIndex, vertices: position.getCount() });
    });
  });
  fs.writeFileSync(path.join(folder, 'manifest.json'), JSON.stringify(entries));
  print({ primitives_without_uv: entries.length });
} else if (command === 'uv-apply') {
  const [inputPath, folder, outputPath] = rest;
  const document = await io.read(inputPath);
  const entries = JSON.parse(fs.readFileSync(path.join(folder, 'manifest.json'), 'utf8'));
  const meshes = document.getRoot().listMeshes();
  for (const entry of entries) {
    const primitive = meshes[entry.mesh].listPrimitives()[entry.primitive];
    const readBinary = (suffix, ArrayType) => {
      const bytes = fs.readFileSync(path.join(folder, `${entry.name}_${suffix}`));
      return new ArrayType(bytes.buffer, bytes.byteOffset, bytes.byteLength / ArrayType.BYTES_PER_ELEMENT);
    };
    const vertexMapping = readBinary('vmapping.u32', Uint32Array);
    const newIndices = readBinary('new_indices.u32', Uint32Array);
    const uvs = readBinary('uvs.f32', Float32Array);
    const remap = (accessor) => {
      const size = accessor.getElementSize();
      const ArrayType = accessor.getArray().constructor;
      const remapped = new ArrayType(vertexMapping.length * size);
      const element = new Array(size);
      vertexMapping.forEach((sourceIndex, targetIndex) => {
        accessor.getElement(sourceIndex, element);
        for (let component = 0; component < size; component += 1) remapped[targetIndex * size + component] = element[component];
      });
      return document.createAccessor().setType(accessor.getType()).setArray(remapped).setNormalized(accessor.getNormalized()).setBuffer(accessor.getBuffer());
    };
    for (const semantic of primitive.listSemantics()) primitive.setAttribute(semantic, remap(primitive.getAttribute(semantic)));
    for (const target of primitive.listTargets()) {
      for (const semantic of target.listSemantics()) target.setAttribute(semantic, remap(target.getAttribute(semantic)));
    }
    const buffer = primitive.getAttribute('POSITION').getBuffer();
    primitive.setIndices(document.createAccessor().setType('SCALAR').setArray(newIndices).setBuffer(buffer));
    primitive.setAttribute('TEXCOORD_0', document.createAccessor().setType('VEC2').setArray(uvs).setBuffer(buffer));
  }
  await document.transform(functions.prune({ keepLeaves: true, keepExtras: true }));
  print({ primitives_unwrapped: entries.length, ...(await writeDocument(document, outputPath)) });
} else if (command === 'validate') {
  print(await validate(rest[0]));
} else {
  console.error(fs.readFileSync(new URL(import.meta.url), 'utf8').split('\nimport ')[0]);
  process.exit(2);
}
