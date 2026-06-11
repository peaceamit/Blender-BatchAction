bl_info = {
    "name": "Batch Operation",
    "author": "ThumbSword Studio",
    "version": (0, 22, 0),
    "blender": (5, 1, 0),
    "location": "3D Viewport > Sidebar > Batch Operation",
    "description": "Run repeatable operations on selected mesh objects",
    "category": "Object",
}

import bpy
import sys
from bpy.props import CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList


_uv_map_enum_items = []
PREVIEW_MATERIAL_NAME = "PreviewMaterial"
PREVIEW_OVERRIDE_FLAG = "batch_operation_preview_override_active"
PREVIEW_LOCAL_VIEW_FLAG = "batch_operation_preview_local_view_active"


def get_target_objects(context):
    settings = context.scene.batch_operation_settings

    if settings.object_source == "DROP_LIST":
        return [
            item.object for item in settings.object_items
            if item.object is not None
        ]

    return list(context.selected_objects)


def get_target_mesh_objects(context):
    return [
        obj for obj in get_target_objects(context)
        if obj.type == "MESH"
    ]


def get_target_mesh_data(context):
    target_mesh_objects = get_target_mesh_objects(context)

    mesh_data = []
    processed_mesh_data = set()

    for obj in target_mesh_objects:
        mesh = obj.data
        mesh_key = mesh.as_pointer()

        if mesh_key in processed_mesh_data:
            continue

        processed_mesh_data.add(mesh_key)
        mesh_data.append(mesh)

    return mesh_data


def get_common_uv_map_names(context):
    mesh_data = get_target_mesh_data(context)

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


def redraw_view3d_areas(context):
    screen = context.screen

    if screen is None:
        return

    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()


def get_preview_material():
    material = bpy.data.materials.get(PREVIEW_MATERIAL_NAME)

    if material is None:
        material = bpy.data.materials.new(PREVIEW_MATERIAL_NAME)
        material.diffuse_color = (1.0, 0.35, 0.0, 1.0)

    material.use_fake_user = True
    return material


def supports_material_override(context):
    return hasattr(context.view_layer, "material_override")


def is_preview_material_override_active(context):
    if not supports_material_override(context):
        return False

    preview_material = bpy.data.materials.get(PREVIEW_MATERIAL_NAME)

    if preview_material is None:
        return False

    return context.view_layer.material_override == preview_material


def get_current_material_override(context):
    if not supports_material_override(context):
        return None

    return context.view_layer.material_override


def get_view3d_space(context):
    if context.area is None or context.area.type != "VIEW_3D":
        return None

    return context.space_data


def set_material_preview_viewport(context):
    space = get_view3d_space(context)

    if space is None:
        return

    space.shading.type = "MATERIAL"


def set_target_local_view(context, target_objects, state):
    space = get_view3d_space(context)

    if space is None:
        return False

    try:
        for obj in context.scene.objects:
            obj.local_view_set(space, obj in target_objects if state else False)
    except Exception:
        return False

    return True


def common_uv_map_items(self, context):
    global _uv_map_enum_items

    common_uv_names = get_common_uv_map_names(context)

    if not common_uv_names:
        _uv_map_enum_items = [
            (
                "NONE",
                "No UV maps available",
                "Target mesh objects do not have a shared UV map name",
            ),
        ]
        return _uv_map_enum_items

    _uv_map_enum_items = [
        (uv_name, uv_name, f'Switch selected meshes to "{uv_name}"')
        for uv_name in common_uv_names
    ]
    return _uv_map_enum_items


class BATCHOP_PG_object_item(PropertyGroup):
    object: PointerProperty(
        name="Object",
        description="Object to include in batch operations",
        type=bpy.types.Object,
    )


class BATCHOP_PG_settings(PropertyGroup):
    object_source: EnumProperty(
        name="Object Source",
        description="Choose which objects batch operations should use",
        items=[
            (
                "SELECTED",
                "Selected",
                "Use the currently selected objects",
            ),
            (
                "DROP_LIST",
                "Drop List",
                "Use the objects in the list below",
            ),
        ],
        default="SELECTED",
    )

    object_items: CollectionProperty(type=BATCHOP_PG_object_item)

    object_items_index: IntProperty(default=0)

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
            (
                "RENAME_UV_MAP",
                "Rename UV Map",
                "Rename a shared UV map on all target mesh objects",
            ),
            (
                "OPEN_UV_EDITOR",
                "Open UV Editor",
                "Open the target mesh objects in UV edit mode",
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

    rename_uv_map_choice: EnumProperty(
        name="Current UV Map",
        description="Common UV map to rename",
        items=common_uv_map_items,
    )

    rename_uv_map_name: StringProperty(
        name="New UV Map Name",
        description="New name for the chosen UV map",
        default="UVMap_Renamed",
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

        target_mesh_objects = get_target_mesh_objects(context)

        if not target_mesh_objects:
            self.report({"ERROR"}, "Choose at least one mesh object.")
            return {"CANCELLED"}

        added_count = 0
        skipped_count = 0
        processed_mesh_data = set()

        for obj in target_mesh_objects:
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

        mesh_data = get_target_mesh_data(context)

        if not mesh_data:
            self.report({"ERROR"}, "Choose at least one mesh object.")
            return {"CANCELLED"}

        common_uv_names = get_common_uv_map_names(context)
        if uv_name == "NONE" or uv_name not in common_uv_names:
            self.report(
                {"ERROR"},
                "Target mesh objects do not share the chosen UV map.",
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


class BATCHOP_OT_rename_uv_map(Operator):
    bl_idname = "batch_operation.rename_uv_map"
    bl_label = "Rename UV Map on Target Objects"
    bl_description = "Rename a shared UV map on all target mesh objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.batch_operation_settings
        old_uv_name = settings.rename_uv_map_choice.strip()
        new_uv_name = settings.rename_uv_map_name.strip()

        if not old_uv_name or old_uv_name == "NONE":
            self.report({"ERROR"}, "Choose a UV map to rename.")
            return {"CANCELLED"}

        if not new_uv_name:
            self.report({"ERROR"}, "Enter a new UV map name.")
            return {"CANCELLED"}

        mesh_data = get_target_mesh_data(context)

        if not mesh_data:
            self.report({"ERROR"}, "Choose at least one mesh object.")
            return {"CANCELLED"}

        common_uv_names = get_common_uv_map_names(context)
        if old_uv_name not in common_uv_names:
            self.report(
                {"ERROR"},
                "Target mesh objects do not share the chosen UV map.",
            )
            return {"CANCELLED"}

        if old_uv_name == new_uv_name:
            self.report({"INFO"}, "UV map already has that name.")
            return {"FINISHED"}

        for mesh in mesh_data:
            existing_uv_layer = mesh.uv_layers.get(new_uv_name)
            old_uv_layer = mesh.uv_layers.get(old_uv_name)

            if existing_uv_layer is not None and existing_uv_layer != old_uv_layer:
                self.report(
                    {"ERROR"},
                    f'Cannot rename: "{new_uv_name}" already exists on "{mesh.name}".',
                )
                return {"CANCELLED"}

        renamed_count = 0

        for mesh in mesh_data:
            mesh.uv_layers[old_uv_name].name = new_uv_name
            renamed_count += 1

        self.report(
            {"INFO"},
            f'UV map "{old_uv_name}" renamed to "{new_uv_name}" on '
            f"{renamed_count} mesh data-block(s).",
        )
        return {"FINISHED"}


class BATCHOP_OT_open_uv_editor(Operator):
    bl_idname = "batch_operation.open_uv_editor"
    bl_label = "Open UV Editor with Target Objects"
    bl_description = "Select target mesh objects and open them in UV edit mode"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target_mesh_objects = get_target_mesh_objects(context)

        if not target_mesh_objects:
            self.report({"ERROR"}, "Choose at least one mesh object.")
            return {"CANCELLED"}

        active_object = target_mesh_objects[0]

        if context.object is not None and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.object.select_all(action="DESELECT")

        for obj in target_mesh_objects:
            obj.select_set(True)

        context.view_layer.objects.active = active_object
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="SELECT")

        if context.area is not None:
            context.area.ui_type = "UV"

        self.report(
            {"INFO"},
            f"Opened {len(target_mesh_objects)} mesh object(s) in the UV Editor.",
        )
        return {"FINISHED"}


class BATCHOP_OT_refresh_targets(Operator):
    bl_idname = "batch_operation.refresh_targets"
    bl_label = "Refresh Targets"
    bl_description = "Refresh target object and UV map dropdowns"
    bl_options = {"REGISTER"}

    def execute(self, context):
        redraw_view3d_areas(context)
        self.report({"INFO"}, "Batch Operation targets refreshed.")
        return {"FINISHED"}


class BATCHOP_OT_apply_preview_material(Operator):
    bl_idname = "batch_operation.apply_preview_material"
    bl_label = "Change Material"
    bl_description = "Preview target objects with PreviewMaterial without changing mesh materials"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target_mesh_objects = get_target_mesh_objects(context)

        if not target_mesh_objects:
            self.report({"ERROR"}, "Choose at least one mesh object.")
            return {"CANCELLED"}

        if not supports_material_override(context):
            self.report({"ERROR"}, "This Blender context does not support material override.")
            return {"CANCELLED"}

        preview_material = get_preview_material()
        current_override = context.view_layer.material_override

        if current_override is not None and current_override != preview_material:
            self.report(
                {"ERROR"},
                f'Current view layer already uses override "{current_override.name}".',
            )
            return {"CANCELLED"}

        if context.object is not None and context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        bpy.ops.object.select_all(action="DESELECT")

        for obj in target_mesh_objects:
            obj.select_set(True)

        context.view_layer.objects.active = target_mesh_objects[0]
        context.view_layer.material_override = preview_material
        context.scene[PREVIEW_OVERRIDE_FLAG] = True
        context.scene[PREVIEW_LOCAL_VIEW_FLAG] = set_target_local_view(
            context,
            set(target_mesh_objects),
            True,
        )
        set_material_preview_viewport(context)

        self.report(
            {"INFO"},
            f"Preview override enabled for viewing {len(target_mesh_objects)} target object(s).",
        )
        return {"FINISHED"}


class BATCHOP_OT_revert_preview_material(Operator):
    bl_idname = "batch_operation.revert_preview_material"
    bl_label = "Revert Material"
    bl_description = "Clear the PreviewMaterial viewport override"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not supports_material_override(context):
            self.report({"ERROR"}, "This Blender context does not support material override.")
            return {"CANCELLED"}

        if not is_preview_material_override_active(context):
            context.scene[PREVIEW_OVERRIDE_FLAG] = False
            self.report({"WARNING"}, f"{PREVIEW_MATERIAL_NAME} override is not active.")
            return {"CANCELLED"}

        context.view_layer.material_override = None
        context.scene[PREVIEW_OVERRIDE_FLAG] = False
        if context.scene.get(PREVIEW_LOCAL_VIEW_FLAG, False):
            set_target_local_view(context, set(), False)
            context.scene[PREVIEW_LOCAL_VIEW_FLAG] = False
        self.report({"INFO"}, f"Cleared {PREVIEW_MATERIAL_NAME} viewport override.")
        return {"FINISHED"}


class BATCHOP_OT_add_object_list_item(Operator):
    bl_idname = "batch_operation.add_object_list_item"
    bl_label = "Add Object Slot"
    bl_description = "Add an empty object slot to the drop list"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.batch_operation_settings
        settings.object_items.add()
        settings.object_items_index = len(settings.object_items) - 1
        redraw_view3d_areas(context)
        return {"FINISHED"}


class BATCHOP_OT_add_selected_to_object_list(Operator):
    bl_idname = "batch_operation.add_selected_to_object_list"
    bl_label = "Add Selected Objects"
    bl_description = "Add currently selected objects to the drop list"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.batch_operation_settings
        existing_objects = {
            item.object for item in settings.object_items
            if item.object is not None
        }

        added_count = 0
        for obj in context.selected_objects:
            if obj in existing_objects:
                continue

            item = settings.object_items.add()
            item.object = obj
            existing_objects.add(obj)
            added_count += 1

        if added_count == 0:
            self.report({"INFO"}, "No new selected objects to add.")
        else:
            settings.object_items_index = len(settings.object_items) - 1
            self.report({"INFO"}, f"Added {added_count} object(s) to the drop list.")

        redraw_view3d_areas(context)
        return {"FINISHED"}


class BATCHOP_OT_remove_object_list_item(Operator):
    bl_idname = "batch_operation.remove_object_list_item"
    bl_label = "Remove Object"
    bl_description = "Remove the active object from the drop list"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.batch_operation_settings
        index = settings.object_items_index

        if index < 0 or index >= len(settings.object_items):
            return {"CANCELLED"}

        settings.object_items.remove(index)
        settings.object_items_index = max(0, min(index, len(settings.object_items) - 1))
        redraw_view3d_areas(context)
        return {"FINISHED"}


class BATCHOP_OT_clear_object_list(Operator):
    bl_idname = "batch_operation.clear_object_list"
    bl_label = "Clear Object List"
    bl_description = "Remove all objects from the drop list"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.batch_operation_settings
        settings.object_items.clear()
        settings.object_items_index = 0
        redraw_view3d_areas(context)
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
            print(f"Batch Operation update failed: module {module_name} was not found.")
            return None

        module_path = getattr(module, "__file__", __file__)
        module.unregister()

        with open(module_path, "r", encoding="utf-8") as source_file:
            source = source_file.read()

        exec(compile(source, module_path, "exec"), module.__dict__)
        module.register()
        print(f"Batch Operation updated from: {module_path}")
    except Exception as exc:
        print(f"Batch Operation update failed: {exc}")

    return None


class BATCHOP_UL_object_list(UIList):
    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname,
        index,
    ):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            layout.prop(item, "object", text="")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text="", icon="OBJECT_DATA")


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
        layout.label(text="Tool Version: 0.22.0")
        layout.label(text=f"Source: {__file__}")
        layout.separator()

        row = layout.row(align=True)
        row.prop(settings, "object_source", expand=True)
        row.operator("batch_operation.refresh_targets", text="", icon="FILE_REFRESH")

        if settings.object_source == "DROP_LIST":
            row = layout.row()
            row.template_list(
                "BATCHOP_UL_object_list",
                "",
                settings,
                "object_items",
                settings,
                "object_items_index",
                rows=4,
            )

            column = row.column(align=True)
            column.operator("batch_operation.add_object_list_item", text="", icon="ADD")
            column.operator("batch_operation.remove_object_list_item", text="", icon="REMOVE")
            column.separator()
            column.operator("batch_operation.clear_object_list", text="", icon="TRASH")

            layout.operator("batch_operation.add_selected_to_object_list", icon="SELECT_EXTEND")

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
                box.label(text="No UV maps available on target meshes.", icon="ERROR")

            row = box.row()
            row.enabled = has_common_uv_maps
            row.operator("batch_operation.switch_uv_map", icon="GROUP_UVS")
        elif settings.operation == "RENAME_UV_MAP":
            common_uv_names = get_common_uv_map_names(context)
            has_common_uv_maps = len(common_uv_names) > 0

            box = layout.box()
            box.label(text="Rename UV Map")
            if has_common_uv_maps:
                box.prop(settings, "rename_uv_map_choice")
                box.prop(settings, "rename_uv_map_name")
            else:
                box.label(text="No UV maps available on target meshes.", icon="ERROR")

            row = box.row()
            row.enabled = has_common_uv_maps
            row.operator("batch_operation.rename_uv_map", icon="GREASEPENCIL")
        elif settings.operation == "OPEN_UV_EDITOR":
            target_mesh_objects = get_target_mesh_objects(context)
            has_mesh_objects = len(target_mesh_objects) > 0

            box = layout.box()
            box.label(text="Open UV Editor")
            if not has_mesh_objects:
                box.label(text="No target mesh objects available.", icon="ERROR")

            row = box.row()
            row.enabled = has_mesh_objects
            row.operator("batch_operation.open_uv_editor", icon="UV")

        layout.separator()

        target_mesh_objects = get_target_mesh_objects(context)
        has_mesh_objects = len(target_mesh_objects) > 0
        can_use_material_override = supports_material_override(context)
        preview_override_active = is_preview_material_override_active(context)
        current_material_override = get_current_material_override(context)
        other_override_active = (
            current_material_override is not None and not preview_override_active
        )

        material_box = layout.box()
        material_box.label(text="Material Switcher")
        material_box.label(text=f"Preview override: {PREVIEW_MATERIAL_NAME}")
        material_box.label(text="Mode: View layer material override")

        row = material_box.row(align=True)
        row.enabled = (
            has_mesh_objects
            and can_use_material_override
            and not preview_override_active
            and not other_override_active
        )
        row.operator("batch_operation.apply_preview_material", icon="MATERIAL")

        row = material_box.row(align=True)
        row.enabled = can_use_material_override and preview_override_active
        row.operator("batch_operation.revert_preview_material", icon="FILE_REFRESH")

        if not has_mesh_objects:
            material_box.label(text="No target mesh objects available.", icon="ERROR")
        elif not can_use_material_override:
            material_box.label(text="Material override is unavailable here.", icon="ERROR")
        elif preview_override_active:
            material_box.label(text="Preview override is active.", icon="INFO")
        elif other_override_active:
            material_box.label(
                text=f'View layer already overrides with "{current_material_override.name}".',
                icon="ERROR",
            )
        else:
            material_box.label(text="Mesh material assignments are never changed.", icon="INFO")


classes = (
    BATCHOP_PG_object_item,
    BATCHOP_PG_settings,
    BATCHOP_OT_add_uv_map,
    BATCHOP_OT_switch_uv_map,
    BATCHOP_OT_rename_uv_map,
    BATCHOP_OT_open_uv_editor,
    BATCHOP_OT_refresh_targets,
    BATCHOP_OT_apply_preview_material,
    BATCHOP_OT_revert_preview_material,
    BATCHOP_OT_add_object_list_item,
    BATCHOP_OT_add_selected_to_object_list,
    BATCHOP_OT_remove_object_list_item,
    BATCHOP_OT_clear_object_list,
    BATCHOP_OT_update_addon,
    BATCHOP_UL_object_list,
    BATCHOP_PT_main_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.batch_operation_settings = bpy.props.PointerProperty(
        type=BATCHOP_PG_settings
    )


def unregister():
    if hasattr(bpy.types.Scene, "batch_operation_settings"):
        del bpy.types.Scene.batch_operation_settings

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


if __name__ == "__main__":
    register()
