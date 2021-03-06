import bpy
import mathutils

from . import strings
from . import options
from . import matrices

from . import blender_materials
from . import ldraw_colors


# https://blender.stackexchange.com/a/91687
# for f in bm.faces:
#     f.smooth = True
# mesh = context.object.data
# for f in mesh.polygons:
#     f.use_smooth = True
# values = [True] * len(mesh.polygons)
# mesh.polygons.foreach_set("use_smooth", values)
# bpy.context.object.active_material.use_backface_culling = True
# bpy.context.object.active_material.use_screen_refraction = True
# apply materials to mesh
# then mesh cleanup
# then apply slope materials
# this order is important because bmesh_ops causes
# mesh.polygons to get out of sync geometry.face_info
# which causes materials and slope materials to be applied incorrectly
# https://blender.stackexchange.com/questions/414/how-to-use-bmesh-to-add-verts-faces-and-edges-to-existing-geometry
# bm.verts.index_update()

def build_edge_indices(bm, geometry):
    # Create kd tree for fast "find nearest points" calculation
    # https://docs.blender.org/api/blender_python_api_current/mathutils.kdtree.html
    kd = mathutils.kdtree.KDTree(len(bm.verts))
    for i, v in enumerate(bm.verts):
        kd.insert(v.co, i)
    kd.balance()

    # Create edge_indices dictionary, which is the list of edges as pairs of indices into our verts array
    edge_indices = {}
    for i, edge in enumerate(geometry.edge_vertices):
        edges0 = [index for (co, index, dist) in kd.find_range(edge[0], options.merge_distance)]
        edges1 = [index for (co, index, dist) in kd.find_range(edge[1], options.merge_distance)]
        for e0 in edges0:
            for e1 in edges1:
                edge_indices[(e0, e1)] = True
                edge_indices[(e1, e0)] = True
    return edge_indices


def get_edge_mesh(key, filename, geometry):
    e_key = f"e_{key}"
    if e_key not in bpy.data.meshes:
        mesh = build_edge_mesh(e_key, filename, geometry)
        mesh.validate()
        mesh.update(calc_edges=True)
    mesh = bpy.data.meshes[e_key]
    return mesh


def build_edge_mesh(key, filename):
    mesh = bpy.data.meshes.new(key)
    mesh[strings.ldraw_filename_key] = filename

    if options.make_gaps and options.gap_target == "mesh":
        mesh.transform(matrices.scaled_matrix(options.gap_scale))

    return mesh


def get_gp_mesh(key, mesh):
    gp_key = f"gp_{key}"
    if gp_key not in bpy.data.grease_pencils:
        gp_mesh = bpy.data.grease_pencils.new(gp_key)

        gp_mesh.pixel_factor = 5.0
        gp_mesh.stroke_depth_order = "3D"

        gp_layer = gp_mesh.layers.new("gpl")
        gp_layer.line_change = 2

        gp_frame = gp_layer.frames.new(1)
        # gp_layer.active_frame = gp_frame

        for e in mesh.edges:
            gp_stroke = gp_frame.strokes.new()
            gp_stroke.material_index = 0
            gp_stroke.line_width = 10.0
            for v in e.vertices:
                i = len(gp_stroke.points)
                gp_stroke.points.add(1)
                gp_point = gp_stroke.points[i]
                gp_point.co = mesh.vertices[v].co

        apply_gp_materials(gp_mesh)
    gp_mesh = bpy.data.grease_pencils[gp_key]
    return gp_mesh


# https://blender.stackexchange.com/a/166492
def apply_gp_materials(gp_mesh):
    color_code = "0"
    color = ldraw_colors.get_color(color_code)

    use_edge_color = True
    base_material = blender_materials.get_material(color, use_edge_color=use_edge_color)
    if base_material is None:
        return

    material_name = f"gp_{base_material.name}"
    if material_name not in bpy.data.materials:
        material = base_material.copy()
        material.name = material_name
        bpy.data.materials.create_gpencil_data(material)  # https://developer.blender.org/T67102
    material = bpy.data.materials[material_name]
    gp_mesh.materials.append(material)

# https://youtu.be/cQ0qtcSymDI?t=356
# https://www.youtube.com/watch?v=cQ0qtcSymDI&t=0s
# https://www.blenderguru.com/articles/cycles-input-encyclopedia
# https://blenderscripting.blogspot.com/2011/05/blender-25-python-moving-object-origin.html
# https://blenderartists.org/t/how-to-set-origin-to-center/687111
# https://blenderartists.org/t/modifying-object-origin-with-python/507305/3
# https://blender.stackexchange.com/questions/414/how-to-use-bmesh-to-add-verts-faces-and-edges-to-existing-geometry
# https://devtalk.blender.org/t/bmesh-adding-new-verts/11108/2
# f1 = Vector((rand(-5, 5),rand(-5, 5),rand(-5, 5)))
# f2 = Vector((rand(-5, 5),rand(-5, 5),rand(-5, 5)))
# f3 = Vector((rand(-5, 5),rand(-5, 5),rand(-5, 5)))
# f = [f1, f2, f3]
# for f in enumerate(faces):
#     this_vert = bm.verts.new(f)
# used_indexes = list(indexes.values())
# bigger = []
# smaller = []
# remaining = (collections.Counter(bigger) - collections.Counter(smaller)).elements()
# unused_indexes = list(remaining)
# print(list(indexes.values()))
# print(len(used_vertices))
# if index is not referenced in vertices. remove from vertices
# apply_materials
# len(faces) do not always match len(mesh.polygons)
# print(len(faces))
# print(len(mesh.polygons))
# if you validate here, the polygon count changes,
# which causes polygon count and geometry.face_info count to get out of sync, causing missing face colors
# mesh.validate()
# mesh.update(calc_edges=True)
# print(len(mesh.polygons))
# slower than bmesh.ops.remove_doubles but necessary if importing to a system without a remove doubles function
