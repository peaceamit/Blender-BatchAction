bl_info = {
    "name": "Batch Operation",
    "author": "ThumbSword Studio",
    "version": (0, 30, 0),
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
_target_uv_map_enum_items = []
PREVIEW_OVERRIDE_FLAG = "batch_operation_preview_override_active"
PREVIEW_LOCAL_VIEW_FLAG = "batch_operation_preview_local_view_active"
_material_enum_items = []


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


def get_target_uv_map_names(context):
    uv_names = set()

    for mesh in get_target_mesh_data(context):
        uv_names.update(uv_layer.name for uv_layer in mesh.uv_layers)

    return sorted(uv_names)


def get_uv_map_removal_impact(context, uv_name):
    target_mesh_objects = get_target_mesh_objects(context)
    impacted_objects = [
        obj for obj in target_mesh_objects
        if obj.data.uv_layers.get(uv_name) is not None
    ]

    impacted_mesh_data = []
    processed_mesh_data = set()

    for obj in impacted_objects:
        mesh = obj.data
        mesh_key = mesh.as_pointer()

        if mesh_key in processed_mesh_data:
            continue

        processed_mesh_data.add(mesh_key)
        impacted_mesh_data.append(mesh)

    return impacted_objects, impacted_mesh_data


def get_material_removal_impact(context):
    target_mesh_objects = get_target_mesh_objects(context)
    impacted_objects = [
        obj for obj in target_mesh_objects
        if len(obj.data.materials) > 0
    ]

    impacted_mesh_data = []
    processed_mesh_data = set()

    for obj in impacted_objects:
        mesh = obj.data
        mesh_key = mesh.as_pointer()

        if mesh_key in processed_mesh_data:
            continue

        processed_mesh_data.add(mesh_key)
        impacted_mesh_data.append(mesh)

    return impacted_objects, impacted_mesh_data


def snapshot_material_assignments(mesh_objects):
    snapshot = {}

    for obj in mesh_objects:
        mesh = obj.data
        snapshot[obj.as_pointer()] = {
            "active_material": obj.active_material.as_pointer()
            if obj.active_material is not None else None,
            "material_slots": [
                slot.material.as_pointer() if slot.material is not None else None
                for slot in obj.material_slots
            ],
            "mesh_materials": [
                material.as_pointer() if material is not None else None
                for material in mesh.materials
            ],
            "polygon_indices": [
                polygon.material_index for polygon in mesh.polygons
            ],
        }

    return snapshot


def redraw_view3d_areas(context):
    screen = context.screen

    if screen is None:
        return

    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()


def get_material_names():
    return sorted(material.name for material in bpy.data.materials)


def material_items(self, context):
    global _material_enum_items

    material_names = get_material_names()

    if not material_names:
        _material_enum_items = [
            (
                "NONE",
                "No materials available",
                "Create or import a material before using material preview",
            ),
        ]
        return _material_enum_items

    _material_enum_items = [
        (material_name, material_name, f'Preview with "{material_name}"')
        for material_name in material_names
    ]
    return _material_enum_items


def get_preview_material(context):
    settings = context.scene.batch_operation_settings
    material_name = settings.preview_material_choice

    if not material_name or material_name == "NONE":
        return None

    return bpy.data.materials.get(material_name)


def supports_material_override(context):
    return hasattr(context.view_layer, "material_override")


def is_preview_material_override_active(context):
    if not supports_material_override(context):
        return False

    return bool(context.scene.get(PREVIEW_OVERRIDE_FLAG, False)) and (
        context.view_layer.material_override is not None
    )


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


def target_uv_map_items(self, context):
    global _target_uv_map_enum_items

    uv_names = get_target_uv_map_names(context)

    if not uv_names:
        _target_uv_map_enum_items = [
            (
                "NONE",
                "No UV maps available",
                "Target mesh objects do not have UV maps",
            ),
        ]
        return _target_uv_map_enum_items

    _target_uv_map_enum_items = [
        (uv_name, uv_name, f'Remove "{uv_name}" from target meshes')
        for uv_name in uv_names
    ]
    return _target_uv_map_enum_items


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
            (
                "REMOVE_UV_MAP",
                "Remove UV Map",
                "Remove a named UV map from target mesh objects",
            ),
            (
                "REMOVE_ALL_MATERIALS",
                "Remove All Materials",
                "Remove all material slots from target mesh objects",
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

    remove_uv_map_choice: EnumProperty(
        name="UV Map Name",
        description="UV map to remove from target mesh objects",
        items=target_uv_map_items,
    )

    preview_material_choice: EnumProperty(
        name="Preview Material",
        description="Material to use as a view-only preview override",
        items=material_items,
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


class BATCHOP_OT_remove_uv_map(Operator):
    bl_idname = "batch_operation.remove_uv_map"
    bl_label = "Remove UV Map from Target Objects"
    bl_description = "Remove a named UV map from target mesh objects after confirmation"
    bl_options = {"REGISTER", "UNDO"}

    def get_remove_uv_name(self, context):
        settings = context.scene.batch_operation_settings
        return settings.remove_uv_map_choice.strip()

    def draw(self, context):
        layout = self.layout
        uv_name = self.get_remove_uv_name(context)
        impacted_objects, impacted_mesh_data = get_uv_map_removal_impact(context, uv_name)

        layout.label(text=f'Remove UV map "{uv_name}"?')
        layout.label(text=f"Objects impacted: {len(impacted_objects)}")
        layout.label(text=f"Mesh data-blocks changed: {len(impacted_mesh_data)}")

    def invoke(self, context, event):
        uv_name = self.get_remove_uv_name(context)

        if not uv_name or uv_name == "NONE":
            self.report({"ERROR"}, "Choose a UV map to remove.")
            return {"CANCELLED"}

        impacted_objects, impacted_mesh_data = get_uv_map_removal_impact(context, uv_name)

        if not impacted_objects:
            self.report({"ERROR"}, f'No target objects have UV map "{uv_name}".')
            return {"CANCELLED"}

        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        uv_name = self.get_remove_uv_name(context)

        if not uv_name or uv_name == "NONE":
            self.report({"ERROR"}, "Choose a UV map to remove.")
            return {"CANCELLED"}

        impacted_objects, impacted_mesh_data = get_uv_map_removal_impact(context, uv_name)

        if not impacted_mesh_data:
            self.report({"ERROR"}, f'No target mesh data-blocks have UV map "{uv_name}".')
            return {"CANCELLED"}

        removed_count = 0

        for mesh in impacted_mesh_data:
            uv_layer = mesh.uv_layers.get(uv_name)

            if uv_layer is None:
                continue

            mesh.uv_layers.remove(uv_layer)
            removed_count += 1

        redraw_view3d_areas(context)
        self.report(
            {"INFO"},
            f'Removed UV map "{uv_name}" from {len(impacted_objects)} object(s) '
            f"and {removed_count} mesh data-block(s).",
        )
        return {"FINISHED"}


class BATCHOP_OT_remove_all_materials(Operator):
    bl_idname = "batch_operation.remove_all_materials"
    bl_label = "Remove All Materials from Target Objects"
    bl_description = "Remove all material slots from target mesh objects after confirmation"
    bl_options = {"REGISTER", "UNDO"}

    def draw(self, context):
        layout = self.layout
        impacted_objects, impacted_mesh_data = get_material_removal_impact(context)

        layout.label(text="Remove all materials from target objects?")
        layout.label(text=f"Objects impacted: {len(impacted_objects)}")
        layout.label(text=f"Mesh data-blocks changed: {len(impacted_mesh_data)}")

    def invoke(self, context, event):
        impacted_objects, impacted_mesh_data = get_material_removal_impact(context)

        if not impacted_objects:
            self.report({"ERROR"}, "No target mesh objects have materials.")
            return {"CANCELLED"}

        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        impacted_objects, impacted_mesh_data = get_material_removal_impact(context)

        if not impacted_mesh_data:
            self.report({"ERROR"}, "No target mesh data-blocks have materials.")
            return {"CANCELLED"}

        removed_count = 0

        for mesh in impacted_mesh_data:
            mesh.materials.clear()

            for polygon in mesh.polygons:
                polygon.material_index = 0

            removed_count += 1

        redraw_view3d_areas(context)
        self.report(
            {"INFO"},
            f"Removed all materials from {len(impacted_objects)} object(s) "
            f"and {removed_count} mesh data-block(s).",
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
    bl_description = "Preview target objects with the selected material without changing mesh materials"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target_mesh_objects = get_target_mesh_objects(context)
        material_snapshot = snapshot_material_assignments(target_mesh_objects)

        if not supports_material_override(context):
            self.report({"ERROR"}, "This Blender context does not support material override.")
            return {"CANCELLED"}

        preview_material = get_preview_material(context)

        if preview_material is None:
            self.report({"ERROR"}, "Choose a preview material.")
            return {"CANCELLED"}

        current_override = context.view_layer.material_override

        if current_override is not None and current_override != preview_material:
            self.report(
                {"ERROR"},
                f'Current view layer already uses override "{current_override.name}".',
            )
            return {"CANCELLED"}

        context.view_layer.material_override = preview_material
        context.scene[PREVIEW_OVERRIDE_FLAG] = True
        context.scene[PREVIEW_LOCAL_VIEW_FLAG] = False

        if target_mesh_objects:
            context.scene[PREVIEW_LOCAL_VIEW_FLAG] = set_target_local_view(
                context,
                set(target_mesh_objects),
                True,
            )

        set_material_preview_viewport(context)

        if snapshot_material_assignments(target_mesh_objects) != material_snapshot:
            context.view_layer.material_override = current_override
            context.scene[PREVIEW_OVERRIDE_FLAG] = False
            context.scene[PREVIEW_LOCAL_VIEW_FLAG] = False
            self.report({"ERROR"}, "Cancelled: material assignments changed unexpectedly.")
            return {"CANCELLED"}

        if target_mesh_objects:
            message = (
                f"Preview override enabled for viewing "
                f"{len(target_mesh_objects)} target object(s)."
            )
        else:
            message = "Preview override enabled for the current view layer."

        self.report({"INFO"}, message)
        return {"FINISHED"}


class BATCHOP_OT_toggle_preview_material(Operator):
    bl_idname = "batch_operation.toggle_preview_material"
    bl_label = "Toggle Preview Material"
    bl_description = "Toggle the selected material as a view-only material override"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if is_preview_material_override_active(context):
            return bpy.ops.batch_operation.revert_preview_material()

        return bpy.ops.batch_operation.apply_preview_material()


class BATCHOP_OT_revert_preview_material(Operator):
    bl_idname = "batch_operation.revert_preview_material"
    bl_label = "Revert Material"
    bl_description = "Clear the selected material viewport override"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not supports_material_override(context):
            self.report({"ERROR"}, "This Blender context does not support material override.")
            return {"CANCELLED"}

        if not is_preview_material_override_active(context):
            context.scene[PREVIEW_OVERRIDE_FLAG] = False
            self.report({"WARNING"}, "The selected preview material override is not active.")
            return {"CANCELLED"}

        context.view_layer.material_override = None
        context.scene[PREVIEW_OVERRIDE_FLAG] = False
        if context.scene.get(PREVIEW_LOCAL_VIEW_FLAG, False):
            set_target_local_view(context, set(), False)
            context.scene[PREVIEW_LOCAL_VIEW_FLAG] = False
        self.report({"INFO"}, "Cleared material preview override.")
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
        layout.label(text="Tool Version: 0.30.0")
        layout.label(text=f"Source: {__file__}")
        layout.separator()

        row = layout.row(align=True)
        row.prop(settings, "object_source", expand=True)
        row.operator("batch_operation.refresh_targets", text="", icon="FILE_REFRESH")

        target_objects = get_target_objects(context)
        target_mesh_objects = get_target_mesh_objects(context)
        layout.label(
            text=(
                f"Target Objects: {len(target_objects)} "
                f"({len(target_mesh_objects)} mesh)"
            ),
            icon="OBJECT_DATA",
        )

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
        elif settings.operation == "REMOVE_UV_MAP":
            uv_names = get_target_uv_map_names(context)
            has_uv_maps = len(uv_names) > 0

            box = layout.box()
            box.label(text="Remove UV Map")
            if has_uv_maps:
                box.prop(settings, "remove_uv_map_choice")
            else:
                box.label(text="No UV maps available on target meshes.", icon="ERROR")

            row = box.row()
            row.enabled = has_uv_maps
            row.operator("batch_operation.remove_uv_map", icon="TRASH")
        elif settings.operation == "REMOVE_ALL_MATERIALS":
            impacted_objects, impacted_mesh_data = get_material_removal_impact(context)
            has_materials = len(impacted_mesh_data) > 0

            box = layout.box()
            box.label(text="Remove All Materials")
            if has_materials:
                box.label(text=f"Objects impacted: {len(impacted_objects)}")
                box.label(text=f"Mesh data-blocks changed: {len(impacted_mesh_data)}")
            else:
                box.label(text="No target mesh materials available.", icon="ERROR")

            row = box.row()
            row.enabled = has_materials
            row.operator("batch_operation.remove_all_materials", icon="TRASH")

        layout.separator()

        target_mesh_objects = get_target_mesh_objects(context)
        has_mesh_objects = len(target_mesh_objects) > 0
        has_materials = len(bpy.data.materials) > 0
        can_use_material_override = supports_material_override(context)
        preview_override_active = is_preview_material_override_active(context)
        current_material_override = get_current_material_override(context)
        other_override_active = (
            current_material_override is not None and not preview_override_active
        )

        material_box = layout.box()
        material_box.label(text="Material Preview")
        material_box.label(text="Mode: View layer material override")

        if has_materials:
            material_box.prop(settings, "preview_material_choice")
        else:
            material_box.label(text="No materials available.", icon="ERROR")

        toggle_text = "Revert Preview Material" if preview_override_active else "Preview Material"
        toggle_icon = "FILE_REFRESH" if preview_override_active else "MATERIAL"

        row = material_box.row(align=True)
        row.enabled = (
            has_materials
            and can_use_material_override
            and not other_override_active
        )
        row.operator(
            "batch_operation.toggle_preview_material",
            text=toggle_text,
            icon=toggle_icon,
        )

        if not can_use_material_override:
            material_box.label(text="Material override is unavailable here.", icon="ERROR")
        elif preview_override_active:
            material_box.label(text="Preview override is active.", icon="INFO")
        elif other_override_active:
            material_box.label(
                text=f'View layer already overrides with "{current_material_override.name}".',
                icon="ERROR",
            )
        elif has_mesh_objects:
            material_box.label(text="Mesh material assignments are never changed.", icon="INFO")
        else:
            material_box.label(text="No targets: preview applies to the view layer.", icon="INFO")


classes = (
    BATCHOP_PG_object_item,
    BATCHOP_PG_settings,
    BATCHOP_OT_add_uv_map,
    BATCHOP_OT_switch_uv_map,
    BATCHOP_OT_rename_uv_map,
    BATCHOP_OT_open_uv_editor,
    BATCHOP_OT_remove_uv_map,
    BATCHOP_OT_remove_all_materials,
    BATCHOP_OT_refresh_targets,
    BATCHOP_OT_apply_preview_material,
    BATCHOP_OT_toggle_preview_material,
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
