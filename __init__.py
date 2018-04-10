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
    "description": "bakes image textures of selected object",
    "author": "Daniel Engler",
    "version": (0, 0, 2),
    "blender": (2, 79, 0),
    "location": "3D View > Tools",
    "category": "Test"
}
    
import bpy
import os
import pathlib

from bpy.props import (StringProperty,
                       BoolProperty,
                       IntProperty,
                       #FloatProperty,
                       #FloatVectorProperty,
                       #EnumProperty,
                       PointerProperty,
                       )
from bpy.types import (Panel,
                       Operator,
                       PropertyGroup,
                       )

# ------------------------------------------------------------------------
#    operators
# ------------------------------------------------------------------------

class PrincipledBakerOperator(bpy.types.Operator):
    bl_idname = "wm.principledbaker"
    bl_label = "Bake"

    pbaker = None
    obj = None
    mat = None
    mat_nodes = None    
    pb_emitter = None
    materialoutput_node = None
    principled_node = None
    socket_to_pb_emitter = None
    
    def new_image(self, image_file_name, image_file_path):
        # if image to bake on does not exist: create new image, else use existing image
        if bpy.data.images.find(image_file_name) == -1:                
            img = bpy.data.images.new(image_file_name, width=self.pbaker.resolution, height=self.pbaker.resolution)
            img.filepath_raw = image_file_path
            img.file_format = self.pbaker.file_format.upper()
        else:
            img = bpy.data.images[image_file_name]
        return img
    
    
    def pb_bake(self, socket_to_pb_emitter, image):
        
        # link socket to temporary PB Emitter
        link = self.mat.node_tree.links.new(socket_to_pb_emitter, self.pb_emitter.inputs['Color'])
            
        # deselect all nodes of type texture image
        for node in self.mat_nodes:
            if node.type == 'TEX_IMAGE':
                node.select = False
                self.mat_nodes.active = node

        # create temporary image texture node or use existing
        pb_image_node_name = "PB_"+image.name
        if self.mat.node_tree.nodes.find(pb_image_node_name) == -1:
            image_node = self.mat.node_tree.nodes.new(type="ShaderNodeTexImage")
            image_node.color_space = 'COLOR'
            image_node.name = pb_image_node_name
            image_node.label = pb_image_node_name    
            image_node.width = 300
            image_node.location = self.materialoutput_node.location.x, self.materialoutput_node.location.y + 500        
        else:
            image_node = self.mat_nodes[pb_image_node_name]
            
        # make image node use of image to bake on
        image_node.image = image

        # select image node to bake on
        image_node.select = True
        self.mat_nodes.active = image_node
        
        # bake
        self.report({'INFO'}, "baking... {0}".format(image.name))
        bpy.ops.object.bake(type='EMIT', margin=self.pbaker.margin)


    def execute(self, context):
        scene = context.scene
        self.pbaker = scene.principled_baker
        
        self.obj = context.active_object
        self.mat = self.obj.material_slots[0].material
        self.mat_nodes = self.mat.node_tree.nodes
        
        # find Material Output node
        for node in self.mat.node_tree.inputs.data.nodes:
            if node.type == 'OUTPUT_MATERIAL':
                self.materialoutput_node = node

        # find Principled BSDF node
        for node in self.mat.node_tree.inputs.data.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                self.principled_node = node

        # no baking if Principled BSDF or Material Output missing
        if self.materialoutput_node == None:
            self.report({'ERROR'}, 'Material Output missing')
            return {'CANCELLED'}
        elif self.principled_node == None:
            self.report({'ERROR'}, 'Principled BSDF missing')
            return {'CANCELLED'}
        else:
            # create temporary Emitter node or use existing
            pb_emitter_name = bl_info["name"] + ' Emission'
            if self.mat.node_tree.nodes.find(pb_emitter_name) == -1:
                self.pb_emitter = self.mat.node_tree.nodes.new(type='ShaderNodeEmission')
                self.pb_emitter.name = pb_emitter_name
                self.pb_emitter.label = pb_emitter_name
                self.pb_emitter.location = self.materialoutput_node.location.x, self.materialoutput_node.location.y + 200
            else:
                self.pb_emitter = self.mat_nodes[pb_emitter_name]

            # get Material Output Surface link for later clean up
            materialoutput_node_has_link = False
            if self.materialoutput_node.inputs['Surface'].is_linked:
                materialoutput_node_has_link = True
                socked_to_materialoutput_node_surface = self.materialoutput_node.inputs['Surface'].links[0].from_socket
            
            # temporary link PB Emitter to Material Output Surface
            pb_emitter_to_surface_link = self.mat.node_tree.links.new(self.pb_emitter.outputs['Emission'], self.materialoutput_node.inputs['Surface'])

            for principled_node_input in self.principled_node.inputs:
                suffix = ""
                # bake if input of Principled BSDF has link
                if principled_node_input.is_linked:
                    if principled_node_input.name == "Normal":
                        if principled_node_input.links[0].from_node.type == 'NORMAL_MAP':
                            if principled_node_input.links[0].from_node.inputs['Color'].is_linked:
                                socket_to_pb_emitter = principled_node_input.links[0].from_node.inputs['Color'].links[0].from_socket                                
                                suffix = self.pbaker.suffix_normal
                            else:
                                self.report({'WARNING'}, "ERROR: {0} has no Color input! Baking skipped.".format(principled_node_input.links[0].from_node.name))
                        elif principled_node_input.links[0].from_node.type == 'BUMP':                            
                            if principled_node_input.links[0].from_node.inputs['Height'].is_linked:
                                socket_to_pb_emitter = principled_node_input.links[0].from_node.inputs['Height'].links[0].from_socket
                                suffix = self.pbaker.suffix_bump
                            else:
                                self.report({'WARNING'}, "{0} has no Height input! Baking skipped.".format(principled_node_input.links[0].from_node.name))
                    elif principled_node_input.name == "Clearcoat Normal":
                        if principled_node_input.links[0].from_node.type == 'NORMAL_MAP':
                            if principled_node_input.links[0].from_node.inputs['Color'].is_linked:
                                socket_to_pb_emitter = principled_node_input.links[0].from_node.inputs['Color'].links[0].from_socket                                
                                suffix = "_Clearcoat" + self.pbaker.suffix_normal
                            else:
                                self.report({'WARNING'}, "ERROR: {0} has no Color input! Baking skipped.".format(principled_node_input.links[0].from_node.name))
                        elif principled_node_input.links[0].from_node.type == 'BUMP':                            
                            if principled_node_input.links[0].from_node.inputs['Height'].is_linked:
                                socket_to_pb_emitter = principled_node_input.links[0].from_node.inputs['Height'].links[0].from_socket
                                suffix = "_Clearcoat" + self.pbaker.suffix_bump
                            else:
                                self.report({'WARNING'}, "{0} has no Height input! Baking skipped.".format(principled_node_input.links[0].from_node.name))
                    else:
                        socket_to_pb_emitter = principled_node_input.links[0].from_socket
                        if principled_node_input.name == "Base Color":                            
                            suffix = self.pbaker.suffix_base_color
                        elif principled_node_input.name == "Metallic":
                            suffix = self.pbaker.suffix_metallic
                        elif principled_node_input.name == "Roughness":
                            suffix = self.pbaker.suffix_roughness
                        else:
                            suffix = "_" + principled_node_input.name
                    if suffix == "":
                        suffix = "_" + principled_node_input.name
                    
                    # image to bake on
                    prefix = self.mat.name if self.pbaker.prefix == "" else self.pbaker.prefix
                    image_name = prefix + suffix
                    image_file_name = image_name + "." + self.pbaker.file_format
                    image_file_path = os.path.join(os.path.dirname(bpy.data.filepath), self.pbaker.file_path.lstrip("/"), image_file_name)
                    
                    # link socket to temporary PB Emitter
                    link = self.mat.node_tree.links.new(socket_to_pb_emitter, self.pb_emitter.inputs['Color'])

                    # overwrite?
                    if self.pbaker.use_overwrite:
                        try:
                            bpy.data.images.remove(bpy.data.images[image_file_name])
                        except:
                            pass
                        image = self.new_image(image_file_name, image_file_path)
                        self.pb_bake(socket_to_pb_emitter, bpy.data.images[image_file_name])
                        image.save()
                    else:
                        if os.path.isfile(image_file_path):
                            self.report({'INFO'}, " Baking skipped. {0} exists.".format(image_file_path))
                        else:
                            # if image to bake on does not exist: create new image, else use existing image
                            if bpy.data.images.find(image_name) == -1:
                                try:
                                    bpy.data.images.remove(bpy.data.images[image_file_name])
                                except:
                                    pass
                                image = self.new_image(image_file_name, image_file_path)
                            else:
                                image = bpy.data.images[image_name]
                            self.pb_bake(socket_to_pb_emitter, bpy.data.images[image.name])
                            image.save()
                        
        # clean up
        if materialoutput_node_has_link:
            self.mat.node_tree.links.new(socked_to_materialoutput_node_surface, self.materialoutput_node.inputs['Surface'])
        #TODO: more clean up. remove PB Emitter and image nodes
        
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
    file_format = StringProperty(
        name="Format",
        default="png",
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
    
# ------------------------------------------------------------------------
#    principledbaker in objectmode
# ------------------------------------------------------------------------

class OBJECT_PT_principledbaker_panel(Panel):
    bl_idname = "OBJECT_PT_principledbaker_panel"
    bl_label = "Principled Baker"
    bl_space_type = "VIEW_3D"   
    bl_region_type = "TOOLS"    
    bl_category = "Misc"
    bl_context = "objectmode"   

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
        layout.prop(pbaker, "file_path")
        layout.prop(pbaker, "prefix")
        layout.prop(pbaker, "file_format")
        layout.prop(pbaker, "use_overwrite")
        layout.label("Suffixes:")
        layout.prop(pbaker, "suffix_base_color")
        layout.prop(pbaker, "suffix_metallic")
        layout.prop(pbaker, "suffix_roughness")
        layout.prop(pbaker, "suffix_normal")
        layout.prop(pbaker, "suffix_bump")

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
