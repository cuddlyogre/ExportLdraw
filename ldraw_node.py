import os
import bpy
import math
import mathutils
import bmesh

from . import strings
from . import options
from . import matrices
from . import blender_mesh
from . import special_bricks
from . import blender_materials
from . import ldraw_colors
from . import helpers

from .ldraw_geometry import LDrawGeometry
from .face_info import FaceInfo

part_count = 0
current_step = 0
last_frame = 0
geometry_cache = {}
top_collection = None
top_empty = None
gap_scale_empty = None
collection_id_map = {}
next_collection = None
end_next_collection = False


def reset_caches():
    global part_count
    global current_step
    global last_frame
    global geometry_cache
    global top_collection
    global top_empty
    global gap_scale_empty
    global collection_id_map
    global next_collection
    global end_next_collection

    part_count = 0
    current_step = 0
    last_frame = 0
    geometry_cache = {}
    top_collection = None
    top_empty = None
    gap_scale_empty = None
    collection_id_map = {}
    next_collection = None
    end_next_collection = False

    if options.meta_step:
        set_step()


def set_step():
    start_frame = options.starting_step_frame
    frame_length = options.frames_per_step
    global last_frame
    last_frame = (start_frame + frame_length) + (frame_length * current_step)
    if options.set_timelime_markers:
        bpy.context.scene.timeline_markers.new("STEP", frame=last_frame)


def create_meta_group(collection_name, parent_collection):
    if collection_name not in bpy.data.collections:
        bpy.data.collections.new(collection_name)
    collection = bpy.data.collections[collection_name]
    if parent_collection is None:
        parent_collection = bpy.context.scene.collection
    if collection.name not in parent_collection.children:
        parent_collection.children.link(collection)
    return collection


# obj.show_name = True
def do_create_object(mesh):
    if options.instancing:
        if mesh.name not in bpy.data.objects:
            bpy.data.objects.new(mesh.name, mesh)
        instanced_obj = bpy.data.objects[mesh.name]

        collection_name = 'Parts'
        if collection_name not in bpy.data.collections:
            parts_collection = bpy.data.collections.new(collection_name)
            bpy.context.scene.collection.children.link(parts_collection)
            parts_collection.hide_viewport = True
            parts_collection.hide_render = True
        parts_collection = bpy.data.collections[collection_name]

        collection_name = mesh.name
        if collection_name not in bpy.data.collections:
            part_collection = bpy.data.collections.new(collection_name)
            parts_collection.children.link(part_collection)
        part_collection = bpy.data.collections[collection_name]

        if instanced_obj.name not in part_collection.objects:
            part_collection.objects.link(instanced_obj)

        obj = bpy.data.objects.new(mesh.name, None)
        obj.instance_type = 'COLLECTION'
        obj.instance_collection = part_collection
    else:
        obj = bpy.data.objects.new(mesh.name, mesh)
    return obj


def process_object(obj, parent_matrix, matrix):
    if top_empty is None:
        set_object_matrix(obj, parent_matrix, matrix)
    else:
        set_parented_object_matrix(obj, parent_matrix, matrix)

    if options.meta_step:
        handle_meta_step(obj)

    if options.smooth_type == "edge_split":
        handle_edge_split(obj)

    if options.bevel_edges:
        handle_bevel_edges(obj)


def handle_bevel_edges(obj):
    bevel_modifier = obj.modifiers.new("Bevel", type='BEVEL')
    bevel_modifier.width = 0.10
    bevel_modifier.segments = 4
    bevel_modifier.profile = 0.5
    bevel_modifier.limit_method = "WEIGHT"
    bevel_modifier.use_clamp_overlap = True


def handle_edge_split(obj):
    edge_modifier = obj.modifiers.new("Edge Split", type='EDGE_SPLIT')
    edge_modifier.use_edge_angle = True
    edge_modifier.split_angle = math.radians(89.9)  # 1.56905 - 89.9 so 90 degrees and up are affected
    edge_modifier.use_edge_sharp = True


# https://docs.blender.org/api/current/bpy.types.bpy_struct.html#bpy.types.bpy_struct.keyframe_insert
# https://docs.blender.org/api/current/bpy.types.Scene.html?highlight=frame_set#bpy.types.Scene.frame_set
# https://docs.blender.org/api/current/bpy.types.Object.html?highlight=rotation_quaternion#bpy.types.Object.rotation_quaternion
def handle_meta_step(obj):
    bpy.context.scene.frame_set(options.starting_step_frame)
    obj.hide_viewport = True
    obj.hide_render = True
    obj.keyframe_insert(data_path="hide_render")
    obj.keyframe_insert(data_path="hide_viewport")
    bpy.context.scene.frame_set(last_frame)
    obj.hide_viewport = False
    obj.hide_render = False
    obj.keyframe_insert(data_path="hide_render")
    obj.keyframe_insert(data_path="hide_viewport")


def set_parented_object_matrix(obj, parent_matrix, matrix):
    matrix_world = matrices.identity @ matrices.rotation @ matrices.scaled_matrix(options.import_scale)
    top_empty.matrix_world[0] = matrix_world[0]
    top_empty.matrix_world[1] = matrix_world[1]
    top_empty.matrix_world[2] = matrix_world[2]
    top_empty.matrix_world[3] = matrix_world[3]
    matrix_world = parent_matrix @ matrix
    obj.matrix_world[0] = matrix_world[0]
    obj.matrix_world[1] = matrix_world[1]
    obj.matrix_world[2] = matrix_world[2]
    obj.matrix_world[3] = matrix_world[3]
    if options.make_gaps and options.gap_target == "object":
        if options.gap_scale_strategy == "object":
            matrix_world = matrices.mt4(obj.matrix_world) @ matrices.scaled_matrix(options.gap_scale)
            obj.matrix_world[0] = matrix_world[0]
            obj.matrix_world[1] = matrix_world[1]
            obj.matrix_world[2] = matrix_world[2]
            obj.matrix_world[3] = matrix_world[3]
        elif options.gap_scale_strategy == "constraint":
            global gap_scale_empty
            if gap_scale_empty is None and top_collection is not None:
                gap_scale_empty = bpy.data.objects.new("gap_scale", None)
                matrix_world = matrices.mt4(gap_scale_empty.matrix_world) @ matrices.scaled_matrix(options.gap_scale)
                gap_scale_empty.matrix_world[0] = matrix_world[0]
                gap_scale_empty.matrix_world[1] = matrix_world[1]
                gap_scale_empty.matrix_world[2] = matrix_world[2]
                gap_scale_empty.matrix_world[3] = matrix_world[3]
                top_collection.objects.link(gap_scale_empty)
            copy_constraint = obj.constraints.new("COPY_SCALE")
            copy_constraint.target = gap_scale_empty
            copy_constraint.target.parent = top_empty
    obj.parent = top_empty  # must be after matrix_world set or else transform is incorrect


def set_object_matrix(obj, parent_matrix, matrix):
    matrix_world = matrices.identity @ matrices.rotation @ matrices.scaled_matrix(options.import_scale)
    matrix_world = matrix_world @ parent_matrix @ matrix
    if options.make_gaps and options.gap_target == "object":
        matrix_world = matrix_world @ matrices.scaled_matrix(options.gap_scale)
    obj.matrix_world[0] = matrix_world[0]
    obj.matrix_world[1] = matrix_world[1]
    obj.matrix_world[2] = matrix_world[2]
    obj.matrix_world[3] = matrix_world[3]


class LDrawNode:
    def __init__(self, file, color_code="16", matrix=matrices.identity):
        self.file = file
        self.color_code = color_code
        self.matrix = matrix
        self.top = False
        self.meta_command = None
        self.meta_args = {}

    def load(self, parent_matrix=matrices.identity, parent_color_code="16", geometry=None, is_edge_logo=False, parent_collection=None):
        global part_count
        global current_step
        global top_collection
        global top_empty
        global next_collection
        global end_next_collection

        if self.file is None:
            if self.meta_command == "step":
                current_step += 1
                set_step()
            elif self.meta_command == "group_begin":
                create_meta_group(self.meta_args["name"], parent_collection)
                end_next_collection = False
                if self.meta_args["name"] in bpy.data.collections:
                    next_collection = bpy.data.collections[self.meta_args["name"]]
            elif self.meta_command == "group_end":
                end_next_collection = True
            elif self.meta_command == "group_def":
                if self.meta_args["id"] not in collection_id_map:
                    collection_id_map[self.meta_args["id"]] = self.meta_args["name"]
                create_meta_group(self.meta_args["name"], parent_collection)
            elif self.meta_command == "group_nxt":
                if self.meta_args["id"] in collection_id_map:
                    key = collection_id_map[self.meta_args["id"]]
                    if key in bpy.data.collections:
                        next_collection = bpy.data.collections[key]
                end_next_collection = True
            elif self.meta_command == "save":
                if options.set_timelime_markers:
                    bpy.context.scene.timeline_markers.new("SAVE", frame=last_frame)
            elif self.meta_command == "clear":
                if options.set_timelime_markers:
                    bpy.context.scene.timeline_markers.new("CLEAR", frame=last_frame)
                if top_collection is not None:
                    for ob in top_collection.all_objects:
                        bpy.context.scene.frame_set(last_frame)
                        ob.hide_viewport = True
                        ob.hide_render = True
                        ob.keyframe_insert(data_path="hide_render")
                        ob.keyframe_insert(data_path="hide_viewport")
            return

        if options.no_studs and self.file.is_like_stud():
            return

        if self.color_code != "16":
            parent_color_code = self.color_code

        key = []
        key.append(self.file.name)
        key.append(parent_color_code)
        if parent_color_code == "24":
            key.append("edge")
        key = "_".join([k.lower() for k in key])[0:63]

        is_model = self.file.is_like_model()
        is_shortcut = self.file.is_shortcut()
        is_part = self.file.is_part()
        is_subpart = self.file.is_subpart()

        matrix = parent_matrix @ self.matrix
        file_collection = parent_collection

        if is_model:
            collection_name = os.path.basename(self.file.name)
            file_collection = bpy.data.collections.new(collection_name)
            if parent_collection is not None:
                parent_collection.children.link(file_collection)

            if top_collection is None:
                top_collection = file_collection
                if options.parent_to_empty and top_empty is None:
                    top_empty = bpy.data.objects.new(top_collection.name, None)
                    if top_collection is not None:
                        top_collection.objects.link(top_empty)
        elif geometry is None:  # top-level part
            geometry = LDrawGeometry()
            matrix = matrices.identity
            self.top = True
            part_count += 1

        if options.meta_group and next_collection is not None:
            file_collection = next_collection
            if end_next_collection:
                next_collection = None

        if options.debug_text:
            print("===========")
            if is_model:
                print("is_model")
            if is_part:
                print("is_part")
            elif is_shortcut:
                print("is_shortcut")
            elif is_subpart:
                print("is_subpart")
            print(self.file.name)
            print("===========")

        # if it's a part and geometry already in the geometry_cache, reuse it
        # meta commands are not in self.top files which is how they are counted
        # missing minifig arms if "if key not in bpy.data.meshes:"
        if self.top and key in geometry_cache:
            geometry = geometry_cache[key]
        else:
            if geometry is not None:
                if self.file.is_edge_logo():
                    is_edge_logo = True

                geometry.face_data.append({
                    "matrix": matrix,
                    "parent_color_code": parent_color_code,
                    "face_vertices": self.file.geometry.face_vertices,
                    "face_infos": self.file.geometry.face_infos,
                })

                if (not is_edge_logo) or (is_edge_logo and options.display_logo):
                    for edge_vertices in self.file.geometry.edge_vertices:
                        _edge = []
                        for i, vertex in enumerate(edge_vertices):
                            tv = matrix @ vertex
                            _edge.append((tv[0], tv[1], tv[2]))
                        geometry.edge_vertices.append(_edge)

            for child_node in self.file.child_nodes:
                child_node.load(parent_matrix=matrix,
                                parent_color_code=parent_color_code,
                                geometry=geometry,
                                is_edge_logo=is_edge_logo,
                                parent_collection=file_collection)

            if self.top:
                geometry_cache[key] = geometry

        if self.top:
            if self.file.name.lower() in [x.lower() for x in ['LDCfgalt.ldr', 'LDConfig.ldr']]:
                print(self.file.name)
                colors = {}
                group_name = 'blank'
                for line in self.file.lines:
                    params = helpers.parse_line(line, 17)

                    if params is None:
                        continue

                    if params[0] == "0":
                        if line.startswith('0 // LDraw'):
                            group_name = line
                            colors[group_name] = []
                        elif params[1].lower() in ["!colour"]:
                            colors[group_name].append(ldraw_colors.parse_color(params))

                j = 0
                for collection_name, codes in colors.items():
                    collection = bpy.data.collections.new(collection_name)
                    bpy.context.scene.collection.children.link(collection)
                    for i, color_code in enumerate(codes):
                        bm = bmesh.new()

                        monkey = True
                        if monkey:
                            prefix = 'monkey'
                            bmesh.ops.create_monkey(bm)
                        else:
                            prefix = 'cube'
                            bmesh.ops.create_cube(bm, size=1.0)

                        for f in bm.faces:
                            f.smooth = True

                        mesh = bpy.data.meshes.new(f"{prefix}_{str(color_code)}")
                        mesh[strings.ldraw_color_code_key] = str(color_code)

                        color = ldraw_colors.get_color(color_code)
                        material = blender_materials.get_material(color)
                        if material is not None:
                            # https://blender.stackexchange.com/questions/23905/select-faces-depending-on-material
                            if material.name not in mesh.materials:
                                mesh.materials.append(material)
                            for face in bm.faces:
                                face.material_index = mesh.materials.find(material.name)

                        bm.faces.ensure_lookup_table()
                        bm.verts.ensure_lookup_table()
                        bm.edges.ensure_lookup_table()

                        bm.to_mesh(mesh)
                        bm.clear()
                        bm.free()

                        mesh.validate()
                        mesh.update(calc_edges=True)
                        obj = bpy.data.objects.new(mesh.name, mesh)
                        obj.modifiers.new("Subdivision", type='SUBSURF')
                        obj.location.x = i * 3
                        obj.location.y = -j * 3
                        # obj.rotation_euler.z = math.radians(90)
                        collection.objects.link(obj)
                    j += 1
                print(colors)
                return

            if key not in bpy.data.meshes:
                bm = bmesh.new()

                mesh = bpy.data.meshes.new(key)
                mesh.name = key
                mesh[strings.ldraw_filename_key] = self.file.name

                if options.bevel_edges:
                    mesh.use_customdata_edge_bevel = True

                if options.smooth_type == "auto_smooth":
                    mesh.use_auto_smooth = options.shade_smooth
                    auto_smooth_angle = 89.9  # 1.56905 - 89.9 so 90 degrees and up are affected
                    auto_smooth_angle = 51.1
                    mesh.auto_smooth_angle = math.radians(auto_smooth_angle)

                if options.make_gaps and options.gap_target == "mesh":
                    mesh.transform(matrices.scaled_matrix(options.gap_scale))

                for data in geometry.face_data:
                    matrix = data["matrix"]
                    parent_color_code = data["parent_color_code"]
                    face_vertices = data["face_vertices"]
                    face_infos = data["face_infos"]

                    for i, fv in enumerate(face_vertices):
                        face = self.build_bm_face(bm, fv, matrix)
                        face_info = self.build_face_info(face_infos[i], parent_color_code)
                        self.process_face(bm, mesh, face, face_info)

                bm.faces.ensure_lookup_table()
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()

                if options.remove_doubles:
                    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=options.merge_distance)

                if options.recalculate_normals:
                    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

                if options.sharpen_edges:
                    self.process_edges(bm, geometry)

                bm.to_mesh(mesh)
                bm.clear()
                bm.free()

                mesh.validate()
                mesh.update(calc_edges=True)
            mesh = bpy.data.meshes[key]

            obj = do_create_object(mesh)
            process_object(obj, parent_matrix, self.matrix)
            obj[strings.ldraw_filename_key] = self.file.name

            # https://b3d.interplanety.org/en/how-to-get-global-vertex-coordinates/

            if file_collection is not None:
                file_collection.objects.link(obj)
            else:
                bpy.context.scene.collection.objects.link(obj)

            if options.import_edges:
                edge_mesh = blender_mesh.get_edge_mesh(key, self.file.name, geometry)

                obj = do_create_object(edge_mesh)
                process_object(obj, parent_matrix, self.matrix)
                obj[strings.ldraw_filename_key] = f"{self.file.name}_edges"

                if file_collection is not None:
                    file_collection.objects.link(obj)
                else:
                    bpy.context.scene.collection.objects.link(obj)

                if options.grease_pencil_edges:
                    gp_mesh = blender_mesh.get_gp_mesh(key, edge_mesh)

                    gp_object = bpy.data.objects.new(key, gp_mesh)
                    process_object(gp_object, parent_matrix, self.matrix)
                    gp_object.active_material_index = len(gp_mesh.materials)

                    collection_name = "Grease Pencil Edges"
                    if collection_name not in bpy.data.collections:
                        collection = bpy.data.collections.new(collection_name)
                        bpy.context.scene.collection.children.link(collection)
                    collection = bpy.context.scene.collection.children[collection_name]
                    collection.objects.link(gp_object)

    def process_edges(self, bm, geometry):
        # Create kd tree for fast "find nearest points" calculation
        # https://docs.blender.org/api/blender_python_api_current/mathutils.kdtree.html
        kd = mathutils.kdtree.KDTree(len(bm.verts))
        for i, v in enumerate(bm.verts):
            kd.insert(v.co, i)
        kd.balance()
        # Create edge_indices dictionary, which is the list of edges as pairs of indices into our verts array
        edge_indices = set()
        for i, edge in enumerate(geometry.edge_vertices):
            distance = options.merge_distance * 2
            edges0 = [index for (co, index, dist) in kd.find_range(edge[0], distance)]
            edges1 = [index for (co, index, dist) in kd.find_range(edge[1], distance)]
            for e0 in edges0:
                for e1 in edges1:
                    edge_indices.add((e0, e1))
                    edge_indices.add((e1, e0))

        # merge line type 2 edges at a greater distance than mesh edges
        merge = set()
        # Find the appropriate mesh edges and make them sharp (i.e. not smooth)
        bevel_weight_layer = bm.edges.layers.bevel_weight.verify()
        for edge in bm.edges:
            v0 = edge.verts[0].index
            v1 = edge.verts[1].index
            if (v0, v1) in edge_indices:
                merge.add(edge.verts[0])
                merge.add(edge.verts[1])

                # Make edge sharp
                edge.smooth = False

                # Add bevel weight
                # https://blender.stackexchange.com/a/188003
                if bevel_weight_layer is not None:
                    bevel_wight = 1.0
                    edge[bevel_weight_layer] = bevel_wight
        bmesh.ops.remove_doubles(bm, verts=list(merge), dist=options.merge_distance * 2)

    def process_face(self, bm, mesh, face, face_info):
        face.smooth = options.shade_smooth
        color_code = face_info.color_code
        color = ldraw_colors.get_color(color_code)
        use_edge_color = face_info.use_edge_color
        texmap = face_info.texmap
        part_slopes = special_bricks.get_part_slopes(self.file.name)

        material = blender_materials.get_material(color, use_edge_color=use_edge_color, part_slopes=part_slopes, texmap=texmap)
        if material is not None:
            # https://blender.stackexchange.com/questions/23905/select-faces-depending-on-material
            if material.name not in mesh.materials:
                mesh.materials.append(material)
            face.material_index = mesh.materials.find(material.name)
        if texmap is not None:
            texmap.uv_unwrap_face(bm, face)

    def build_face_info(self, fi, parent_color_code):
        face_info = FaceInfo(color_code=parent_color_code)
        if parent_color_code == "24":
            face_info.use_edge_color = True
        if fi.color_code != "16":
            face_info.color_code = fi.color_code
        face_info.texmap = fi.texmap
        return face_info

    def build_bm_face(self, bm, fv, matrix):
        _face = []
        for vertex in fv:
            tv = matrix @ vertex
            _face.append(bm.verts.new((tv[0], tv[1], tv[2])))
        face = bm.faces.new(_face)
        return face
