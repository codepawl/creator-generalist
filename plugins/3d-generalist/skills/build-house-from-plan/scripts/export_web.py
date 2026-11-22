"""Export a built house as one web GLB for a live walk page. Runs inside Blender.

    blender -b out/house.blend -t 6 -P scripts/export_web.py -- plan.json out/web/house.glb [--texture 1024] [--keep-site]

The builder's materials are Cycles node trees (tint, noise drift, per-piece variation), which glTF cannot carry.
This rebuilds each one as plain PBR from the same tables in house_core.py: the scan is tinted and desaturated
into a new texture, the tile size moves into the UVs, plain paints become flat factors, glass becomes
transmission and lamps become emission. Static meshes are then merged per material, so a web renderer draws one
batch per material instead of one per object. It writes `<name>.glb` and `<name>_web.json` (lamps, glass and the
bounds) next to each other. Furniture keeps its own glTF-ready materials, with textures cut to the same size.
"""

import json
import pathlib
import sys

import bmesh
import bpy
import numpy

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import house_core  # noqa: E402

TEXTURED = house_core.TEXTURED_MATERIALS
PLAIN = house_core.PLAIN_MATERIALS


def parse_arguments():
    arguments = sys.argv[sys.argv.index("--") + 1:]
    plan_path = pathlib.Path(arguments[0]).resolve()
    out_path = pathlib.Path(arguments[1]).resolve()
    texture_size = 1024
    if "--texture" in arguments:
        texture_size = int(arguments[arguments.index("--texture") + 1])
    return plan_path, out_path, texture_size


def image_node_with(material, name_part):
    if not material.use_nodes:
        return None
    for node in material.node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.image is not None and name_part in node.image.filepath.lower():
            return node
    return None


def resized_pixels(image, size):
    copy = image.copy()
    if copy.size[0] > size or copy.size[1] > size:
        copy.scale(size, size)
    width, height = copy.size
    pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
    copy.pixels.foreach_get(pixels)
    bpy.data.images.remove(copy)
    return pixels.reshape(height, width, 4), width, height


def new_image(name, pixels, width, height, colour):
    image = bpy.data.images.new(name, width, height, alpha=False, float_buffer=False)
    image.colorspace_settings.name = "sRGB" if colour else "Non-Color"
    image.pixels.foreach_set(pixels.ravel())
    image.file_format = "JPEG"
    image.pack()
    return image


def baked_diffuse(material_name, source_image, size):
    """Bake the builder's desaturate and tint into the texture, since glTF has one colour factor only."""
    _folder, _tile, tint, desaturate, _bump, _rough = TEXTURED[material_name]
    pixels, width, height = resized_pixels(source_image, size)
    rgb = pixels[..., :3]
    # Blender stores sRGB images as sRGB values in pixels; tint in linear, then back.
    linear = numpy.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    grey = (linear * numpy.array([0.2126, 0.7152, 0.0722])).sum(axis=2, keepdims=True)
    linear = grey + (linear - grey) * (1 - desaturate)
    linear = numpy.clip(linear * numpy.array(tint), 0, 1)
    rgb = numpy.where(linear <= 0.0031308, linear * 12.92, 1.055 * numpy.power(linear, 1 / 2.4) - 0.055)
    pixels[..., :3] = rgb
    pixels[..., 3] = 1
    return new_image(f"{material_name}_web_color", pixels, width, height, True)


def plain_principled(material, colour, roughness, metallic):
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Base Color"].default_value = (*colour, 1)
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return tree, shader


def rebuild_textured(material, size):
    name = material.name
    _folder, _tile, _tint, _desaturate, bump_strength, roughness_scale = TEXTURED[name]
    diffuse_node = image_node_with(material, "_diff") or image_node_with(material, "color")
    normal_node = image_node_with(material, "_nor")
    if diffuse_node is None:
        plain_principled(material, TEXTURED[name][2], 0.7, 0.0)
        return
    colour_image = baked_diffuse(name, diffuse_node.image, size)
    normal_image = None
    if normal_node is not None:
        pixels, width, height = resized_pixels(normal_node.image, size)
        normal_image = new_image(f"{name}_web_normal", pixels, width, height, False)
    tree, shader = plain_principled(material, (1, 1, 1), min(1.0, 0.75 * roughness_scale), 0.0)
    colour_node = tree.nodes.new("ShaderNodeTexImage")
    colour_node.image = colour_image
    tree.links.new(colour_node.outputs["Color"], shader.inputs["Base Color"])
    if normal_image is not None:
        normal_texture = tree.nodes.new("ShaderNodeTexImage")
        normal_texture.image = normal_image
        normal_map = tree.nodes.new("ShaderNodeNormalMap")
        normal_map.inputs["Strength"].default_value = max(0.2, bump_strength)
        tree.links.new(normal_texture.outputs["Color"], normal_map.inputs["Color"])
        tree.links.new(normal_map.outputs["Normal"], shader.inputs["Normal"])


def rebuild_materials(size):
    lamps = []
    for material in bpy.data.materials:
        name = material.name
        if name in TEXTURED:
            rebuild_textured(material, size)
        elif name in PLAIN:
            colour, roughness, metallic = PLAIN[name]
            plain_principled(material, colour, roughness, metallic)
        elif name == "glass":
            tree, shader = plain_principled(material, (0.96, 0.98, 0.97), 0.02, 0.0)
            shader.inputs["Transmission Weight"].default_value = 1.0
            shader.inputs["IOR"].default_value = 1.5
        elif name.startswith("lamp_"):
            tree, shader = plain_principled(material, (1.0, 0.85, 0.65), 0.6, 0.0)
            shader.inputs["Emission Color"].default_value = (1.0, 0.78, 0.55, 1)
            shader.inputs["Emission Strength"].default_value = 4.0
            lamps.append(name)
        else:
            shrink_textures(material, size)
    return lamps


def shrink_textures(material, size):
    if not material.use_nodes:
        return
    for node in material.node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.image is not None and not node.image.name.endswith("_web"):
            image = node.image
            if image.size[0] > size or image.size[1] > size:
                pixels, width, height = resized_pixels(image, size)
                colour = image.colorspace_settings.name == "sRGB"
                node.image = new_image(image.name + "_web", pixels, width, height, colour)


def scale_tiled_uvs(mesh_object):
    """The builder writes UVs in metres and tiles in the shader; move the tile size into the UVs."""
    mesh = mesh_object.data
    if not mesh.uv_layers:
        return
    uv_layer = mesh.uv_layers.active.data
    tile_by_slot = {}
    for index, slot in enumerate(mesh_object.material_slots):
        if slot.material is not None and slot.material.name in TEXTURED:
            tile_by_slot[index] = TEXTURED[slot.material.name][1]
    if not tile_by_slot:
        return
    for polygon in mesh.polygons:
        tile = tile_by_slot.get(polygon.material_index)
        if tile is None:
            continue
        for loop_index in polygon.loop_indices:
            u, v = uv_layer[loop_index].uv
            uv_layer[loop_index].uv = (u / tile, v / tile)


def drop_render_only_objects(keep_site):
    """Lights, cameras, fit zones and the sheet stay out. So does the site (ground, grass scatter, trees) unless
    asked: its grass is a geometry-nodes scatter of millions of instances, and a live page grows its own
    landscape with wind instead."""
    site = bpy.data.collections.get("site")
    site_objects = set(site.all_objects) if site is not None and not keep_site else set()
    for item in list(bpy.data.objects):
        hidden = item.hide_render or item.name.startswith(("fit_zone_", "sheet", "Camera"))
        if item.type in ("LIGHT", "CAMERA") or hidden or item in site_objects:
            bpy.data.objects.remove(item, do_unlink=True)


MAXIMUM_TRIANGLES_PER_MODEL = 60000


def capped(mesh):
    """Collapse a scanned model over the triangle cap: one scanned bed came in at 941k triangles, more than the
    whole house."""
    triangles = sum(len(polygon.vertices) - 2 for polygon in mesh.polygons)
    if triangles <= MAXIMUM_TRIANGLES_PER_MODEL:
        return mesh
    holder = bpy.data.objects.new("decimate_holder", mesh)
    bpy.context.scene.collection.objects.link(holder)
    modifier = holder.modifiers.new("cap", "DECIMATE")
    modifier.ratio = MAXIMUM_TRIANGLES_PER_MODEL / triangles
    bpy.context.view_layer.update()
    evaluated = holder.evaluated_get(bpy.context.evaluated_depsgraph_get())
    reduced = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True)
    bpy.data.objects.remove(holder)
    bpy.data.meshes.remove(mesh)
    print(f"WEB capped a model from {triangles} triangles", flush=True)
    return reduced


def evaluated_world_meshes():
    """A world-space copy of every visible mesh, collection instances and modifiers applied, with its materials."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    copies = []
    for instance in depsgraph.object_instances:
        source = instance.object
        # An instanced object sits in a collection outside the view layer, so only check visibility of real ones.
        if source.type != "MESH" or not (instance.is_instance or source.original.visible_get()):
            continue
        mesh = bpy.data.meshes.new_from_object(source, preserve_all_data_layers=True, depsgraph=depsgraph)
        mesh.transform(instance.matrix_world)
        if instance.matrix_world.determinant() < 0:
            mesh.flip_normals()
        materials = [slot.material for slot in source.original.material_slots] or [None]
        copies.append((mesh, materials, source.original))
    # Capping links a holder object, which would invalidate the instance iterator above, so it runs after it.
    return [(capped(mesh), materials, original) for mesh, materials, original in copies]


def merge_by_material(copies):
    """Append every copy into one bmesh with global material indices, then write one object per material.

    Pure data API: bpy.ops join and separate on hundreds of linked objects crashed Blender in background mode."""
    all_materials = []
    combined = bmesh.new()
    for mesh, materials, original in copies:
        holder = bpy.data.objects.new("holder", mesh)
        for material in materials:
            holder.data.materials.append(material)
        scale_tiled_uvs(holder)
        global_index = []
        for material in materials:
            if material not in all_materials:
                all_materials.append(material)
            global_index.append(all_materials.index(material))
        local_indices = numpy.zeros(len(mesh.polygons), dtype=numpy.int32)
        mesh.polygons.foreach_get("material_index", local_indices)
        local_indices = numpy.clip(local_indices, 0, len(global_index) - 1)
        mesh.polygons.foreach_set("material_index", numpy.array(global_index, dtype=numpy.int32)[local_indices])
        if mesh.uv_layers:
            mesh.uv_layers.active.name = "UVMap"
        combined.from_mesh(mesh)
        bpy.data.objects.remove(holder)
        bpy.data.meshes.remove(mesh)
    for item in list(bpy.data.objects):
        bpy.data.objects.remove(item, do_unlink=True)
    scene_collection = bpy.context.scene.collection
    for index, material in enumerate(all_materials):
        part = combined.copy()
        bmesh.ops.delete(part, geom=[face for face in part.faces if face.material_index != index], context="FACES")
        if not part.faces:
            part.free()
            continue
        for face in part.faces:
            face.material_index = 0
        name = material.name if material is not None else "unassigned"
        mesh = bpy.data.meshes.new(name)
        part.to_mesh(mesh)
        part.free()
        mesh.materials.append(material)
        scene_collection.objects.link(bpy.data.objects.new(name, mesh))
    combined.free()


def main():
    plan_path, out_path, texture_size = parse_arguments()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    drop_render_only_objects(keep_site="--keep-site" in sys.argv)
    rebuild_materials(texture_size)
    print("WEB step: materials rebuilt", flush=True)
    copies = evaluated_world_meshes()
    print("WEB step: copied", len(copies), "meshes", flush=True)
    merge_by_material(copies)
    print("WEB step: merged", flush=True)
    plan = json.loads(plan_path.read_text())
    lamps = plan.get("lamps", [])
    glass = sorted({item.name for item in bpy.data.objects if item.active_material and item.active_material.name == "glass"})
    bpy.ops.export_scene.gltf(
        filepath=str(out_path), export_format="GLB", export_image_format="JPEG", export_jpeg_quality=86,
        export_apply=True, export_lights=False, export_cameras=False, export_yup=True,
        export_texcoords=True, export_normals=True, export_vertex_color="ACTIVE",
    )
    corners = [item.matrix_world @ house_core.Vector(corner) for item in bpy.data.objects for corner in item.bound_box]
    summary = {
        "plan": plan_path.name, "glb": out_path.name, "plan_lamps": lamps, "glass_objects": glass,
        "materials": sorted({item.active_material.name for item in bpy.data.objects if item.active_material}),
        "bounds_blender_z_up": [[min(corner[i] for corner in corners) for i in range(3)],
                                [max(corner[i] for corner in corners) for i in range(3)]],
        "objects": len(bpy.data.objects), "bytes": out_path.stat().st_size,
    }
    out_path.with_name(out_path.stem + "_web.json").write_text(json.dumps(summary, indent=1))
    print("WEB GLB saved", out_path, summary["objects"], "objects", summary["bytes"], "bytes")


if __name__ == "__main__":
    main()
