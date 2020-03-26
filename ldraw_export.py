import bpy
import bmesh

from . import ldraw_file
from . import ldraw_colors
from . import filesystem
from . import matrices
from . import options
from . import helpers
from . import ldraw_part_types

remove_doubles = None
triangulate = None
recalculate_normals = None
selection_only = None
ngon_handling = None


# https://devtalk.blender.org/t/to-mesh-and-creating-new-object-issues/8557/4
# https://docs.blender.org/api/current/bpy.types.Depsgraph.html
def clean_mesh(obj):
    bm = bmesh.new()
    bm.from_object(obj, bpy.context.evaluated_depsgraph_get())

    bm.transform(matrices.reverse_rotation @ obj.matrix_world)

    if ngon_handling == "triangulate":
        faces = []
        for f in bm.faces:
            if len(f.verts) > 4:
                faces.append(f)
        bmesh.ops.triangulate(bm, faces=faces, quad_method='BEAUTY', ngon_method='BEAUTY')

    if remove_doubles:
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=options.merge_distance)

    mesh = obj.data.copy()
    bm.to_mesh(mesh)
    bm.clear()
    bm.free()
    return mesh


# https://stackoverflow.com/a/2440786
# https://www.ldraw.org/article/512.html#precision
def fix_round(number, places=3):
    x = round(number, places)
    value = ('%f' % x).rstrip('0').rstrip('.')

    # remove -0
    if value == "-0":
        value = "0"

    return value


# TODO: if obj["section_label"] then:
#  0 // f{obj["section_label"]}
def export_subfiles(obj, name, lines, is_model=False):
    color_code = "16"
    if len(obj.data.materials) > 0:
        material = obj.data.materials[0]
        if options.ldraw_color_code_key in material:
            color_code = material[options.ldraw_color_code_key]

        color = ldraw_colors.get_color(color_code)
        if color is not None:
            color_code = color["code"]

    precision = 3
    if options.ldraw_export_precision_key in obj:
        precision = obj[options.ldraw_export_precision_key]

    if is_model:
        aa = matrices.reverse_rotation @ obj.matrix_world

        a = fix_round(aa[0][0], precision)
        b = fix_round(aa[0][1], precision)
        c = fix_round(aa[0][2], precision)
        x = fix_round(aa[0][3], precision)

        d = fix_round(aa[1][0], precision)
        e = fix_round(aa[1][1], precision)
        f = fix_round(aa[1][2], precision)
        y = fix_round(aa[1][3], precision)

        g = fix_round(aa[2][0], precision)
        h = fix_round(aa[2][1], precision)
        i = fix_round(aa[2][2], precision)
        z = fix_round(aa[2][3], precision)

        line = f"1 {color_code} {x} {y} {z} {a} {b} {c} {d} {e} {f} {g} {h} {i} {name}"
    else:
        aa = obj.matrix_world

        a = fix_round(aa[0][0], precision)
        b = fix_round(aa[0][1], precision)
        c = fix_round(-aa[0][2], precision)
        x = fix_round(aa[0][3], precision)

        d = fix_round(aa[1][0], precision)
        e = fix_round(aa[1][1], precision)
        f = fix_round(-aa[1][2], precision)
        y = fix_round(aa[1][3], precision)

        g = fix_round(-aa[2][0], precision)
        h = fix_round(-aa[2][1], precision)
        i = fix_round(aa[2][2], precision)
        z = fix_round(-aa[2][3], precision)

        line = f"1 {color_code} {x} {z} {y} {a} {c} {b} {g} {i} {h} {d} {f} {e} {name}"
    lines.append(line)


def export_polygons(obj, lines):
    if not getattr(obj.data, 'polygons', None):
        return False

    # so objects that are not linked to the scene don't get exported
    # objects during a failed export would be such an object
    if obj.users < 1:
        return False

    mesh = clean_mesh(obj)

    precision = 3
    if options.ldraw_export_precision_key in obj:
        precision = obj[options.ldraw_export_precision_key]

    for p in mesh.polygons:
        length = len(p.vertices)
        line_type = None
        if length == 3:
            line_type = 3
        elif length == 4:
            line_type = 4

        if line_type is None:
            continue

        color_code = "16"
        if p.material_index + 1 <= len(mesh.materials):
            material = mesh.materials[p.material_index]
            if options.ldraw_color_code_key in material:
                color_code = material[options.ldraw_color_code_key]

        color = ldraw_colors.get_color(color_code)
        color_code = "16"
        if color is not None:
            color_code = color["code"]

        line = [str(line_type), str(color_code)]

        for v in p.vertices:
            for vv in mesh.vertices[v].co:
                line.append(fix_round(vv, precision))

        lines.append(line)

    # export edges
    for e in mesh.edges:
        if e.use_edge_sharp:
            line = ["2", "24"]
            for v in e.vertices:
                for vv in mesh.vertices[v].co:
                    line.append(fix_round(vv))

            lines.append(line)

    bpy.data.meshes.remove(mesh)

    return True


# objects in "Scene Collection > subfiles" will be output as line type 1
# objects marked sharp and with a bevel weight of 1.00 will be output as line type 2
# objects in "Scene Collection > polygons" will be output as line type 3 or 4, depending on their vertex count
# if ngons are triangulated, they will be line type 3, otherwise they won't be exported at all
# conditional lines, line type 5, aren't handled
def do_export(filepath):
    filesystem.build_search_paths()
    ldraw_file.read_color_table()

    all_objects = bpy.context.scene.objects
    selected = bpy.context.selected_objects
    active = bpy.context.view_layer.objects.active

    objects = all_objects
    if selection_only:
        objects = selected

    if options.ldraw_filename_key not in bpy.context.object:
        return
    header_text_name = bpy.context.object[options.ldraw_filename_key]

    if header_text_name not in bpy.data.texts:
        return

    lines = []
    part_type = None

    header_text = bpy.data.texts[header_text_name]

    for text_line in header_text.lines:
        lines.append(text_line.body)

        line = text_line.body

        params = helpers.parse_line(line, 14)

        if params is None:
            continue

        if params[0] == "0":
            if params[1].lower() in ["!ldraw_org"]:
                if params[2].lower() in ["lcad"]:
                    part_type = params[3].lower()
                else:
                    part_type = params[2].lower()

    is_model = part_type in ldraw_part_types.model_types

    part_lines = []
    for obj in objects:
        if obj.data is None:
            continue

        if options.ldraw_filename_key not in obj:
            continue
        name = obj[options.ldraw_filename_key]

        do_export_polygons = False
        if options.ldraw_export_polygons_key in obj:
            do_export_polygons = obj[options.ldraw_export_polygons_key] == 1

        if do_export_polygons:
            export_polygons(obj, part_lines)
        else:
            export_subfiles(obj, name, lines, is_model=is_model)

    part_lines = sorted(part_lines, key=lambda pl: (int(pl[1]), int(pl[0])))

    sorted_part_lines = []
    current_color_code = None
    for text_line in part_lines:
        if len(text_line) > 2:
            new_color_code = int(text_line[1])
            if new_color_code != current_color_code:
                current_color_code = new_color_code
                name = ldraw_colors.get_color(current_color_code)['name']
                sorted_part_lines.append("\n")
                sorted_part_lines.append(f"0 // {name}")
        sorted_part_lines.append(" ".join(text_line))
    lines.extend(sorted_part_lines)

    with open(filepath, 'w') as file:
        for i, text_line in enumerate(lines):
            # print(line)
            if text_line != "\n":
                file.write(text_line)
            file.write("\n")

    for obj in selected:
        if not obj.select_get():
            obj.select_set(True)

    bpy.context.view_layer.objects.active = active
