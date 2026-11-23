"""Renders fixed views of a glTF file for the mesh_prep gate: unlit albedo and world-space normals (normal maps
included), each with a transparent background. The first call writes the framing (centre, radius) to a JSON file;
the second call reads it, so both files are shot by identical orthographic cameras.

    blender --background --factory-startup --python blender_views.py -- <in.glb> <out_dir> <framing.json> [size]
"""

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

VIEWS = {
    "front": (0.0, -1.0, 0.0),
    "back": (0.0, 1.0, 0.0),
    "left": (-1.0, 0.0, 0.0),
    "right": (1.0, 0.0, 0.0),
    "top": (0.0, 0.0, 1.0),
    "three_quarter": (1.0, -1.0, 0.8),
}


def arguments():
    values = sys.argv[sys.argv.index("--") + 1:]
    return Path(values[0]), Path(values[1]), Path(values[2]), int(values[3]) if len(values) > 3 else 512


def clear_scene():
    for item in list(bpy.data.objects):
        bpy.data.objects.remove(item, do_unlink=True)


def world_bounds(mesh_objects):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    low = Vector((1e30, 1e30, 1e30))
    high = Vector((-1e30, -1e30, -1e30))
    for item in mesh_objects:
        evaluated = item.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        for vertex in mesh.vertices:
            point = evaluated.matrix_world @ vertex.co
            low = Vector(map(min, low, point))
            high = Vector(map(max, high, point))
        evaluated.to_mesh_clear()
    return low, high


def principled_node(material):
    if not material.use_nodes:
        return None
    for node in material.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    return None


def rewire_unlit(material, mode):
    """Replace the material output with an emission of base colour or of the shading normal mapped to 0..1."""
    material.use_nodes = True
    tree = material.node_tree
    principled = principled_node(material)
    output = next((node for node in tree.nodes if node.type == "OUTPUT_MATERIAL"), None) or tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = 1.0
    if mode == "albedo":
        base = principled.inputs["Base Color"] if principled else None
        if base is not None and base.is_linked:
            tree.links.new(base.links[0].from_socket, emission.inputs["Color"])
        else:
            emission.inputs["Color"].default_value = base.default_value if base is not None else (0.8, 0.8, 0.8, 1.0)
    else:
        normal_input = principled.inputs["Normal"] if principled else None
        if normal_input is not None and normal_input.is_linked:
            source = normal_input.links[0].from_socket
        else:
            source = tree.nodes.new("ShaderNodeNewGeometry").outputs["Normal"]
        remap = tree.nodes.new("ShaderNodeVectorMath")
        remap.operation = "MULTIPLY_ADD"
        remap.inputs[1].default_value = (0.5, 0.5, 0.5)
        remap.inputs[2].default_value = (0.5, 0.5, 0.5)
        tree.links.new(source, remap.inputs[0])
        tree.links.new(remap.outputs["Vector"], emission.inputs["Color"])
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])


def prepare_materials(mesh_objects, mode, originals):
    for item in mesh_objects:
        if not item.data.materials:
            item.data.materials.append(bpy.data.materials.new("mesh_prep_default"))
        for slot_index, material in enumerate(item.data.materials):
            source = originals.setdefault((item.name, slot_index), material or bpy.data.materials.new("mesh_prep_default"))
            working = source.copy()
            rewire_unlit(working, mode)
            item.data.materials[slot_index] = working


def set_engine(scene):
    for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            scene.render.engine = engine
            return
        except TypeError:
            continue


def main():
    input_path, output_folder, framing_path, size = arguments()
    output_folder.mkdir(parents=True, exist_ok=True)
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    mesh_objects = [item for item in bpy.context.scene.objects if item.type == "MESH"]
    if framing_path.exists():
        framing = json.loads(framing_path.read_text())
    else:
        low, high = world_bounds(mesh_objects)
        centre = (low + high) / 2
        framing = {"centre": list(centre), "radius": max((high - low).length / 2, 1e-6)}
        framing_path.write_text(json.dumps(framing))
    centre = Vector(framing["centre"])
    radius = framing["radius"]

    scene = bpy.context.scene
    set_engine(scene)
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.eevee.taa_render_samples = 4
    scene.world = scene.world or bpy.data.worlds.new("mesh_prep_world")

    camera_data = bpy.data.cameras.new("mesh_prep_camera")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = radius * 2.2
    camera_data.clip_start = radius * 0.01
    camera_data.clip_end = radius * 8
    camera = bpy.data.objects.new("mesh_prep_camera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera

    originals = {}
    for mode, view_transform in (("albedo", "Standard"), ("normal", "Raw")):
        prepare_materials(mesh_objects, mode, originals)
        scene.view_settings.view_transform = view_transform
        scene.view_settings.look = "None"
        for view_name, direction in VIEWS.items():
            direction_vector = Vector(direction).normalized()
            camera.location = centre + direction_vector * radius * 3
            camera.rotation_euler = (-direction_vector).to_track_quat("-Z", "Y").to_euler()
            scene.render.filepath = str(output_folder / f"{view_name}_{mode}.png")
            bpy.ops.render.render(write_still=True)
    print(json.dumps({"views": list(VIEWS), "framing": framing}))


main()
