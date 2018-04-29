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
    "version": (0, 0, 6),
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
                if self.settings.use_bump_to_normal:
                    suffix = self.settings.suffix_normal
                else:
                    suffix = self.settings.suffix_bump                
            elif connected_node.type == 'NORMAL_MAP':
                suffix = self.settings.suffix_normal
        elif input_name == 'Clearcoat Normal':
            if connected_node.type == 'BUMP':
                if self.settings.use_bump_to_normal:
                    suffix = '_Clearcoat' + self.settings.suffix_normal
                else:
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
    
    def set_image_nodes_color_space_to_color(self, material):
        for node in material.node_tree.nodes:
            if node.type == 'TEX_IMAGE':
                node.color_space = 'COLOR'

    def set_image_nodes_color_space_to_noncolor(self, material):
        for node in material.node_tree.nodes:
            if node.type == 'TEX_IMAGE':
                node.color_space = 'NONE'

        
    def execute(self, context):
        scene = context.scene
        self.settings = context.scene.principled_baker
        obj = context.active_object
        active_mat = obj.active_material
        
        # vars for relocating nodes
        node_offset_x = 600
        node_offset_y = 260
        
        # no baking without UV Map
        if not len(obj.data.uv_textures.keys()) > 0:
            self.report({'ERROR'}, 'UV Map missing')
            return {'CANCELLED'}
        
        # get source material
        if 'p_baker_source_material' in active_mat.keys():
            mat_name = active_mat['p_baker_source_material']
            mat = bpy.data.materials[mat_name]
        else:
            mat = active_mat
            
        # find Material Output node
        for node in mat.node_tree.nodes:
            if node.type == 'OUTPUT_MATERIAL':
                materialoutput_node = node
                break
        else:
            # no baking if Material Output missing
            self.report({'ERROR'}, 'Material Output missing')
            return {'CANCELLED'}

        # get Material Output Surface links for later clean up
        socked_to_materialoutput_node_surface = None
        socked_to_materialoutput_node_displacement = None
        if materialoutput_node.inputs['Surface'].is_linked:
            socked_to_materialoutput_node_surface = materialoutput_node.inputs['Surface'].links[0].from_socket
        if materialoutput_node.inputs['Displacement'].is_linked:            
            socked_to_materialoutput_node_displacement = materialoutput_node.inputs['Displacement'].links[0].from_socket
        
        # get all non-color data image nodes for later clean up and color space to color
        noncolor_image_nodes = []
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE':
                if node.color_space == 'NONE':
                    noncolor_image_nodes.append(node)
                    node.color_space = 'COLOR'
                    
        # get principled_node
        if materialoutput_node.inputs['Surface'].is_linked:
            if materialoutput_node.inputs['Surface'].links[0].from_node.type == 'BSDF_PRINCIPLED':
                principled_node = materialoutput_node.inputs['Surface'].links[0].from_node
        else:
            for node in mat.node_tree.nodes:
                if node.type == 'BSDF_PRINCIPLED':
                    principled_node = node
                    break
            else:
                self.report({'ERROR'}, 'Principled BSDF missing in {0}'.format(mat.name))
                return {'CANCELLED'}  
        
        # new Material
        if self.settings.use_new_material:
            for m in obj.data.materials:
                if 'p_baker_source_material' in m.keys():
                    new_mat = m
                    for node in new_mat.node_tree.nodes:
                        if node.type == 'BSDF_PRINCIPLED':
                            new_principled_node = node
                            break
                    else:
                        # Principled BSDF missing: create and link new
                        new_principled_node = new_mat.node_tree.nodes.new(type='ShaderNodeBsdfPrincipled')
                        new_link = new_mat.node_tree.links.new(new_principled_node.outputs['BSDF'], new_mat.node_tree.nodes['Material Output'].inputs['Surface'])
                    break
            else:
                # create new material
                new_mat_name = "{0} {1}".format('Principled Baker', mat.name)
                new_mat = bpy.data.materials.new(new_mat_name)
                new_mat.use_nodes = True
                new_mat.node_tree.nodes.remove(new_mat.node_tree.nodes['Diffuse BSDF'])
                
                new_principled_node = new_mat.node_tree.nodes.new(type='ShaderNodeBsdfPrincipled')
                # link new_principled_node to Material Output
                new_link = new_mat.node_tree.links.new(new_principled_node.outputs['BSDF'], new_mat.node_tree.nodes['Material Output'].inputs['Surface'])
                # properties
                new_mat['p_baker_source_material'] = mat.name
                obj.data.materials.append(new_mat)
            # copy values
            if self.settings.use_copy_default_values:
                for v in principled_node.inputs:
                    new_principled_node.inputs[v.name].default_value = v.default_value

            
        # create pb_emitter or use existing
        pb_emitter_name = bl_info["name"] + ' Emission'
        if pb_emitter_name in mat.node_tree.nodes:
            pb_emitter = mat.node_tree.nodes[pb_emitter_name]
        else:
            pb_emitter = mat.node_tree.nodes.new(type='ShaderNodeEmission')
            pb_emitter.name = pb_emitter_name
            pb_emitter.label = pb_emitter_name
            pb_emitter.location = materialoutput_node.location.x, materialoutput_node.location.y + 200
            
        # temporary link PB Emitter to Material Output Surface
        pb_emitter_to_surface_link = mat.node_tree.links.new(pb_emitter.outputs['Emission'], materialoutput_node.inputs['Surface'])
        
        i = 0 # for relocating
        
        for input_socket in principled_node.inputs:
            if input_socket.is_linked:
                suffix = self.get_image_suffix(input_socket)
                prefix = self.settings.prefix if not self.settings.prefix == "" else mat.name
                image_file_format = image_file_format_endings[self.settings.file_format]
                image_name = "{0}{1}".format(prefix, suffix)
                image_file_name = "{0}.{1}".format(image_name, image_file_format)
                image_file_path = os.path.join(
                                    os.path.dirname(bpy.data.filepath), 
                                    self.settings.file_path.lstrip("/"), 
                                    image_file_name)

                # bake only if necessary: if overwrite or if file not exists
                if self.settings.use_overwrite or not os.path.isfile(image_file_path):
                        
                    if image_file_name in bpy.data.images.keys() and os.path.isfile(image_file_path):
                        image = bpy.data.images[image_file_name]
                        # rescale
                        if not image.size[0] == self.settings.resolution:
                            image.scale(self.settings.resolution, self.settings.resolution)
                    else:
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

                    if self.settings.use_new_material:
                        # create new image node or use exixting
                        image_node_name = "{0} {1}".format(bl_info["name"], image_file_name)
                        if image_node_name in new_mat.node_tree.nodes:
                            image_node = new_mat.node_tree.nodes[image_node_name]
                        else:
                            image_node = new_mat.node_tree.nodes.new(type="ShaderNodeTexImage")
                            image_node.color_space = 'COLOR' if input_socket.type == 'RGBA' else 'NONE'
                            image_node.name = image_node_name
                            image_node.label = image_node_name    
                            image_node.width = 300                            
                            # relocate image_node
                            image_node.location.x = new_principled_node.location.x - node_offset_x
                            image_node.location.y = new_principled_node.location.y - i * node_offset_y
                        
                        # add image to image_node
                        image_node.image = image
                        
                        # link image_node to new_principled_node
                        input_name = input_socket.name
                        connected_node = input_socket.links[0].from_node
                        if input_name == 'Normal' or input_name == 'Clearcoat Normal':
                            # check if bump/normal node is there or create new
                            if image_node.outputs['Color'].is_linked:
                                bump_normal_node = image_node.outputs['Color'].links[0].to_node
                            else:
                                if connected_node.type == 'BUMP':
                                    if self.settings.use_bump_to_normal:
                                        bump_normal_node = new_mat.node_tree.nodes.new(type="ShaderNodeNormalMap")
                                        new_mat.node_tree.links.new(image_node.outputs['Color'], bump_normal_node.inputs['Color'])
                                    else:
                                        bump_normal_node = new_mat.node_tree.nodes.new(type="ShaderNodeBump")
                                        new_mat.node_tree.links.new(image_node.outputs['Color'], bump_normal_node.inputs['Height'])
                                elif connected_node.type == 'NORMAL_MAP':
                                    bump_normal_node = new_mat.node_tree.nodes.new(type="ShaderNodeNormalMap")
                                    new_mat.node_tree.links.new(image_node.outputs['Color'], bump_normal_node.inputs['Color'])
                                new_mat.node_tree.links.new(bump_normal_node.outputs['Normal'], new_principled_node.inputs[input_socket.name])
                                # relocate image_node
                                bump_normal_node.location.x = image_node.location.x + 350
                                bump_normal_node.location.y = image_node.location.y
                            # link bump/normal node to Principled Baker BSDF
                            new_mat.node_tree.links.new(bump_normal_node.outputs['Normal'], new_principled_node.inputs[input_socket.name])
                        else:
                            new_mat.node_tree.links.new(image_node.outputs['Color'], new_principled_node.inputs[input_socket.name])
                        
                        i = i + 1 # for relocating
                        
                    
                    # deselect all nodes of type texture image
                    for node in mat.node_tree.nodes:
                        if node.type == 'TEX_IMAGE':
                            node.select = False
                            mat.node_tree.nodes.active = node
                                           
                    # temp bake node
                    bake_image_node = mat.node_tree.nodes.new(type="ShaderNodeTexImage")
                    bake_image_node.image = image
                    
                    # select image node to bake on
                    bake_image_node.select = True
                    mat.node_tree.nodes.active = bake_image_node

                    # temp link to Material Output Displacement or pb_emitter
                    socket_to_pb_emitter = self.get_linked_socket(input_socket)
                    if self.settings.use_bump_to_normal and input_socket.links[0].from_node.type == 'BUMP':
                        # temp set all image nodes to non-color data
                        self.set_image_nodes_color_space_to_noncolor(mat)
                        temp_link = mat.node_tree.links.new(socket_to_pb_emitter, materialoutput_node.inputs['Displacement'])
                        # bake to normal and save image
                        self.report({'INFO'}, "baking... {0}".format(image.name))
                        bpy.ops.object.bake(type='NORMAL', margin=self.settings.margin, use_clear=self.settings.use_clear)
                        image.save()
                    else:
                        # temp set all image nodes to color
                        self.set_image_nodes_color_space_to_color(mat)
                        temp_link = mat.node_tree.links.new(socket_to_pb_emitter, pb_emitter.inputs['Color'])
                        # bake and save image
                        self.report({'INFO'}, "baking... {0}".format(image.name))
                        bpy.ops.object.bake(type='EMIT', margin=self.settings.margin, use_clear=self.settings.use_clear)
                        image.save()
                        
                    # clean up
                    mat.node_tree.nodes.remove(bake_image_node)
                    mat.node_tree.links.remove(temp_link)
                    
                else:
                    self.report({'INFO'}, "baking skipped. file exists: {0}".format(image_file_path))
            
        ### END of for loop ###
        
        ### clean up! ###
        mat.node_tree.nodes.remove(pb_emitter)

        # set all image nodes back
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE':
                if node in noncolor_image_nodes:
                    node.color_space = 'NONE'
                else:
                    node.color_space = 'COLOR'        
            
        if not socked_to_materialoutput_node_surface == None:
            mat.node_tree.links.new(socked_to_materialoutput_node_surface, materialoutput_node.inputs['Surface'])
        if not socked_to_materialoutput_node_displacement == None:
            mat.node_tree.links.new(socked_to_materialoutput_node_displacement, materialoutput_node.inputs['Displacement'])
            
        principled_node.select = True
        mat.node_tree.nodes.active = principled_node
        
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

    use_new_material = BoolProperty(
        name="New Material",
        default = False
        )

    use_copy_default_values = BoolProperty(
        name="Copy values",
        description="Copy default values from Principled BSDF node",
        default = True
        )
        
    use_bump_to_normal = BoolProperty(
        name="bump to normal",
        description="bake bump map as normal map",
        default = False
        )

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
    #bl_context = "objectmode"
	
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
        layout.prop(pbaker, "use_bump_to_normal")
        layout.prop(pbaker, "use_new_material")
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