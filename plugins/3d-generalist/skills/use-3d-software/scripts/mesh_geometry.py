"""Geometry side of mesh_prep: topology, Hausdorff distance, UV metrics, xatlas unwrap, watertight repair and the
render comparison. mesh_prep.py runs each command with `uv run --no-project --with ...` so a run installs only the
packages that command needs. Every command prints one JSON object on stdout.

    mesh_geometry.py topology   <in.glb>
    mesh_geometry.py hausdorff  <reference.glb> <candidate.glb> [samples]
    mesh_geometry.py uv-metrics <in.glb>
    mesh_geometry.py uv-layout  <in.glb> <texture_size> <padding_px>
    mesh_geometry.py uv-unwrap  <folder from mesh_gltf.mjs uv-export>
    mesh_geometry.py watertight <in.glb> <out.glb>
    mesh_geometry.py compare-views <reference_views_dir> <candidate_views_dir> <sheet.png>
"""

import json
import math
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def emit(result):
    print(json.dumps(result))


def load_world_mesh(path):
    """All triangle geometry of a glTF scene, flattened to world space, as one trimesh (no processing)."""
    import trimesh

    scene = trimesh.load(path, force="scene", process=False)
    meshes = []
    for node_name in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node_name]
        geometry = scene.geometry[geometry_name]
        if not isinstance(geometry, trimesh.Trimesh) or len(geometry.faces) == 0:
            continue
        copy = geometry.copy()
        copy.apply_transform(transform)
        meshes.append(copy)
    if not meshes:
        raise SystemExit(f"no triangle geometry in {path}")
    return trimesh.util.concatenate(meshes)


def welded_by_position(mesh):
    import trimesh

    welded = trimesh.Trimesh(vertices=mesh.vertices.copy(), faces=mesh.faces.copy(), process=False)
    welded.merge_vertices(merge_tex=True, merge_norm=True)
    return welded


def count_components(mesh):
    import numpy
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    adjacency = mesh.face_adjacency
    face_count = len(mesh.faces)
    graph = coo_matrix((numpy.ones(len(adjacency)), (adjacency[:, 0], adjacency[:, 1])), shape=(face_count, face_count))
    count, _ = connected_components(graph, directed=False)
    return int(count)


def topology(path):
    import numpy

    mesh = load_world_mesh(path)
    diagonal = float(numpy.linalg.norm(mesh.bounds[1] - mesh.bounds[0]))
    welded = welded_by_position(mesh)
    faces = welded.faces
    repeated_index = int(numpy.sum((faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2]) | (faces[:, 0] == faces[:, 2])))
    zero_area = int(numpy.sum(welded.area_faces <= (diagonal * 1e-7) ** 2 * 0.5))
    sorted_faces = numpy.sort(faces, axis=1)
    unique_faces = numpy.unique(sorted_faces, axis=0)
    edges = numpy.sort(welded.edges, axis=1)
    _, edge_use = numpy.unique(edges, axis=0, return_counts=True)
    result = {
        "triangles": int(len(mesh.faces)),
        "vertices_welded": int(len(welded.vertices)),
        "diagonal": diagonal,
        "degenerate_faces": repeated_index + zero_area,
        "duplicate_faces": int(len(sorted_faces) - len(unique_faces)),
        "boundary_edges": int(numpy.sum(edge_use == 1)),
        "non_manifold_edges": int(numpy.sum(edge_use > 2)),
        "components": count_components(welded),
        "winding_consistent": bool(welded.is_winding_consistent),
        "watertight": bool(welded.is_watertight),
    }
    try:
        import manifold3d

        solid = manifold3d.Manifold(manifold3d.Mesh(vert_properties=welded.vertices.astype("float32"), tri_verts=welded.faces.astype("uint32")))
        result["manifold3d_status"] = str(solid.status()).split(".")[-1]
    except ImportError:
        pass
    emit(result)


def sampled_distances(mesh_set, sampled_index, target_index, samples):
    """Point-to-surface distances from samples on one mesh to the surface of the other (PyMeshLab, exact)."""
    import numpy

    summary = mesh_set.get_hausdorff_distance(
        sampledmesh=sampled_index,
        targetmesh=target_index,
        savesample=True,
        samplevert=False,
        sampleface=True,
        samplenum=samples,
    )
    # savesample adds two meshes: the samples (quality = distance) and their closest points.
    sample_mesh = mesh_set.mesh(mesh_set.mesh_number() - 2)
    distances = numpy.asarray(sample_mesh.vertex_scalar_array(), dtype="float64")
    positions = numpy.asarray(sample_mesh.vertex_matrix(), dtype="float64")
    return summary, distances, positions


def hausdorff(reference_path, candidate_path, samples):
    import numpy
    import pymeshlab

    reference = welded_by_position(load_world_mesh(reference_path))
    candidate = welded_by_position(load_world_mesh(candidate_path))
    diagonal = float(numpy.linalg.norm(reference.bounds[1] - reference.bounds[0]))
    mesh_set = pymeshlab.MeshSet()
    mesh_set.add_mesh(pymeshlab.Mesh(reference.vertices, reference.faces), "reference")
    mesh_set.add_mesh(pymeshlab.Mesh(candidate.vertices, candidate.faces), "candidate")
    forward_summary, forward, forward_positions = sampled_distances(mesh_set, 1, 0, samples)
    backward_summary, backward, backward_positions = sampled_distances(mesh_set, 0, 1, samples)
    both = numpy.concatenate([forward, backward])
    positions = numpy.concatenate([forward_positions, backward_positions])

    def percent(value):
        return round(100.0 * float(value) / diagonal, 4)

    # Where the worst samples sit: of the samples past 75% of the max, the share within 5% of the diagonal of the
    # single worst one. A high share is one region the low cannot follow, such as a crease where the high touches
    # itself (a Tripo body's thighs). A bounding-box spread was thrown off by one stray sample.
    worst = positions[both >= 0.75 * both.max()] if len(both) else positions[:0]
    worst_point = positions[int(numpy.argmax(both))] if len(both) else None
    near_worst = numpy.linalg.norm(worst - worst_point, axis=1) <= 0.05 * diagonal if len(worst) else numpy.zeros(0, bool)

    emit({
        "diagonal": diagonal,
        "samples_each_way": samples,
        "max_percent": percent(max(forward_summary["max"], backward_summary["max"])),
        "p95_percent": percent(numpy.percentile(both, 95)) if len(both) else None,
        "p99_percent": percent(numpy.percentile(both, 99)) if len(both) else None,
        "worst_samples": int(len(worst)),
        "worst_share_near_max_percent": round(100.0 * float(near_worst.mean()), 1) if len(worst) else None,
        "worst_point": [round(float(value), 4) for value in worst_point] if worst_point is not None else None,
        "mean_percent": percent(numpy.mean(both)) if len(both) else None,
        "candidate_to_reference_max_percent": percent(forward_summary["max"]),
        "reference_to_candidate_max_percent": percent(backward_summary["max"]),
    })


def load_with_uvs(path):
    """trimesh drops TEXCOORD_0 from primitives that have no material, so a freshly unwrapped mesh would read as
    UV-less. Give such primitives an empty default material in a temporary copy, then load that."""
    import struct
    import tempfile

    import trimesh

    path = Path(path)
    raw = path.read_bytes()
    if raw[:4] != b"glTF":
        return trimesh.load(path, force="scene", process=False)
    json_length = struct.unpack("<I", raw[12:16])[0]
    document = json.loads(raw[20:20 + json_length])
    primitives = [primitive for mesh in document.get("meshes", []) for primitive in mesh.get("primitives", [])]
    missing = [primitive for primitive in primitives if "material" not in primitive and "TEXCOORD_0" in primitive.get("attributes", {})]
    if not missing:
        return trimesh.load(path, force="scene", process=False)
    document.setdefault("materials", []).append({"name": "uv_probe_default"})
    for primitive in missing:
        primitive["material"] = len(document["materials"]) - 1
    encoded = json.dumps(document).encode("utf-8")
    encoded += b" " * ((4 - len(encoded) % 4) % 4)
    rest = raw[20 + json_length:]
    body = struct.pack("<II", len(encoded), 0x4E4F534A) + encoded + rest
    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as handle:
        handle.write(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)
        temporary = handle.name
    try:
        return trimesh.load(temporary, force="scene", process=False)
    finally:
        Path(temporary).unlink(missing_ok=True)


def triangle_areas_2d(points):
    edge_one = points[:, 1] - points[:, 0]
    edge_two = points[:, 2] - points[:, 0]
    return 0.5 * (edge_one[:, 0] * edge_two[:, 1] - edge_one[:, 1] * edge_two[:, 0])


def uv_metrics(path):
    """Overlap: share of UV area covered more than once, from rasterised coverage at 2048 px against the analytic sum
    of triangle areas (mirrored or stacked islands count as overlap). Stretch: per-face ratio of UV area share to
    surface area share; 1 means no area distortion."""
    import numpy
    import trimesh
    from PIL import Image, ImageDraw

    scene = load_with_uvs(path)
    resolution = 2048
    rows = []
    for geometry in scene.geometry.values():
        if not isinstance(geometry, trimesh.Trimesh):
            continue
        uv = getattr(geometry.visual, "uv", None)
        if uv is None or len(uv) != len(geometry.vertices):
            rows.append({"has_uv": False, "triangles": int(len(geometry.faces))})
            continue
        corners = uv[geometry.faces]
        signed_area = triangle_areas_2d(corners)
        uv_area = numpy.abs(signed_area)
        surface_area = geometry.area_faces
        valid = (uv_area > 0) & (surface_area > 0)
        ratio = numpy.ones(len(uv_area))
        ratio[valid] = (uv_area[valid] / uv_area[valid].sum()) / (surface_area[valid] / surface_area[valid].sum())
        distortion = numpy.maximum(ratio, 1.0 / numpy.maximum(ratio, 1e-12))
        weights = surface_area / max(surface_area.sum(), 1e-12)
        wrapped = numpy.mod(corners, 1.0)
        spans_tile = (corners.max(axis=1) - corners.min(axis=1)).max(axis=1) >= 1.0
        mask = Image.new("1", (resolution, resolution), 0)
        drawer = ImageDraw.Draw(mask)
        pixel_area_sum = 0.0
        for corner_set, wraps in zip(wrapped, spans_tile):
            if wraps:
                continue
            pixels = [(float(x) * resolution, float(1.0 - y) * resolution) for x, y in corner_set]
            drawer.polygon(pixels, fill=1)
        tile_corners = wrapped[~spans_tile]
        pixel_area_sum = float(numpy.abs(triangle_areas_2d(tile_corners)).sum()) * resolution * resolution
        covered = float(numpy.asarray(mask, dtype=bool).sum())
        overlap = max(0.0, (pixel_area_sum - covered) / pixel_area_sum) if pixel_area_sum > resolution else 0.0
        rows.append({
            "has_uv": True,
            "triangles": int(len(geometry.faces)),
            "overlap_percent": round(100.0 * overlap, 2),
            "flipped_faces_percent": round(100.0 * float(weights[signed_area < 0].sum()), 2),
            "stretch_p95": round(float(numpy.percentile(distortion[valid], 95)), 3) if valid.any() else None,
            "area_outside_half_to_double_percent": round(100.0 * float(weights[(ratio < 0.5) | (ratio > 2.0)].sum()), 2),
            "zero_area_uv_faces": int(numpy.sum(uv_area <= 0)),
        })
    with_uv = [row for row in rows if row["has_uv"]]
    total = sum(row["triangles"] for row in with_uv) or 1

    def weighted(key):
        values = [(row[key], row["triangles"]) for row in with_uv if row.get(key) is not None]
        return round(sum(value * count for value, count in values) / max(sum(count for _, count in values), 1), 3) if values else None

    emit({
        "primitives": len(rows),
        "primitives_without_uv": sum(1 for row in rows if not row["has_uv"]),
        "overlap_percent": weighted("overlap_percent"),
        "flipped_faces_percent": weighted("flipped_faces_percent"),
        "stretch_p95": max((row["stretch_p95"] for row in with_uv if row.get("stretch_p95")), default=None),
        "area_outside_half_to_double_percent": weighted("area_outside_half_to_double_percent"),
        "triangles_with_uv": total if with_uv else 0,
    })


def uv_layout(path, texture_size, padding):
    """Texel density and island padding of TEXCOORD_0, the UV gate of the asset pipeline.
    Islands are faces joined through shared vertices (glTF splits UV seams into separate vertices).
    Density per island, in pixels per metre at texture_size: sqrt(UV area * size^2 / world surface area), in world
    space so node scale counts. Padding: texels of two different islands closer than `padding` pixels."""
    import numpy
    import trimesh
    from PIL import Image, ImageDraw
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    scene = load_with_uvs(path)
    densities = []
    island_areas = []
    island_polygons = []
    for node_name in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node_name]
        geometry = scene.geometry[geometry_name]
        uv = getattr(getattr(geometry, "visual", None), "uv", None)
        if not isinstance(geometry, trimesh.Trimesh) or uv is None or len(uv) != len(geometry.vertices):
            continue
        world = geometry.copy()
        world.apply_transform(transform)
        faces = geometry.faces
        face_count = len(faces)
        # Exporters also split vertices at normal seams, so weld by position and UV: two faces belong to one island
        # when they share a corner with the same position and the same UV. Measured 2026-11-24: without the weld a
        # smooth-shaded body read as 6,526 one-face islands and thousands of false padding clashes.
        corner_keys = numpy.hstack([numpy.round(geometry.vertices * 1e5), numpy.round(uv * 1e6)]).astype(numpy.int64)
        _, welded = numpy.unique(corner_keys, axis=0, return_inverse=True)
        welded = welded.reshape(-1)
        rows = numpy.repeat(numpy.arange(face_count), 3)
        incidence = coo_matrix((numpy.ones(face_count * 3), (rows, welded[faces].reshape(-1))), shape=(face_count, int(welded.max()) + 1)).tocsr()
        adjacency = incidence @ incidence.T
        _, labels = connected_components(adjacency, directed=False)
        uv_area = numpy.abs(triangle_areas_2d(uv[faces]))
        surface_area = world.area_faces
        for label in numpy.unique(labels):
            members = labels == label
            area = float(surface_area[members].sum())
            mapped = float(uv_area[members].sum())
            if area <= 0 or mapped <= 0:
                continue
            densities.append(math.sqrt(mapped * texture_size * texture_size / area))
            island_areas.append(area)
            island_polygons.append(uv[faces[members]])
    if not densities:
        emit({"islands": 0})
        return
    densities = numpy.array(densities)
    weights = numpy.array(island_areas) / sum(island_areas)
    order = numpy.argsort(densities)
    cumulative = numpy.cumsum(weights[order])
    median = float(densities[order][numpy.searchsorted(cumulative, 0.5)])
    outside = (densities < median / 2.0) | (densities > median * 2.0)
    ids = Image.new("I", (texture_size, texture_size), 0)
    drawer = ImageDraw.Draw(ids)
    for island_number, triangles in enumerate(island_polygons, start=1):
        for corner_set in triangles:
            wrapped = numpy.mod(corner_set, 1.0) if (corner_set.max(axis=0) - corner_set.min(axis=0)).max() < 1.0 else None
            if wrapped is None:
                continue
            drawer.polygon([(float(x) * texture_size, float(1.0 - y) * texture_size) for x, y in wrapped], fill=island_number)
    grid = numpy.asarray(ids, dtype=numpy.int64)
    close_texels = numpy.zeros(grid.shape, dtype=bool)
    close_pairs = set()
    for shift_y in range(-padding, padding + 1):
        for shift_x in range(-padding, padding + 1):
            if (shift_x == 0 and shift_y == 0) or shift_x * shift_x + shift_y * shift_y > padding * padding:
                continue
            height, width = grid.shape
            source = grid[max(0, -shift_y):height - max(0, shift_y), max(0, -shift_x):width - max(0, shift_x)]
            target = grid[max(0, shift_y):height - max(0, -shift_y), max(0, shift_x):width - max(0, -shift_x)]
            clash = (source > 0) & (target > 0) & (source != target)
            if clash.any():
                close_texels[max(0, -shift_y):height - max(0, shift_y), max(0, -shift_x):width - max(0, shift_x)] |= clash
                pairs = numpy.unique(numpy.minimum(source[clash], target[clash]) * 1_000_000 + numpy.maximum(source[clash], target[clash]))
                close_pairs.update(int(pair) for pair in pairs[:2000])
    border = numpy.zeros(grid.shape, dtype=bool)
    border[:padding, :] = border[-padding:, :] = border[:, :padding] = border[:, -padding:] = True
    emit({
        "islands": len(densities),
        "texture_size": texture_size,
        "padding_px": padding,
        "texel_density_median_px_per_m": round(median, 2),
        "texel_density_p5_px_per_m": round(float(numpy.percentile(densities, 5)), 2),
        "texel_density_p95_px_per_m": round(float(numpy.percentile(densities, 95)), 2),
        "area_outside_half_to_double_density_percent": round(100.0 * float(weights[outside].sum()), 2),
        "island_pairs_closer_than_padding": len(close_pairs),
        "texels_closer_than_padding": int(close_texels.sum()),
        "texels_in_border_margin": int(((grid > 0) & border).sum()),
        "uv_space_used_percent": round(100.0 * float((grid > 0).mean()), 2),
    })


def uv_unwrap(folder):
    """xatlas on the raw primitives that mesh_gltf.mjs uv-export wrote. Only arrays go through Python, so materials,
    textures and every vertex attribute stay in the glTF and are remapped there by uv-apply."""
    import numpy
    import xatlas

    folder = Path(folder)
    entries = json.loads((folder / "manifest.json").read_text())
    for entry in entries:
        positions = numpy.fromfile(folder / f"{entry['name']}_positions.f32", dtype="<f4").reshape(-1, 3)
        indices = numpy.fromfile(folder / f"{entry['name']}_indices.u32", dtype="<u4").reshape(-1, 3)
        vertex_mapping, new_indices, uvs = xatlas.parametrize(positions, indices)
        vertex_mapping.astype("<u4").tofile(folder / f"{entry['name']}_vmapping.u32")
        new_indices.astype("<u4").reshape(-1).tofile(folder / f"{entry['name']}_new_indices.u32")
        uvs.astype("<f4").reshape(-1).tofile(folder / f"{entry['name']}_uvs.f32")
        entry["vertices_after"] = int(len(vertex_mapping))
    emit({"primitives_unwrapped": len(entries), "vertices_added": sum(entry["vertices_after"] - entry["vertices"] for entry in entries)})


def watertight(input_path, output_path):
    """Geometry-only watertight copy (collision, printing, booleans): drops UVs and materials on purpose."""
    import numpy
    import pymeshlab
    import trimesh

    mesh = welded_by_position(load_world_mesh(input_path))
    diagonal = float(numpy.linalg.norm(mesh.bounds[1] - mesh.bounds[0]))
    mesh_set = pymeshlab.MeshSet()
    mesh_set.add_mesh(pymeshlab.Mesh(mesh.vertices, mesh.faces), "input")
    mesh_set.meshing_remove_duplicate_vertices()
    mesh_set.meshing_remove_duplicate_faces()
    mesh_set.meshing_remove_null_faces()
    mesh_set.meshing_repair_non_manifold_edges(method="Remove Faces")
    mesh_set.meshing_repair_non_manifold_vertices()
    mesh_set.meshing_remove_unreferenced_vertices()
    mesh_set.meshing_close_holes(maxholesize=max(30, int(len(mesh.faces) ** 0.5)))
    mesh_set.meshing_re_orient_faces_coherently()
    result_mesh = mesh_set.current_mesh()
    repaired = trimesh.Trimesh(vertices=result_mesh.vertex_matrix(), faces=result_mesh.face_matrix(), process=False)
    repaired.fix_normals()
    repaired.export(output_path)
    status = None
    try:
        import manifold3d

        solid = manifold3d.Manifold(manifold3d.Mesh(vert_properties=repaired.vertices.astype("float32"), tri_verts=repaired.faces.astype("uint32")))
        status = str(solid.status()).split(".")[-1]
    except ImportError:
        pass
    emit({"watertight": bool(repaired.is_watertight), "manifold3d_status": status, "triangles": int(len(repaired.faces)), "diagonal": diagonal})


def structural_similarity(first, second):
    """Grey SSIM with an 7 px box window (Wang et al. 2004 constants)."""
    import numpy
    from scipy.ndimage import uniform_filter

    first = first.astype("float64")
    second = second.astype("float64")
    constant_one = (0.01 * 255) ** 2
    constant_two = (0.03 * 255) ** 2
    mean_first = uniform_filter(first, 7)
    mean_second = uniform_filter(second, 7)
    variance_first = uniform_filter(first * first, 7) - mean_first**2
    variance_second = uniform_filter(second * second, 7) - mean_second**2
    covariance = uniform_filter(first * second, 7) - mean_first * mean_second
    numerator = (2 * mean_first * mean_second + constant_one) * (2 * covariance + constant_two)
    denominator = (mean_first**2 + mean_second**2 + constant_one) * (variance_first + variance_second + constant_two)
    return numerator / denominator


def compare_views(reference_folder, candidate_folder, sheet_path):
    import numpy
    from PIL import Image

    reference_folder = Path(reference_folder)
    candidate_folder = Path(candidate_folder)
    views = sorted(path.name.replace("_albedo.png", "") for path in reference_folder.glob("*_albedo.png"))
    rows = []
    tiles = []
    for view in views:
        reference_albedo = numpy.asarray(Image.open(reference_folder / f"{view}_albedo.png").convert("RGBA"))
        candidate_albedo = numpy.asarray(Image.open(candidate_folder / f"{view}_albedo.png").convert("RGBA"))
        reference_normal = numpy.asarray(Image.open(reference_folder / f"{view}_normal.png").convert("RGBA"))
        candidate_normal = numpy.asarray(Image.open(candidate_folder / f"{view}_normal.png").convert("RGBA"))
        reference_mask = reference_albedo[..., 3] > 127
        candidate_mask = candidate_albedo[..., 3] > 127
        union = reference_mask | candidate_mask
        intersection = reference_mask & candidate_mask
        silhouette_iou = float(intersection.sum() / max(union.sum(), 1))

        def unit_normals(image):
            vectors = image[..., :3].astype("float64") / 255.0 * 2.0 - 1.0
            return vectors / numpy.maximum(numpy.linalg.norm(vectors, axis=-1, keepdims=True), 1e-9)

        # Pixels away from the outline: anti-aliased edge pixels mix in the transparent background.
        from scipy.ndimage import binary_erosion

        interior = binary_erosion(intersection, iterations=2)
        cosine = numpy.clip(numpy.sum(unit_normals(reference_normal) * unit_normals(candidate_normal), axis=-1), -1.0, 1.0)
        angles = numpy.degrees(numpy.arccos(cosine[interior])) if interior.any() else numpy.array([0.0])
        grey_reference = reference_albedo[..., :3].astype("float64") @ [0.299, 0.587, 0.114]
        grey_candidate = candidate_albedo[..., :3].astype("float64") @ [0.299, 0.587, 0.114]
        similarity_map = structural_similarity(grey_reference, grey_candidate)
        albedo_ssim = float(similarity_map[interior].mean()) if interior.any() else 1.0
        rows.append({
            "view": view,
            "reference_coverage": round(float(reference_mask.mean()), 4),
            "silhouette_iou": round(silhouette_iou, 4),
            "normal_angle_mean_deg": round(float(angles.mean()), 2),
            "normal_angle_p95_deg": round(float(numpy.percentile(angles, 95)), 2),
            "albedo_ssim": round(albedo_ssim, 4),
        })
        difference = numpy.zeros_like(reference_albedo)
        difference[..., 0] = (reference_mask & ~candidate_mask) * 255
        difference[..., 2] = (candidate_mask & ~reference_mask) * 255
        angle_image = numpy.zeros(reference_mask.shape)
        angle_image[interior] = numpy.clip(numpy.degrees(numpy.arccos(cosine[interior])) / 45.0, 0, 1) * 255
        difference[..., 1] = angle_image.astype("uint8")
        difference[..., 3] = 255
        tiles.append([reference_albedo, candidate_albedo, reference_normal, candidate_normal, difference])
    if tiles:
        height, width = tiles[0][0].shape[:2]
        sheet = Image.new("RGBA", (width * 5, height * len(tiles)), (40, 40, 40, 255))
        for row_index, row_tiles in enumerate(tiles):
            for column_index, tile in enumerate(row_tiles):
                background = Image.new("RGBA", (width, height), (40, 40, 40, 255))
                background.alpha_composite(Image.fromarray(tile))
                sheet.paste(background, (column_index * width, row_index * height))
        sheet.convert("RGB").save(sheet_path)

    def worst(key, pick):
        return pick(row[key] for row in rows) if rows else None

    emit({
        "views": rows,
        "reference_coverage_min": worst("reference_coverage", min),
        "silhouette_iou_min": worst("silhouette_iou", min),
        "normal_angle_mean_deg_max": worst("normal_angle_mean_deg", max),
        "normal_angle_p95_deg_max": worst("normal_angle_p95_deg", max),
        "albedo_ssim_min": worst("albedo_ssim", min),
        "sheet": str(sheet_path),
        "sheet_columns": "reference albedo | output albedo | reference normals | output normals | difference (red: lost, blue: added, green: normal angle up to 45 deg)",
    })


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    command, arguments = sys.argv[1], sys.argv[2:]
    if command == "topology":
        topology(arguments[0])
    elif command == "hausdorff":
        hausdorff(arguments[0], arguments[1], int(arguments[2]) if len(arguments) > 2 else 200000)
    elif command == "uv-metrics":
        uv_metrics(arguments[0])
    elif command == "uv-layout":
        uv_layout(arguments[0], int(arguments[1]), int(arguments[2]))
    elif command == "uv-unwrap":
        uv_unwrap(arguments[0])
    elif command == "watertight":
        watertight(arguments[0], arguments[1])
    elif command == "compare-views":
        compare_views(arguments[0], arguments[1], arguments[2])
    else:
        print(__doc__)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
