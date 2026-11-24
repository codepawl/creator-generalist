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

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


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


def shrinkwrap_to_source(item, source_mesh):
    # Voxels round the surface off by up to a voxel; snapping each vertex to the nearest input surface takes that back
    # (Tripo body: Hausdorff p95 0.110% to 0.094%). It cannot reach a crease with no low vertex inside it: touching
    # thighs kept their 1.5% max at the crotch. Part those in the high before retopo.
    target = bpy.data.objects.new("shrinkwrap_target", source_mesh)
    target.matrix_world = item.matrix_world.copy()
    bpy.context.scene.collection.objects.link(target)
    wrap = item.modifiers.new("shrinkwrap", "SHRINKWRAP")
    wrap.target = target
    wrap.wrap_method = "NEAREST_SURFACEPOINT"
    bpy.context.view_layer.objects.active = item
    bpy.ops.object.modifier_apply(modifier=wrap.name)
    bpy.data.objects.remove(target, do_unlink=True)


def welded_open_edges(mesh, diagonal, write_back=False):
    """Non-manifold edges after welding by position, the way the retopo gate counts them on the exported GLB.
    Coincident vertices also make faces that collapse once an exporter welds, so those are dissolved first."""
    checked = bmesh.new()
    checked.from_mesh(mesh)
    bmesh.ops.remove_doubles(checked, verts=checked.verts, dist=diagonal * 1e-6)
    bmesh.ops.dissolve_degenerate(checked, dist=diagonal * 1e-6, edges=checked.edges)
    if write_back:
        checked.to_mesh(mesh)
    open_edges = sum(1 for edge in checked.edges if len(edge.link_faces) != 2)
    slivers = sum(1 for face in checked.faces if face.calc_area() < (diagonal * 1e-5) ** 2)
    checked.free()
    return open_edges, slivers


def surface_kept(item, source_tree, diagonal, source_open_edges):
    """QuadriFlow can report success and still leave an invalid, torn mesh: on a 59k Tripo body it gave 25k
    degenerate triangles and a silhouette IoU of 0.46 (2026-11-24). Accept its result only when the mesh is valid,
    has no more open edges than the input, no zero-area faces, and 95% of its vertices sit within 1% of the
    diagonal from the input surface."""
    if item.data.validate(verbose=False):
        return False, "invalid mesh"
    # validate() passes slivers and holes: at 12k faces on the same body QuadriFlow left 30 zero-area faces and 15
    # non-manifold edges that the retopo gate then failed.
    open_edges, slivers = welded_open_edges(item.data, diagonal, write_back=True)
    if open_edges > source_open_edges or slivers:
        return False, f"{open_edges} non-manifold edges (input {source_open_edges}), {slivers} zero-area faces"
    distances = []
    for vertex in item.data.vertices:
        nearest = source_tree.find_nearest(item.matrix_world @ vertex.co)
        if nearest[0] is None:
            return False, "vertex far from the input"
        distances.append(nearest[3])
    distances.sort()
    p95 = distances[int(len(distances) * 0.95)] if distances else 0.0
    return p95 <= diagonal * 0.01, f"p95 distance {p95 / diagonal:.4f} of the diagonal"


def remesh(input_path, output_path, quads_path, method, faces):
    clear_scene()
    item = import_joined(input_path, "remesh_source")
    diagonal = diagonal_of(item)
    source_mesh = item.data.copy()
    source_open_edges, _ = welded_open_edges(source_mesh, diagonal)
    source_tree = BVHTree.FromPolygons([item.matrix_world @ vertex.co for vertex in source_mesh.vertices], [polygon.vertices[:] for polygon in source_mesh.polygons])
    path = method
    check = ""
    if method == "qremeshify":
        if not hasattr(bpy.ops, "qremeshify") or not hasattr(bpy.ops.qremeshify, "remesh"):
            raise SystemExit("QRemeshify add-on is not enabled in this Blender; use --remesh quadriflow or install it")
        bpy.ops.qremeshify.remesh()
    else:
        on_surface = quadriflow_on_surface(item, faces)
        kept, check = surface_kept(item, source_tree, diagonal, source_open_edges) if on_surface else (False, "cancelled")
        if kept:
            # mesh_prep hands over the watertight copy. On a Tripo grenade this kept the pin ring that every voxel
            # pass loses (Hausdorff max 0.81% against 1.28% through a voxel copy at the same 20k faces).
            path = "quadriflow on the surface"
        else:
            path = f"quadriflow on a voxel copy (surface pass rejected: {check})"
            item.data = source_mesh.copy()
            quadriflow_on_voxels(item, faces, diagonal)
            shrinkwrap_to_source(item, source_mesh)
            path += ", shrinkwrapped back onto the input"
            kept, check = surface_kept(item, source_tree, diagonal, source_open_edges)
            if not kept:
                path += f"; voxel pass also off the surface: {check}"
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
