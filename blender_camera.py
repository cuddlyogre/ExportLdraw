import bpy
import math

from . import matrices
from . import options


def look_at(obj, target_location, up_vector):
    # back vector is a vector pointing from the target to the camera
    back = matrices.Vector(list(obj.location)) - target_location
    back = matrices.normalize(back)

    # If our back and up vectors are very close to pointing the same way (or opposite), choose a different up_vector
    if abs(matrices.dot(back, up_vector)) > 0.9999:
        up_vector = matrices.Vector((0.0, 0.0, 1.0))
        if abs(matrices.dot(back, up_vector)) > 0.9999:
            up_vector = matrices.Vector((1.0, 0.0, 0.0))

    right = matrices.cross(up_vector, back)
    right = matrices.normalize(right)

    up = matrices.cross(back, right)
    up = matrices.normalize(up)

    row1 = [right[0], up[0], back[0], obj.location[0]]
    row2 = [right[1], up[1], back[1], obj.location[1]]
    row3 = [right[2], up[2], back[2], obj.location[2]]
    row4 = [0.0, 0.0, 0.0, 1.0]

    matrix_world = matrices.Matrix((
        row1,
        row2,
        row3,
        row4
    ))
    obj.matrix_world[0] = matrix_world[0]
    obj.matrix_world[1] = matrix_world[1]
    obj.matrix_world[2] = matrix_world[2]
    obj.matrix_world[3] = matrix_world[3]


def create_camera(camera, empty=None, collection=None):
    blender_camera = bpy.data.cameras.new(camera.name)

    blender_camera.sensor_fit = "VERTICAL"
    # camera.sensor_height = self.fov
    blender_camera.lens_unit = "FOV"
    blender_camera.angle = math.radians(camera.fov)  # self.fov * 3.1415926 / 180.0
    blender_camera.clip_start = camera.z_near
    blender_camera.clip_end = camera.z_far

    blender_camera.clip_start = blender_camera.clip_start * options.import_scale
    blender_camera.clip_end = blender_camera.clip_end * options.import_scale

    camera.position[0] = camera.position[0] * options.import_scale
    camera.position[1] = camera.position[1] * options.import_scale
    camera.position[2] = camera.position[2] * options.import_scale

    camera.target_position[0] = camera.target_position[0] * options.import_scale
    camera.target_position[1] = camera.target_position[1] * options.import_scale
    camera.target_position[2] = camera.target_position[2] * options.import_scale

    camera.up_vector[0] = camera.up_vector[0] * options.import_scale
    camera.up_vector[1] = camera.up_vector[1] * options.import_scale
    camera.up_vector[2] = camera.up_vector[2] * options.import_scale

    if camera.orthographic:
        distance = camera.position - camera.target_position
        dist_target_to_camera = matrices.length(distance)
        blender_camera.ortho_scale = dist_target_to_camera / 1.92
        blender_camera.type = "ORTHO"
    else:
        blender_camera.type = "PERSP"

    obj = bpy.data.objects.new(camera.name, blender_camera)
    obj.name = camera.name
    obj.location = camera.position
    obj.hide_viewport = camera.hidden
    obj.hide_render = camera.hidden

    if collection is None:
        collection = bpy.context.scene.collection
    if obj.name not in collection:
        collection.objects.link(obj)

    # https://blender.stackexchange.com/a/72899
    # https://blender.stackexchange.com/a/154926
    # https://blender.stackexchange.com/a/29148
    # https://docs.blender.org/api/current/info_gotcha.html#stale-data
    # https://blenderartists.org/t/how-to-avoid-bpy-context-scene-update/579222/6
    # https://blenderartists.org/t/where-do-matrix-changes-get-stored-before-view-layer-update/1182838
    # when parenting the location of the parented obj is affected by the transform of the empty
    # this undoes the transform of the empty
    obj.parent = empty
    bpy.context.view_layer.update()
    if obj.parent is not None:
        obj.matrix_parent_inverse = obj.parent.matrix_world.inverted()

    look_at(obj, camera.target_position, camera.up_vector)

    return obj
