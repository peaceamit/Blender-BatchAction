bl_info = {
    "name": "Batch Operation",
    "author": "ThumbSword Studio",
    "version": (0, 5, 0),
    "blender": (4, 0, 0),
    "location": "3D Viewport > Sidebar > Batch Operation",
    "description": "Run repeatable operations on selected mesh objects",
    "category": "Object",
}

import bpy
import importlib
import sys
import types
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup


_uv_map_enum_items = []


def get_selected_mesh_data(context):
    selected_mesh_objects = [
        obj for obj in context.selected_objects
        if obj.type == "MESH"
    ]

    mesh_data = []
    processed_mesh_data = set()

    for obj in selected_mesh_objects:
        mesh = obj.data
        mesh_key = mesh.as_pointer()

        if mesh_key in processed_mesh_data:
            continue

        processed_mesh_data.add(mesh_key)
        mesh_data.append(mesh)

    return mesh_data


def get_common_uv_map_names(context):
    mesh_data = get_selected_mesh_data(context)

    if not mesh_data:
        return []

    common_uv_names = {
        uv_layer.name for uv_layer in mesh_data[0].uv_layers
    }

    for mesh in mesh_data[1:]:
        common_uv_names.intersection_update(
            uv_layer.name for uv_layer in mesh.uv_layers
        )

    return sorted(common_uv_names)


def common_uv_map_items(self, context):
    global _uv_map_enum_items

    common_uv_names = get_common_uv_map_names(context)

    if not common_uv_names:
        _uv_map_enum_items = [
            (
                "NONE",
                "No common UV maps",
                "Selected mesh objects do not share a UV map name",
            ),
        ]
        return _uv_map_enum_items

    _uv_map_enum_items = [
        (uv_name, uv_name, f'Switch selected meshes to "{uv_name}"')
        for uv_name in common_uv_names
    ]
    return _uv_map_enum_items


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
            (
                "SWITCH_UV_MAP",
                "Switch UV Map",
                "Set the named UV map as active and active render on all selected mesh objects",
            ),
        ],
        default="ADD_UV_MAP",
    )

    new_uv_map_name: StringProperty(
        name="New UV Map Name",
        description="Name of the UV map to add",
        default="UVMap_Second",
    )

    switch_uv_map_choice: EnumProperty(
        name="UV Map Name",
        description="Common UV map to make active",
        items=common_uv_map_items,
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


class BATCHOP_OT_switch_uv_map(Operator):
    bl_idname = "batch_operation.switch_uv_map"
    bl_label = "Switch UV Map on Selected Objects"
    bl_description = "Set the named UV map as active and active render on all selected mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.batch_operation_settings
        uv_name = settings.switch_uv_map_choice.strip()

        if not uv_name:
            self.report({"ERROR"}, "Enter a UV map name.")
            return {"CANCELLED"}

        mesh_data = get_selected_mesh_data(context)

        if not mesh_data:
            self.report({"ERROR"}, "Select at least one mesh object.")
            return {"CANCELLED"}

        common_uv_names = get_common_uv_map_names(context)
        if uv_name == "NONE" or uv_name not in common_uv_names:
            self.report(
                {"ERROR"},
                "Selected mesh objects do not share the chosen UV map.",
            )
            return {"CANCELLED"}

        switched_count = 0

        for mesh in mesh_data:
            uv_layer = mesh.uv_layers.get(uv_name)
            mesh.uv_layers.active = uv_layer
            uv_layer.active_render = True
            switched_count += 1

        self.report(
            {"INFO"},
            f'UV map "{uv_name}" made active and active render on '
            f"{switched_count} mesh data-block(s).",
        )
        return {"FINISHED"}


class BATCHOP_OT_update_addon(Operator):
    bl_idname = "batch_operation.update_addon"
    bl_label = "Update Tool"
    bl_description = "Reload this add-on from the latest file changes"
    bl_options = {"REGISTER"}

    def execute(self, context):
        self.report({"INFO"}, "Reloading Batch Operation tool...")
        bpy.app.timers.register(reload_this_addon, first_interval=0.1)

        return {"FINISHED"}


def reload_this_addon():
    module_name = __name__

    try:
        module = sys.modules.get(module_name)
        if module is None:
            return None

        module_path = getattr(module, "__file__", __file__)
        importlib.invalidate_caches()
        module.unregister()

        with open(module_path, "r", encoding="utf-8") as source_file:
            source = source_file.read()

        new_module = types.ModuleType(module_name)
        new_module.__file__ = module_path
        new_module.__package__ = getattr(module, "__package__", None)
        sys.modules[module_name] = new_module

        exec(compile(source, module_path, "exec"), new_module.__dict__)
        new_module.register()
    except Exception as exc:
        print(f"Batch Operation update failed: {exc}")

    return None


class BATCHOP_PT_main_panel(Panel):
    bl_label = "Batch Operation"
    bl_idname = "BATCHOP_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Batch Operation"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.batch_operation_settings

        layout.operator("batch_operation.update_addon", icon="FILE_REFRESH")
        layout.label(text="Tool Version: 0.5.0")
        layout.label(text=f"Source: {__file__}")
        layout.separator()
        layout.prop(settings, "operation", expand=True)

        if settings.operation == "ADD_UV_MAP":
            box = layout.box()
            box.label(text="Add New UV Map")
            box.prop(settings, "new_uv_map_name")
            box.operator("batch_operation.add_uv_map", icon="GROUP_UVS")
        elif settings.operation == "SWITCH_UV_MAP":
            common_uv_names = get_common_uv_map_names(context)
            has_common_uv_maps = len(common_uv_names) > 0

            box = layout.box()
            box.label(text="Switch UV Map")
            if has_common_uv_maps:
                box.prop(settings, "switch_uv_map_choice")
            else:
                box.label(text="No common UV maps on selected meshes.", icon="ERROR")

            row = box.row()
            row.enabled = has_common_uv_maps
            row.operator("batch_operation.switch_uv_map", icon="GROUP_UVS")


classes = (
    BATCHOP_PG_settings,
    BATCHOP_OT_add_uv_map,
    BATCHOP_OT_switch_uv_map,
    BATCHOP_OT_update_addon,
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
