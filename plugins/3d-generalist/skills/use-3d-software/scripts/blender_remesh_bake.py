"""Blender steps of mesh_prep.

    remesh: blender -b --factory-startup -P blender_remesh_bake.py -- remesh <in.glb> <out.glb> <quads.obj> <method> <faces>
            method quadriflow (built in) or qremeshify (needs the QRemeshify add-on enabled). Writes a triangulated GLB
            for the next steps and an OBJ that keeps the quads for editing.
    bake:   blender -b --factory-startup -P blender_remesh_bake.py -- bake <source.glb> <target.glb> <out.glb> <size> <maps>
            maps: comma list of normal, basecolor, roughness. Bakes from the source surface onto the target's UVs
            (Cycles, selected to active). Maps not baked keep the target's own textures.
"""

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def arguments():
    return sys.argv[sys.argv.index("--") + 1:]


def clear_scene():
    for item in list(bpy.data.objects):
        bpy.data.objects.remove(item, do_unlink=True)


def import_joined(path, name):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    mesh_objects = [item for item in bpy.data.objects if item not in before and item.type == "MESH"]
    bpy.ops.object.select_all(action="DESELECT")
    for item in mesh_objects:
        item.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objects[0]
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    if len(mesh_objects) > 1:
        bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined.name = name
    for item in list(bpy.data.objects):
        if item not in before and item is not joined and item.type != "MESH":
            bpy.data.objects.remove(item, do_unlink=True)
    return joined


def diagonal_of(item):
    corners = [item.matrix_world @ Vector(corner) for corner in item.bound_box]
    low = Vector(map(min, *corners))
    high = Vector(map(max, *corners))
    return (high - low).length


def export_selected(path, item, materials=True):
    bpy.ops.object.select_all(action="DESELECT")
    item.select_set(True)
    bpy.context.view_layer.objects.active = item
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", use_selection=True, export_materials="EXPORT" if materials else "NONE")


def run_quadriflow(item, faces):
    before = len(item.data.polygons)
    result = bpy.ops.object.quadriflow_remesh(mode="FACES", target_faces=int(faces), use_preserve_sharp=True, use_preserve_boundary=True, smooth_normals=False)
    return "FINISHED" in result and len(item.data.polygons) < before


def quadriflow_on_surface(item, faces):
    """QuadriFlow straight on the input surface; False when it cancels (not closed or not manifold)."""
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    return run_quadriflow(item, faces)


def quadriflow_on_voxels(item, faces, diagonal):
    # Fallback for a surface QuadriFlow refuses. Voxels lose parts thin in two dimensions (wires, rings). The voxel
    # copy also leaves near-duplicate vertices where thin parts meet: on a Tripo grenade, merging at voxel/80 left
    # QuadriFlow cancelling and voxel/50 let it run, so merge at voxel/50 and retry coarser.
    voxel = item.modifiers.new("voxel", "REMESH")
    voxel.mode = "VOXEL"
    voxel_size = diagonal / 250
    voxel.voxel_size = voxel_size
    bpy.ops.object.modifier_apply(modifier=voxel.name)
    for merge_divisor in (50, 10):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles(threshold=voxel_size / merge_divisor)
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.mesh.select_non_manifold()
        bpy.ops.mesh.delete(type="VERT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.mesh.select_non_manifold()
        bpy.ops.mesh.fill_holes(sides=0)
        bpy.ops.object.mode_set(mode="OBJECT")
        if run_quadriflow(item, faces):
            return
    raise SystemExit("QuadriFlow did not run on the surface or on a voxel copy; the mesh is not a closed manifold with consistent normals")


def remesh(input_path, output_path, quads_path, method, faces):
    clear_scene()
    item = import_joined(input_path, "remesh_source")
    diagonal = diagonal_of(item)
    path = method
    if method == "qremeshify":
        if not hasattr(bpy.ops, "qremeshify") or not hasattr(bpy.ops.qremeshify, "remesh"):
            raise SystemExit("QRemeshify add-on is not enabled in this Blender; use --remesh quadriflow or install it")
        bpy.ops.qremeshify.remesh()
    elif quadriflow_on_surface(item, faces):
        # mesh_prep hands over the watertight copy. On a Tripo grenade this kept the pin ring that every voxel pass
        # loses (Hausdorff max 0.81% against 1.28% through a voxel copy at the same 20k faces).
        path = "quadriflow on the surface"
    else:
        path = "quadriflow on a voxel copy"
        quadriflow_on_voxels(item, faces, diagonal)
    item.data.materials.clear()
    bpy.ops.object.shade_flat()
    quads = sum(1 for polygon in item.data.polygons if len(polygon.vertices) == 4)
    polygons = len(item.data.polygons)
    bpy.ops.object.select_all(action="DESELECT")
    item.select_set(True)
    bpy.ops.wm.obj_export(filepath=str(quads_path), export_selected_objects=True, export_materials=False, export_uv=False)
    export_selected(output_path, item, materials=False)
    print(json.dumps({"method": method, "path": path, "polygons": polygons, "quad_share": round(quads / max(polygons, 1), 4)}))


def new_image(name, size, data):
    image = bpy.data.images.new(name, width=size, height=size, alpha=False, float_buffer=False)
    image.colorspace_settings.name = "Non-Color" if data else "sRGB"
    return image


def target_material(item):
    if item.data.materials and item.data.materials[0] is not None:
        material = item.data.materials[0]
    else:
        material = bpy.data.materials.new("baked")
        item.data.materials.append(material)
    material.use_nodes = True
    return material


def bake(source_path, target_path, output_path, size, maps):
    clear_scene()
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    source = import_joined(source_path, "bake_source")
    target = import_joined(target_path, "bake_target")
    diagonal = diagonal_of(source)
    if len(target.data.materials) > 1:
        raise SystemExit("bake needs a target with one material: every material would bake into the same UV space")
    material = target_material(target)
    tree = material.node_tree
    principled = next((node for node in tree.nodes if node.type == "BSDF_PRINCIPLED"), None) or tree.nodes.new("ShaderNodeBsdfPrincipled")
    bake_settings = scene.render.bake
    bake_settings.use_selected_to_active = True
    bake_settings.cage_extrusion = diagonal * 0.01
    bake_settings.max_ray_distance = diagonal * 0.03
    bake_settings.margin = 8
    results = {}
    for map_name in maps:
        image = new_image(f"baked_{map_name}", size, data=map_name != "basecolor")
        image_node = tree.nodes.new("ShaderNodeTexImage")
        image_node.image = image
        tree.nodes.active = image_node
        bpy.ops.object.select_all(action="DESELECT")
        source.select_set(True)
        target.select_set(True)
        bpy.context.view_layer.objects.active = target
        if map_name == "normal":
            bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT")
        elif map_name == "basecolor":
            # The diffuse colour pass is black on metal (a grenade's lever and cap baked black), so the source
            # bakes as non-metal; metallic itself is not baked and the target keeps its own value.
            source_bsdfs = [node for slot in source.material_slots if slot.material and slot.material.node_tree for node in slot.material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"]
            for node in source_bsdfs:
                metallic_input = node.inputs["Metallic"]
                for link in list(metallic_input.links):
                    link.id_data.links.remove(link)
                metallic_input.default_value = 0.0
            bake_settings.use_pass_direct = False
            bake_settings.use_pass_indirect = False
            bake_settings.use_pass_color = True
            bpy.ops.object.bake(type="DIFFUSE")
        elif map_name == "roughness":
            bpy.ops.object.bake(type="ROUGHNESS")
        image.pack()
        if map_name == "normal":
            normal_map = tree.nodes.new("ShaderNodeNormalMap")
            tree.links.new(image_node.outputs["Color"], normal_map.inputs["Color"])
            tree.links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])
        elif map_name == "basecolor":
            tree.links.new(image_node.outputs["Color"], principled.inputs["Base Color"])
        elif map_name == "roughness":
            tree.links.new(image_node.outputs["Color"], principled.inputs["Roughness"])
        results[map_name] = size
    export_selected(output_path, target)
    print(json.dumps({"baked": results, "cage_extrusion": bake_settings.cage_extrusion}))


def main():
    values = arguments()
    if values[0] == "remesh":
        remesh(Path(values[1]), Path(values[2]), Path(values[3]), values[4], int(values[5]))
    elif values[0] == "bake":
        bake(Path(values[1]), Path(values[2]), Path(values[3]), int(values[4]), values[5].split(","))
    else:
        raise SystemExit(__doc__)


main()
