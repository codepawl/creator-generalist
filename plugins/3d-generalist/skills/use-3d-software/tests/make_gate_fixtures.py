"""Build good and known-bad fixtures for `mesh_prep.py gate`, one pair per stage, into the folder given.

    blender -b --factory-startup --python make_gate_fixtures.py -- <folder>

retopo_good.blend   subdivided quad sphere            retopo_bad.blend   the same sphere triangulated and decimated
retopo_high.glb     the same sphere as the high       retopo_torn.blend  quads intact, every 7th vertex pushed out
uv_good.glb         cube, smart UV with margin        uv_overlap.glb     every face mapped onto the same square
                                                      uv_padding.glb     smart UV with no margin
texture_good.blend  sRGB colour, Non-Color data maps  texture_bad.blend  normal map in sRGB, colour map 300x300
bake_high.glb       noisy sphere (the high poly)
bake_low.blend      low sphere with a baked normal    bake_bad.blend     same with the normal map's blue inverted
rig_good.blend      bent tube with three bones        rig_bad.blend      same with unnormalised and missing weights
                                                      rig_stray.blend    hip-end vertices weighted to the lower leg
"""

import sys
from pathlib import Path

import bmesh
import bpy

folder = Path(sys.argv[sys.argv.index("--") + 1])
folder.mkdir(parents=True, exist_ok=True)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def save(name):
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / name))


def export(name):
    bpy.ops.export_scene.gltf(filepath=str(folder / name), export_format="GLB", export_apply=True)


def quad_sphere():
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    item = bpy.context.active_object
    modifier = item.modifiers.new("subdivide", "SUBSURF")
    modifier.levels = 3
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    cast = item.modifiers.new("cast", "CAST")
    cast.factor = 1.0
    bpy.ops.object.modifier_apply(modifier=cast.name)
    return item


def image(name, size, colour, non_colour):
    created = bpy.data.images.new(name, size[0], size[1], float_buffer=False)
    created.generated_color = colour
    if non_colour:
        created.colorspace_settings.name = "Non-Color"
    created.pack()
    return created


def principled_material(item, base, normal, roughness):
    material = bpy.data.materials.new("surface")
    material.use_nodes = True
    tree = material.node_tree
    principled = tree.nodes["Principled BSDF"]
    base_node = tree.nodes.new("ShaderNodeTexImage")
    base_node.image = base
    tree.links.new(base_node.outputs["Color"], principled.inputs["Base Color"])
    rough_node = tree.nodes.new("ShaderNodeTexImage")
    rough_node.image = roughness
    tree.links.new(rough_node.outputs["Color"], principled.inputs["Roughness"])
    normal_node = tree.nodes.new("ShaderNodeTexImage")
    normal_node.image = normal
    normal_map = tree.nodes.new("ShaderNodeNormalMap")
    tree.links.new(normal_node.outputs["Color"], normal_map.inputs["Color"])
    tree.links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])
    item.data.materials.append(material)
    return material, normal_node


def smart_uv(item, margin):
    bpy.context.view_layer.objects.active = item
    item.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(island_margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")


def retopo_fixtures():
    reset()
    quad_sphere()
    save("retopo_good.blend")
    export("retopo_high.glb")
    item = bpy.context.active_object
    for vertex in list(item.data.vertices)[::7]:
        vertex.co *= 1.4
    save("retopo_torn.blend")
    for vertex in list(item.data.vertices)[::7]:
        vertex.co /= 1.4
    decimate = item.modifiers.new("decimate", "DECIMATE")
    decimate.ratio = 0.4
    bpy.ops.object.modifier_apply(modifier=decimate.name)
    save("retopo_bad.blend")


def grid_uv(item, gap):
    """Each face of a cube on its own square cell, cells `gap` apart: no overlap, padding set by the gap."""
    mesh = bmesh.new()
    mesh.from_mesh(item.data)
    layer = mesh.loops.layers.uv.active
    cell = 0.3
    for index, face in enumerate(mesh.faces):
        left = 0.02 + (index % 3) * (cell + gap)
        bottom = 0.02 + (index // 3) * (cell + gap)
        corners = [(left, bottom), (left + cell, bottom), (left + cell, bottom + cell), (left, bottom + cell)]
        for loop, corner in zip(face.loops, corners):
            loop[layer].uv = corner
    mesh.to_mesh(item.data)
    mesh.free()


def uv_fixtures():
    reset()
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    item = bpy.context.active_object
    smart_uv(item, 0.05)
    export("uv_good.glb")
    grid_uv(item, gap=0.002)
    export("uv_padding.glb")
    mesh = bmesh.new()
    mesh.from_mesh(item.data)
    layer = mesh.loops.layers.uv.active
    square = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]
    for face in mesh.faces:
        for loop, corner in zip(face.loops, square):
            loop[layer].uv = corner
    mesh.to_mesh(item.data)
    mesh.free()
    export("uv_overlap.glb")


def texture_fixtures():
    reset()
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    item = bpy.context.active_object
    smart_uv(item, 0.05)
    principled_material(item, image("colour", (512, 512), (0.6, 0.3, 0.2, 1), False),
                        image("normal", (512, 512), (0.5, 0.5, 1, 1), True), image("rough", (512, 512), (0.5, 0.5, 0.5, 1), True))
    save("texture_good.blend")
    reset()
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    item = bpy.context.active_object
    smart_uv(item, 0.05)
    principled_material(item, image("colour", (300, 300), (0.6, 0.3, 0.2, 1), False),
                        image("normal", (512, 512), (0.5, 0.5, 1, 1), False), image("rough", (512, 512), (0.5, 0.5, 0.5, 1), True))
    save("texture_bad.blend")


def bake_fixtures():
    reset()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=1.0)
    high = bpy.context.active_object
    high.name = "high"
    displace = high.modifiers.new("bumps", "DISPLACE")
    displace.texture = bpy.data.textures.new("bumps", "VORONOI")
    displace.texture.noise_scale = 0.3
    displace.strength = 0.02
    bpy.ops.object.modifier_apply(modifier=displace.name)
    bpy.ops.object.select_all(action="DESELECT")
    high.select_set(True)
    export("bake_high.glb")
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1.0)
    low = bpy.context.active_object
    low.name = "low"
    smart_uv(low, 0.02)
    normal = bpy.data.images.new("baked_normal", 512, 512)
    normal.colorspace_settings.name = "Non-Color"
    principled_material(low, image("colour", (512, 512), (0.7, 0.7, 0.7, 1), False), normal,
                        image("rough", (512, 512), (0.5, 0.5, 0.5, 1), True))
    tree = low.active_material.node_tree
    tree.nodes.active = next(node for node in tree.nodes if node.type == "TEX_IMAGE" and node.image == normal)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.render.bake.use_selected_to_active = True
    scene.render.bake.use_cage = False
    scene.render.bake.cage_extrusion = 0.0
    scene.render.bake.max_ray_distance = 0.2
    scene.render.bake.margin = 8
    bpy.ops.object.select_all(action="DESELECT")
    high.select_set(True)
    low.select_set(True)
    bpy.context.view_layer.objects.active = low
    bpy.ops.object.bake(type="NORMAL")
    normal.pack()
    bpy.data.objects.remove(high, do_unlink=True)
    save("bake_low.blend")
    pixels = list(normal.pixels)
    for index in range(2, len(pixels), 4):
        pixels[index] = 1.0 - pixels[index]
    normal.pixels = pixels
    normal.pack()
    save("bake_bad.blend")


def rig_fixtures():
    reset()
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.1, depth=2.0, location=(0, 0, 1.0))
    tube = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.loopcut_slide(MESH_OT_loopcut={"number_cuts": 15, "edge_index": 1})
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.armature_add(location=(0, 0, 0))
    armature = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT")
    bones = armature.data.edit_bones
    root = bones[0]
    root.name = "Hips"
    root.head, root.tail = (0, 0, 0), (0, 0, 0.6)
    upper = bones.new("UpperLeg")
    upper.head, upper.tail, upper.parent = (0, 0, 0.6), (0, 0, 1.3), root
    lower = bones.new("LowerLeg")
    lower.head, lower.tail, lower.parent = (0, 0, 1.3), (0, 0.02, 2.0), upper
    lower.use_connect = True
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    tube.select_set(True)
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    save("rig_good.blend")
    group = tube.vertex_groups["LowerLeg"]
    for vertex in tube.data.vertices[:20]:
        for element in list(vertex.groups):
            tube.vertex_groups[element.group].remove([vertex.index])
    for vertex in tube.data.vertices[20:40]:
        group.add([vertex.index], 0.3, "ADD")
    save("rig_bad.blend")
    bpy.ops.wm.open_mainfile(filepath=str(folder / "rig_good.blend"))
    tube = bpy.data.objects["Cylinder"]
    low_vertices = [vertex.index for vertex in tube.data.vertices if (tube.matrix_world @ vertex.co).z < 0.3]
    for group in tube.vertex_groups:
        group.remove(low_vertices)
    tube.vertex_groups["LowerLeg"].add(low_vertices, 1.0, "REPLACE")
    save("rig_stray.blend")


retopo_fixtures()
uv_fixtures()
texture_fixtures()
bake_fixtures()
rig_fixtures()
print("fixtures written to", folder)
