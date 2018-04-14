#    Principled Baker
#    Copyright (C) 2018 Daniel Engler

#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.

#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

bl_info = {
    "name": "Principled Baker",
    "description": "bakes all inputs of a Principled BSDF with link to image textures",
    "author": "Daniel Engler",
    "version": (0, 0, 3),
    "blender": (2, 79, 0),
    "location": "Node Editor Toolbar",
    "category": "Node",
}
    
import bpy
import os
import pathlib

from bpy.props import (StringProperty,
                       BoolProperty,
                       IntProperty,
                       #FloatProperty,
                       #FloatVectorProperty,
                       EnumProperty,
                       PointerProperty,
                       )
from bpy.types import (Panel,
                       Operator,
                       PropertyGroup,
                       )

image_file_format_endings = {
    "BMP":"bmp",
    "PNG":"png",
    "JPEG":"jpg",
    "TIFF":"tif",
    "TARGA":"tga",
}
# ------------------------------------------------------------------------
#    operators
# ------------------------------------------------------------------------

class PrincipledBakerOperator(bpy.types.Operator):
    bl_idname = "wm.principledbaker"
    bl_label = "Bake"

    settings = None
    
    def get_image_suffix(self, input_socket):
        input_name = input_socket.name
        connected_node = input_socket.links[0].from_node
        suffix = ""
        if input_name == 'Normal':
            if connected_node.type == 'BUMP':
                suffix = self.settings.suffix_bump
            elif connected_node.type == 'NORMAL_MAP':
                suffix = self.settings.suffix_normal
        elif input_name == 'Clearcoat Normal':
            if connected_node.type == 'BUMP':
                suffix = '_Clearcoat' + self.settings.suffix_bump
            elif connected_node.type == 'NORMAL_MAP':
                suffix = '_Clearcoat' + self.settings.suffix_normal
        else:
            if input_name == 'Base Color':
                suffix = self.settings.suffix_base_color
            elif input_name == 'Metallic':
                suffix = self.settings.suffix_metallic
            elif input_name == 'Roughness':
                suffix = self.settings.suffix_roughness
            else:
                suffix = '_' + input_name        
        return suffix
    
    def get_linked_socket(self, input_socket):
        input_name = input_socket.name
        connected_node = input_socket.links[0].from_node
        if input_name == 'Normal' or input_name == 'Clearcoat Normal':
            if connected_node.type == 'BUMP':
                if connected_node.inputs['Height'].is_linked:
                    socket = connected_node.inputs['Height'].links[0].from_socket
                else:
                    self.report({'WARNING'}, "ERROR: {0} has no Height input! Baking skipped.".format(connected_node.name))
            elif connected_node.type == 'NORMAL_MAP':
                if connected_node.inputs['Color'].is_linked:
                    socket = connected_node.inputs['Color'].links[0].from_socket
                else:
                    self.report({'WARNING'}, "ERROR: {0} has no Color input! Baking skipped.".format(connected_node.name))
        else:
            socket = input_socket.links[0].from_socket
        return socket
    
    def execute(self, context):
        scene = context.scene
        self.settings = context.scene.principled_baker
        obj = context.active_object
        mat = context.active_object.active_material
        mat_nodes = mat.node_tree.nodes
        
        # Principled BSDF for baked textures
        p_baker_bsdf_name = 'Principled Baker BSDF'
        p_baker_bsdf = None
                
        materialoutput_node = None
        principled_node = None
        pb_emitter = None
        
        # vars for relocating nodes
        i = 0
        node_offset_x = 600
        node_offset_y = 260
        
        # find Material Output node
        for node in mat_nodes:
            if node.type == 'OUTPUT_MATERIAL':
                materialoutput_node = node
                
        # no baking if Material Output missing
        if materialoutput_node == None:
            self.report({'ERROR'}, 'Material Output missing')
            return {'CANCELLED'}
                
        # p_baker_node property
        if 'p_baker_node' not in mat.keys():
            mat['p_baker_node'] = 'Principled Baker BSDF'
        
        # p_baker_source property and find principled_node
        if 'p_baker_source' not in mat.keys():
            if mat_nodes.active.type == 'BSDF_PRINCIPLED' and not mat_nodes.active.name == mat['p_baker_node']:
                principled_node = mat_nodes.active
            else:
                for node in mat_nodes:
                    if node.type == 'BSDF_PRINCIPLED' and not node.name == mat['p_baker_node']:
                        principled_node = node
            mat['p_baker_source'] = principled_node.name
        else:
            principled_node = mat_nodes[ mat['p_baker_source'] ]
        
        # no baking if Principled BSDF missing
        if principled_node == None:
            self.report({'ERROR'}, 'Principled BSDF missing')
            return {'CANCELLED'}

        # use existing or create new Principled Baker BSDF node
        if self.settings.use_p_baker_node:
            if mat['p_baker_node'] in mat_nodes.keys():
                p_baker_node = mat_nodes[mat['p_baker_node']]
            else:
                p_baker_node = mat.node_tree.nodes.new(type='ShaderNodeBsdfPrincipled')
                p_baker_node.name = mat['p_baker_node']
                p_baker_node.label = mat['p_baker_node']
                p_baker_node.width = principled_node.width
                # copy values from principled_node
                if self.settings.use_copy_default_values:
                    for v in principled_node.inputs:
                        p_baker_node.inputs[v.name].default_value = v.default_value        
                # relocate p_baker_node relative to principled_node
                p_baker_node.location = principled_node.location.x, principled_node.location.y - node_offset_x
        
        # get Material Output Surface link for later clean up
        materialoutput_node_has_link = False
        if materialoutput_node.inputs['Surface'].is_linked:
            materialoutput_node_has_link = True
            socked_to_materialoutput_node_surface = materialoutput_node.inputs['Surface'].links[0].from_socket

        
        # create pb_emitter or use existing
        pb_emitter_name = bl_info["name"] + ' Emission'
        if mat_nodes.find(pb_emitter_name) == -1:
            self.pb_emitter = mat.node_tree.nodes.new(type='ShaderNodeEmission')
            self.pb_emitter.name = pb_emitter_name
            self.pb_emitter.label = pb_emitter_name
            self.pb_emitter.location = materialoutput_node.location.x, materialoutput_node.location.y + 200
        else:
            self.pb_emitter = mat_nodes[pb_emitter_name]
        # temporary link PB Emitter to Material Output Surface
        pb_emitter_to_surface_link = mat.node_tree.links.new(self.pb_emitter.outputs['Emission'], materialoutput_node.inputs['Surface'])

        
        # go through all inputs of Principled BSDF
        for input_socket in principled_node.inputs:
            # bake only inputs with link
            if input_socket.is_linked:
                suffix = self.get_image_suffix(input_socket)
                prefix = self.settings.prefix if not self.settings.prefix == "" else mat.name
                #image_file_format = self.settings.file_format.lower()
                image_file_format = image_file_format_endings[self.settings.file_format]
                image_name = "{0}{1}".format(prefix, suffix)
                image_file_name = "{0}.{1}".format(image_name, image_file_format)
                image_file_path = os.path.join(
                                    os.path.dirname(bpy.data.filepath), 
                                    self.settings.file_path.lstrip("/"), 
                                    image_file_name)
                # bake only if necessary: if overwrite or if file not exists
                if self.settings.use_overwrite or not os.path.isfile(image_file_path):
#                    if bpy.data.images.find(image_name) == -1:
#                        try:
#                            bpy.data.images.remove(bpy.data.images[image_name])
#                        except:
#                            pass
#                        image = bpy.data.images.new(
#                                    image_name, 
#                                    width=self.settings.resolution, 
#                                    height=self.settings.resolution)
                    if bpy.data.images.find(image_file_name) == -1:
                        try:
                            bpy.data.images.remove(bpy.data.images[image_file_name])
                        except:
                            pass
                        image = bpy.data.images.new(
                                    image_file_name, 
                                    width=self.settings.resolution, 
                                    height=self.settings.resolution)

                        image.filepath_raw = image_file_path
                        image.file_format = self.settings.file_format
                    else:
                        image = bpy.data.images[image_file_name]
                    
                    # get socket to emitter and link to emitter
                    socket_to_pb_emitter = self.get_linked_socket(input_socket)
                    link = mat.node_tree.links.new(socket_to_pb_emitter, self.pb_emitter.inputs['Color'] )
                    
                    # create new image texture node or use exixting
                    image_node_name = "{0} {1}".format(bl_info["name"], image_file_name)#image_name)
                    if mat_nodes.find(image_node_name) == -1:
                        image_node = mat.node_tree.nodes.new(type="ShaderNodeTexImage")
                        image_node.color_space = 'COLOR' if input_socket.type == 'RGBA' else 'NONE'
                        image_node.name = image_node_name
                        image_node.label = image_node_name    
                        image_node.width = 300
                        image_node.image = image
                        # relocate image_node
                        if self.settings.use_p_baker_node:
                            image_node.location.x = p_baker_node.location.x - node_offset_x
                            image_node.location.y = p_baker_node.location.y - i * node_offset_y
                        else:
                            image_node.location.x = principled_node.location.x - node_offset_x
                            image_node.location.y = principled_node.location.y - node_offset_x - i * node_offset_y
                    else:
                        image_node = mat_nodes[image_node_name]
                        
                    i = i + 1 # for relocating
                    
                    # deselect all nodes of type texture image
                    for node in mat_nodes:
                        if node.type == 'TEX_IMAGE':
                            node.select = False
                            mat_nodes.active = node
                    
                    # select image node to bake on
                    image_node.select = True
                    mat_nodes.active = image_node

                    # bake
                    self.report({'INFO'}, "baking... {0}".format(image.name))
                    bpy.ops.object.bake(type='EMIT', margin=self.settings.margin, use_clear=self.settings.use_clear)
                    
                    # save
                    image.save()
                    
                    # link new image to p_baker_node
                    if self.settings.use_p_baker_node:
                        input_name = input_socket.name
                        connected_node = input_socket.links[0].from_node
                        if input_name == 'Normal' or input_name == 'Clearcoat Normal':
                            # check if bump/normal node is there or create new
                            if image_node.outputs['Color'].is_linked:
                                bump_normal_node = image_node.outputs['Color'].links[0].to_node
                            else:
                                if connected_node.type == 'BUMP':
                                    bump_normal_node = mat.node_tree.nodes.new(type="ShaderNodeBump")
                                    mat.node_tree.links.new(image_node.outputs['Color'], bump_normal_node.inputs['Height'])
                                elif connected_node.type == 'NORMAL_MAP':
                                    bump_normal_node = mat.node_tree.nodes.new(type="ShaderNodeNormalMap")
                                    mat.node_tree.links.new(image_node.outputs['Color'], bump_normal_node.inputs['Color'])
                                mat.node_tree.links.new(bump_normal_node.outputs['Normal'], p_baker_node.inputs[input_socket.name])
                                # relocate image_node
                                bump_normal_node.location.x = image_node.location.x + 350
                                bump_normal_node.location.y = image_node.location.y
                            # link bump/normal node to Principled Baker BSDF
                            mat.node_tree.links.new(bump_normal_node.outputs['Normal'], p_baker_node.inputs[input_socket.name])
                        else:
                            mat.node_tree.links.new(image_node.outputs['Color'], p_baker_node.inputs[input_socket.name])
                else:
                    self.report({'INFO'}, " Baking skipped. {0} exists.".format(image_file_path))

        # clean up
        mat_nodes.remove(self.pb_emitter)
        if materialoutput_node_has_link:
            mat.node_tree.links.new(socked_to_materialoutput_node_surface, materialoutput_node.inputs['Surface'])
        
        return {'FINISHED'}


# ------------------------------------------------------------------------
#    properties
# ------------------------------------------------------------------------

class PBakerSettings(PropertyGroup):
    
    use_overwrite = BoolProperty(
        name="Overwrite",
        default = True
        )

    suffix_base_color = StringProperty(
        name="Base Color suffix",
        default="_color",
        maxlen=1024,
        )
    suffix_metallic = StringProperty(
        name="Metallic suffix",
        default="_metal",
        maxlen=1024,
        )
    suffix_roughness = StringProperty(
        name="Roughness suffix",
        default="_roughness",
        maxlen=1024,
        )
    suffix_normal = StringProperty(
        name="Normal suffix",
        default="_normal",
        maxlen=1024,
        )
    suffix_bump = StringProperty(
        name="Bump suffix",
        default="_bump",
        maxlen=1024,
        )
        
    prefix = StringProperty(
        name="Name",
        description="Texture Name. If empty, Texture will have name of Material",
        default="",
        maxlen=1024,
        )
    
    file_path = StringProperty(
        name="",
        description="Choose a directory:",
        default="//",
        maxlen=1024,
        subtype='DIR_PATH'
        )        
    resolution = IntProperty(
        name = "resolution",
        default = 2048,
        min = 1,
        #max = 16*1024
        )
    margin = IntProperty(
        name = "margin",
        default = 0,
        min = 0,
        max = 64
        )
    
    use_clear = BoolProperty(
        name="Clear",
        default = False
        )
        
    use_p_baker_node = BoolProperty(
        name="New Principled BSDF node",
        description="Create new Principled BSDF node and link baked Image Textures.\nExisting Principled BSDF node will not be touched",
        default = False
        )
    
    use_copy_default_values = BoolProperty(
        name="Copy values",
        description="Copy default values from Principled BSDF node",
        default = True
        )
        
#    file_format = StringProperty(
#        name="Format",
#        default="png",
#        maxlen=1024,
#        )
    file_format = EnumProperty(
        name="Format:",
        items=(
            ("PNG", "PNG", ""),
            ("BMP", "BMP", ""),
            ("JPEG", "JPEG", ""),
            ("TIFF", "TIFF", ""),
            ("TARGA", "TARGA", ""),
        ),
        default='PNG'
        )

# ------------------------------------------------------------------------
#    principledbaker in objectmode
# ------------------------------------------------------------------------

class OBJECT_PT_principledbaker_panel(Panel):
    bl_idname = "OBJECT_PT_principledbaker_panel"
    bl_space_type = 'NODE_EDITOR'
    bl_label = "Principled Baker"
    bl_region_type = "TOOLS"
    bl_category = "Principled Baker"
	
    @classmethod
    def poll(self,context):
        return context.object is not None

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        pbaker = scene.principled_baker

        layout.operator("wm.principledbaker", icon="SCENE")
        
        layout.prop(pbaker, "resolution")
        layout.prop(pbaker, "margin")
        layout.prop(pbaker, "use_clear")
        layout.prop(pbaker, "file_path")
        layout.prop(pbaker, "prefix")
        layout.prop(pbaker, "file_format", text="")
        layout.prop(pbaker, "use_overwrite")
        layout.label("Suffixes:")
        layout.prop(pbaker, "suffix_base_color")
        layout.prop(pbaker, "suffix_metallic")
        layout.prop(pbaker, "suffix_roughness")
        layout.prop(pbaker, "suffix_normal")
        layout.prop(pbaker, "suffix_bump")
        layout.prop(pbaker, "use_p_baker_node")
        layout.prop(pbaker, "use_copy_default_values")

# ------------------------------------------------------------------------
# register and unregister
# ------------------------------------------------------------------------

def register():
    bpy.utils.register_module(__name__)
    bpy.types.Scene.principled_baker = PointerProperty(type=PBakerSettings)

def unregister():
    bpy.utils.unregister_module(__name__)
    del bpy.types.Scene.principled_baker

if __name__ == "__main__":
    register()