bl_info = {
    "name": "Batch Operation",
    "author": "ThumbSword Studio",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "3D Viewport > Sidebar > Batch Operation",
    "description": "Run repeatable operations on selected mesh objects",
    "category": "Object",
}

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup


class BATCHOP_PG_settings(PropertyGroup):
    operation: EnumProperty(
        name="Operation",
        description="Choose the batch operation to run",
        items=[
            (
                "ADD_UV_MAP",
                "Add New UV Map",
                "Add a UV map with the provided name to all selected mesh objects",
            ),
        ],
        default="ADD_UV_MAP",
    )

    new_uv_map_name: StringProperty(
        name="New UV Map Name",
        description="Name of the UV map to add",
        default="UVMap_Second",
    )


class BATCHOP_OT_add_uv_map(Operator):
    bl_idname = "batch_operation.add_uv_map"
    bl_label = "Add UV Map to Selected Objects"
    bl_description = "Add a UV map with the provided name to all selected mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.batch_operation_settings
        uv_name = settings.new_uv_map_name.strip()

        if not uv_name:
            self.report({"ERROR"}, "Enter a UV map name.")
            return {"CANCELLED"}

        selected_mesh_objects = [
            obj for obj in context.selected_objects
            if obj.type == "MESH"
        ]

        if not selected_mesh_objects:
            self.report({"ERROR"}, "Select at least one mesh object.")
            return {"CANCELLED"}

        added_count = 0
        skipped_count = 0
        processed_mesh_data = set()

        for obj in selected_mesh_objects:
            mesh = obj.data
            mesh_key = mesh.as_pointer()

            # Objects can share the same mesh data-block.
            # In that case, adding the UV map once is enough.
            if mesh_key in processed_mesh_data:
                continue

            processed_mesh_data.add(mesh_key)

            if mesh.uv_layers.get(uv_name) is not None:
                skipped_count += 1
                continue

            # do_init=True copies the currently active UV map when possible.
            # This is safer for an existing textured model than creating blank UVs.
            mesh.uv_layers.new(name=uv_name, do_init=True)
            added_count += 1

        self.report(
            {"INFO"},
            f'UV map "{uv_name}" added to {added_count} mesh data-block(s); '
            f"{skipped_count} already had it.",
        )
        return {"FINISHED"}


class BATCHOP_PT_main_panel(Panel):
    bl_label = "Batch Operation"
    bl_idname = "BATCHOP_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Batch Operation"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.batch_operation_settings

        layout.prop(settings, "operation")

        if settings.operation == "ADD_UV_MAP":
            box = layout.box()
            box.label(text="Add New UV Map")
            box.prop(settings, "new_uv_map_name")
            box.operator("batch_operation.add_uv_map", icon="GROUP_UVS")


classes = (
    BATCHOP_PG_settings,
    BATCHOP_OT_add_uv_map,
    BATCHOP_PT_main_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.batch_operation_settings = bpy.props.PointerProperty(
        type=BATCHOP_PG_settings
    )


def unregister():
    del bpy.types.Scene.batch_operation_settings

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
