"""Blender side of `mesh_prep.py gate`: measures one pipeline stage of an asset and prints one JSON line.
mesh_prep.py applies the limits; this file only measures.

    blender -b --factory-startup -P blender_asset_gates.py -- retopo  <in.blend|glb|gltf|fbx|obj>
    blender -b --factory-startup -P blender_asset_gates.py -- texture <in.blend|glb|gltf|fbx|obj>
    blender -b --factory-startup -P blender_asset_gates.py -- bake    <low.blend|glb> <high.glb|...> <flat_out.glb> [ray_distance]
    blender -b --factory-startup -P blender_asset_gates.py -- rig     <in.blend|glb|gltf|fbx>
    blender -b --factory-startup -P blender_asset_gates.py -- export  <in.blend> <out.glb>

retopo:  quad share, triangles, n-gons, poles (6+ edges), non-manifold and loose geometry of the mesh as authored.
         Run it on the .blend or a quad OBJ: a glTF file is always triangles.
texture: per material, which PBR channels have an image, each image's colour space, size and whether it is one flat
         value. Colour space is only meaningful in a .blend (glTF fixes it by slot), so a glTF input says so.
bake:    the low-to-high gap (how far the bake rays must reach), the ray distance or cage extrusion set in the file,
         the share of normal-map texels inside UV islands that point into the surface (blue below 0.5), and a copy
         of the low mesh with its normal map removed (flat_out) so mesh_prep can show the bake improves the shading.
rig:     skin weights (unweighted, more than 4 influences, not normalised, deform bones with no weights) and a bend
         test: each elbow, knee and spine bone is turned 70 degrees on its own and faces that collapse (area below
         15% of rest) or vertices that move while far from every bone the bend turns (stray weights) are counted.
"""

import json
import math
import os
import re
import sys
from pathlib import Path

import bmesh
import bpy
import numpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

POLE_EDGE_COUNT = 6
BEND_DEGREES = 70.0
COLLAPSED_AREA_RATIO = 0.15
BEND_BONE_PATTERN = re.compile(r"fore ?arm|lower ?arm|elbow|lower ?leg|shin|calf|knee|(^|[:_. ])(left|right|l|r)?[_. ]?leg$|spine", re.IGNORECASE)
PBR_INPUTS = ["Base Color", "Normal", "Roughness", "Metallic", "Alpha", "Emission Color"]
DATA_INPUTS = {"Normal", "Roughness", "Metallic", "Alpha"}


def emit(result):
    print(json.dumps(result))


def chosen(mesh_objects, apply_filter):
    """Keep only the objects named in MESH_PREP_GATE_OBJECTS (comma list), e.g. the low poly of a .blend that also
    holds the high poly. Without the variable every mesh object counts."""
    names = [name.strip() for name in os.environ.get("MESH_PREP_GATE_OBJECTS", "").split(",") if name.strip()]
    if not apply_filter or not names:
        return mesh_objects
    kept = [item for item in mesh_objects if item.name in names]
    if not kept:
        raise SystemExit(f"none of the objects {names} found; mesh objects are {[item.name for item in mesh_objects]}")
    return kept


def load(path, apply_filter=True):
    """Open a .blend, or import any other format into an empty scene. Returns the new mesh objects."""
    path = Path(path)
    if path.suffix.lower() == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(path))
        return chosen([item for item in bpy.context.scene.objects if item.type == "MESH"], apply_filter)
    before = set(bpy.data.objects)
    suffix = path.suffix.lower()
    if suffix in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    elif suffix == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path))
    else:
        raise SystemExit(f"unsupported file type: {path}")
    return chosen([item for item in bpy.data.objects if item not in before and item.type == "MESH"], apply_filter)


def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def world_bmesh(item):
    mesh = bmesh.new()
    mesh.from_mesh(item.data)
    mesh.transform(item.matrix_world)
    return mesh


def retopo(path):
    mesh_objects = load(path)
    totals = {"faces": 0, "quads": 0, "triangles": 0, "ngons": 0, "vertices": 0, "poles": 0, "non_manifold_edges": 0, "loose_vertices": 0, "loose_edges": 0}
    for item in mesh_objects:
        mesh = world_bmesh(item)
        for face in mesh.faces:
            corner_count = len(face.verts)
            totals["faces"] += 1
            if corner_count == 3:
                totals["triangles"] += 1
            elif corner_count == 4:
                totals["quads"] += 1
            else:
                totals["ngons"] += 1
        totals["vertices"] += len(mesh.verts)
        totals["poles"] += sum(1 for vertex in mesh.verts if len(vertex.link_edges) >= POLE_EDGE_COUNT)
        totals["non_manifold_edges"] += sum(1 for edge in mesh.edges if not edge.is_manifold and not edge.is_boundary)
        totals["loose_vertices"] += sum(1 for vertex in mesh.verts if not vertex.link_edges)
        totals["loose_edges"] += sum(1 for edge in mesh.edges if not edge.link_faces)
        mesh.free()
    face_count = max(totals["faces"], 1)
    totals["quad_share"] = round(totals["quads"] / face_count, 4)
    totals["pole_share"] = round(totals["poles"] / max(totals["vertices"], 1), 4)
    totals["triangle_equivalent"] = totals["triangles"] + 2 * totals["quads"] + totals["ngons"] * 3
    totals["objects"] = len(mesh_objects)
    totals["source_is_triangulated_format"] = Path(path).suffix.lower() in (".glb", ".gltf")
    emit(totals)


def image_feeding(socket, depth=0):
    """The image texture node behind a socket, through Normal Map, separate-colour and reroute nodes."""
    if not socket.is_linked or depth > 6:
        return None, None
    node = socket.links[0].from_node
    if node.type == "TEX_IMAGE":
        return node, socket.links[0].from_socket.name
    for name in ("Color", "Image", "Input", "Vector"):
        if name in node.inputs:
            found, output_name = image_feeding(node.inputs[name], depth + 1)
            if found:
                return found, output_name
    for node_input in node.inputs:
        found, output_name = image_feeding(node_input, depth + 1)
        if found:
            return found, output_name
    return None, None


def image_is_flat(image):
    """True when every sampled pixel holds the same value: a texture that could be a number."""
    if image.size[0] == 0:
        return None
    pixels = numpy.empty(image.size[0] * image.size[1] * image.channels, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape(-1, image.channels)[::97, :3]
    return bool(float(pixels.std(axis=0).max()) < 1.0 / 255.0)


def texture(path):
    mesh_objects = load(path)
    from_gltf = Path(path).suffix.lower() in (".glb", ".gltf")
    materials = []
    seen = set()
    for item in mesh_objects:
        for slot in item.material_slots:
            material = slot.material
            if material is None or material.name in seen:
                continue
            seen.add(material.name)
            row = {"material": material.name, "channels": {}}
            principled = None
            if material.use_nodes:
                principled = next((node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
            if principled is None:
                row["error"] = "no Principled BSDF"
                materials.append(row)
                continue
            for input_name in PBR_INPUTS:
                if input_name not in principled.inputs:
                    continue
                node, output_name = image_feeding(principled.inputs[input_name])
                if node is None or node.image is None:
                    continue
                image = node.image
                colour_space = image.colorspace_settings.name
                row["channels"][input_name] = {
                    "image": image.name,
                    "size": list(image.size),
                    "colour_space": colour_space,
                    "expected": "Non-Color" if input_name in DATA_INPUTS else "sRGB",
                    "colour_space_ok": None if from_gltf else ((colour_space in ("Non-Color", "Raw", "Linear Rec.709")) == (input_name in DATA_INPUTS) or (input_name == "Alpha" and output_name == "Alpha")),
                    "flat": image_is_flat(image),
                }
            materials.append(row)
    emit({"materials": materials, "colour_space_checkable": not from_gltf, "objects": len(mesh_objects)})


def joined_copy(mesh_objects, name):
    mesh = bmesh.new()
    for item in mesh_objects:
        part = world_bmesh(item)
        data = bpy.data.meshes.new("part")
        part.to_mesh(data)
        part.free()
        mesh.from_mesh(data)
        bpy.data.meshes.remove(data)
    return mesh


def measure_gap(low_mesh, high_tree, size):
    """Distance from each low face centre to the high surface along the face normal, outward then inward. Vertex
    normals average across hard edges: on a hydrant their diagonal missed the high's bevels and read a gap of 16%
    of the size where the low sat within 0.7%."""
    reach = size * 0.25
    distances = []
    misses = 0
    for face in low_mesh.faces:
        normal = face.normal
        if normal.length < 0.5:
            continue
        centre = face.calc_center_median()
        best = None
        for direction in (normal, -normal):
            hit, _, _, distance = high_tree.ray_cast(centre - direction * 1e-5, direction, reach)
            if hit is not None and (best is None or distance < best):
                best = distance
        if best is None:
            misses += 1
            continue
        distances.append(best)
    values = numpy.array(distances) if distances else numpy.zeros(1)
    return {
        "gap_p50": round(float(numpy.percentile(values, 50)), 5),
        "gap_p99": round(float(numpy.percentile(values, 99)), 5),
        "gap_max": round(float(values.max()), 5),
        "faces_without_high_surface": misses,
        "face_count": len(low_mesh.faces),
    }


def normal_map_of(mesh_objects):
    for item in mesh_objects:
        for slot in item.material_slots:
            material = slot.material
            if material is None or not material.use_nodes:
                continue
            for node in material.node_tree.nodes:
                if node.type == "NORMAL_MAP":
                    image_node, _ = image_feeding(node.inputs["Color"])
                    if image_node and image_node.image:
                        return material, node, image_node
    return None, None, None


def island_texels(mesh_objects, width, height):
    """Mask of texels covered by any UV triangle of the active UV map, rasterised at the image size."""
    mask = numpy.zeros((height, width), dtype=bool)
    for item in mesh_objects:
        mesh = bmesh.new()
        mesh.from_mesh(item.data)
        uv_layer = mesh.loops.layers.uv.active
        if uv_layer is None:
            mesh.free()
            continue
        bmesh.ops.triangulate(mesh, faces=mesh.faces[:])
        for face in mesh.faces:
            corners = numpy.array([[loop[uv_layer].uv.x * width, loop[uv_layer].uv.y * height] for loop in face.loops])
            low = numpy.floor(corners.min(axis=0)).astype(int)
            high = numpy.ceil(corners.max(axis=0)).astype(int)
            low = numpy.clip(low, 0, [width - 1, height - 1])
            high = numpy.clip(high, 0, [width - 1, height - 1])
            if (high - low).min() < 0:
                continue
            xs, ys = numpy.meshgrid(numpy.arange(low[0], high[0] + 1) + 0.5, numpy.arange(low[1], high[1] + 1) + 0.5)
            first, second, third = corners
            denominator = (second[1] - third[1]) * (first[0] - third[0]) + (third[0] - second[0]) * (first[1] - third[1])
            if abs(denominator) < 1e-12:
                continue
            weight_one = ((second[1] - third[1]) * (xs - third[0]) + (third[0] - second[0]) * (ys - third[1])) / denominator
            weight_two = ((third[1] - first[1]) * (xs - third[0]) + (first[0] - third[0]) * (ys - third[1])) / denominator
            inside = (weight_one >= 0) & (weight_two >= 0) & (weight_one + weight_two <= 1)
            mask[low[1]:high[1] + 1, low[0]:high[0] + 1] |= inside
        mesh.free()
    return mask


def bake(low_path, high_path, flat_path, ray_distance_argument):
    low_objects = load(low_path)
    scene_bake = bpy.context.scene.render.bake
    file_ray_distance = None
    if Path(low_path).suffix.lower() == ".blend":
        file_ray_distance = scene_bake.cage_extrusion if scene_bake.use_cage else (scene_bake.max_ray_distance or None)
    high_objects = load(high_path, apply_filter=False)
    low_mesh = joined_copy(low_objects, "low")
    high_mesh = joined_copy(high_objects, "high")
    corners = [vertex.co for vertex in high_mesh.verts]
    size = (Vector(map(max, *corners)) - Vector(map(min, *corners))).length if corners else 1.0
    high_tree = BVHTree.FromBMesh(high_mesh)
    result = {"size": round(size, 4), **measure_gap(low_mesh, high_tree, size)}
    result["ray_distance"] = float(ray_distance_argument) if ray_distance_argument else file_ray_distance
    material, normal_node, image_node = normal_map_of(low_objects)
    result["has_normal_map"] = image_node is not None
    if image_node is not None:
        image = image_node.image
        width, height = image.size
        pixels = numpy.empty(width * height * image.channels, dtype=numpy.float32)
        image.pixels.foreach_get(pixels)
        pixels = pixels.reshape(height, width, image.channels)
        mask = island_texels(low_objects, width, height)
        inside = pixels[mask]
        result["normal_map"] = image.name
        result["normal_map_size"] = [width, height]
        result["normal_map_colour_space"] = image.colorspace_settings.name
        result["island_texels"] = int(mask.sum())
        if len(inside):
            result["inward_texel_share"] = round(float((inside[:, 2] < 0.5).mean()), 5)
            lengths = numpy.linalg.norm(inside[:, :3] * 2.0 - 1.0, axis=1)
            result["bad_length_texel_share"] = round(float((numpy.abs(lengths - 1.0) > 0.25).mean()), 5)
            result["flat_texel_share"] = round(float((numpy.abs(inside[:, :3] - [0.5, 0.5, 1.0]).max(axis=1) < 2.0 / 255.0).mean()), 5)
        tree = material.node_tree
        for link in list(normal_node.outputs["Normal"].links):
            tree.links.remove(link)
    for item in high_objects:
        bpy.data.objects.remove(item, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    for item in low_objects:
        item.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(flat_path), use_selection=True, export_format="GLB", export_apply=True)
    low_mesh.free()
    high_mesh.free()
    emit(result)


def face_areas(mesh_data):
    areas = numpy.empty(len(mesh_data.polygons), dtype=numpy.float64)
    mesh_data.polygons.foreach_get("area", areas)
    return areas


def evaluated_state(item):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = item.evaluated_get(depsgraph)
    data = evaluated.to_mesh()
    positions = numpy.empty(len(data.vertices) * 3, dtype=numpy.float64)
    data.vertices.foreach_get("co", positions)
    areas = face_areas(data)
    evaluated.to_mesh_clear()
    matrix = numpy.array(item.matrix_world)
    positions = positions.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
    return positions, areas


def rig(path):
    mesh_objects = load(path)
    armatures = [item for item in bpy.context.scene.objects if item.type == "ARMATURE"]
    result = {"armatures": len(armatures), "skinned_objects": 0, "vertices": 0, "unweighted_vertices": 0,
              "over_four_influences": 0, "unnormalised_vertices": 0, "deform_bones": 0, "deform_bones_without_weights": [],
              "bends": [], "bend_degrees": BEND_DEGREES}
    if not armatures:
        emit(result)
        return
    armature = armatures[0]
    deform_bones = [bone.name for bone in armature.data.bones if bone.use_deform]
    result["deform_bones"] = len(deform_bones)
    weighted_bones = set()
    skinned = [item for item in mesh_objects if any(modifier.type == "ARMATURE" for modifier in item.modifiers)]
    result["skinned_objects"] = len(skinned)
    for item in skinned:
        group_names = {group.index: group.name for group in item.vertex_groups}
        for vertex in item.data.vertices:
            result["vertices"] += 1
            weights = [(group_names.get(element.group), element.weight) for element in vertex.groups if element.weight > 1e-4 and group_names.get(element.group) in deform_bones]
            for name, _ in weights:
                weighted_bones.add(name)
            total = sum(weight for _, weight in weights)
            if total <= 1e-4:
                result["unweighted_vertices"] += 1
                continue
            if len(weights) > 4:
                result["over_four_influences"] += 1
            if abs(total - 1.0) > 0.015:
                result["unnormalised_vertices"] += 1
    result["deform_bones_without_weights"] = sorted(set(deform_bones) - weighted_bones)[:20]
    result["deform_bones_without_weights_count"] = len(set(deform_bones) - weighted_bones)
    bpy.context.view_layer.objects.active = armature
    armature.data.pose_position = "POSE"
    rest = {item.name: evaluated_state(item) for item in skinned}
    bend_bones = [bone for bone in armature.pose.bones if BEND_BONE_PATTERN.search(bone.name) and bone.name in weighted_bones]
    all_rest = numpy.vstack([state[0] for state in rest.values()])
    height = float(all_rest[:, 2].max() - all_rest[:, 2].min()) or 1.0
    for pose_bone in bend_bones:
        # The bones this bend moves, as world segments before the bend. A vertex that moves while far from all of them
        # carries a stray weight (a hip vertex weighted to the forearm).
        chain = [pose_bone] + list(pose_bone.children_recursive)
        segments = [(numpy.array(armature.matrix_world @ bone.head), numpy.array(armature.matrix_world @ bone.tail)) for bone in chain]
        # A torso surface sits up to about 0.12 of body height from the spine line, so reach is 0.2 of the height.
        reach = max(pose_bone.bone.length * armature.matrix_world.to_scale().x, height * 0.2)
        # Compose the bend onto the pose the file already has; switching rotation mode would drop that pose and turn
        # the bone by more than the bend.
        saved_basis = pose_bone.matrix_basis.copy()
        pose_bone.matrix_basis = saved_basis @ Matrix.Rotation(math.radians(BEND_DEGREES), 4, "X")
        bpy.context.view_layer.update()
        collapsed = 0
        faces = 0
        jumped = 0
        for item in skinned:
            positions, areas = evaluated_state(item)
            rest_positions, rest_areas = rest[item.name]
            valid = rest_areas > 1e-12
            collapsed += int(numpy.sum((areas[valid] / rest_areas[valid]) < COLLAPSED_AREA_RATIO))
            faces += int(valid.sum())
            moved = numpy.linalg.norm(positions - rest_positions, axis=1)
            nearest = numpy.full(len(rest_positions), numpy.inf)
            for head, tail in segments:
                axis = tail - head
                share = numpy.clip(((rest_positions - head) @ axis) / max(float(axis @ axis), 1e-12), 0.0, 1.0)
                nearest = numpy.minimum(nearest, numpy.linalg.norm(rest_positions - (head + share[:, None] * axis), axis=1))
            jumped += int(numpy.sum((moved > height * 0.01) & (nearest > reach)))
        result["bends"].append({"bone": pose_bone.name, "collapsed_faces": collapsed, "collapsed_share": round(collapsed / max(faces, 1), 5), "jumped_vertices": jumped})
        pose_bone.matrix_basis = saved_basis
        bpy.context.view_layer.update()
    emit(result)


def main():
    values = sys.argv[sys.argv.index("--") + 1:]
    stage = values[0]
    if stage == "retopo":
        retopo(values[1])
    elif stage == "texture":
        texture(values[1])
    elif stage == "bake":
        empty_scene()
        bake(values[1], values[2], values[3], values[4] if len(values) > 4 else None)
    elif stage == "rig":
        rig(values[1])
    elif stage == "export":
        exported = load(values[1])
        bpy.ops.object.select_all(action="DESELECT")
        for item in exported:
            item.hide_set(False)
            item.select_set(True)
        bpy.ops.export_scene.gltf(filepath=str(values[2]), export_format="GLB", export_apply=True, use_selection=True)
        emit({"exported": values[2]})
    else:
        raise SystemExit(f"unknown stage {stage}")


if __name__ == "__main__":
    main()
