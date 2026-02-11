import bpy

from ....properties.types import LightType
from ...log import logger
from ...models import (
    ColorID,
    ControlMapElement_MODIFIED,
    ControlMapStatus_MODIFIED,
    CtrlData,
    EditingData,
    EditMode,
    FiberData,
    LEDBulbData,
    LEDData,
    PartType,
    Revision,
    SelectMode,
)
from ...states import state
from ...utils.notification import notify
from ...utils.object import clear_selection
from ...utils.operator import execute_operator
from ...utils.ui import redraw_area, set_outliner_filter
from .control_map import (
    add_control,
    apply_control_map_updates,
    delete_control,
    update_control,
)
from .current_status import update_current_status_by_index


def attach_editing_control_frame():
    """Attach to editing frame and sync location to ld_position"""
    if not bpy.context:
        return
    current_frame = state.current_editing_frame

    state.current_editing_detached = False
    state.current_editing_frame_synced = True

    if current_frame != bpy.context.scene.frame_current:
        bpy.context.scene.frame_current = current_frame

    sync_editing_control_frame_properties()


def sync_editing_control_frame_properties():
    """Sync location to ld_position"""
    show_dancer_dict = dict(zip(state.dancer_names, state.show_dancers))
    for dancer in state.dancers_array:
        if not show_dancer_dict[dancer.name]:
            continue
        dancer_obj: bpy.types.Object | None = bpy.data.objects.get(dancer.name)
        if dancer_obj is not None:
            part_objs: list[bpy.types.Object] = getattr(dancer_obj, "children")
            part_obj_names: list[str] = [
                getattr(obj, "ld_part_name") for obj in part_objs
            ]

            for part in dancer.parts:
                if part.name not in part_obj_names:
                    continue

                part_index = part_obj_names.index(part.name)
                part_obj = part_objs[part_index]
                part_type = getattr(part_obj, "ld_light_type")

                # Boost alpha to 255 in edit mode so user can see and edit
                # (stored data may have alpha=0 for "no effect" frames)
                ld_alpha: int = getattr(part_obj, "ld_alpha")
                if ld_alpha == 0:
                    setattr(part_obj, "ld_alpha", 255)

                # Re-trigger update
                if part_type == LightType.FIBER.value:
                    ld_alpha = getattr(part_obj, "ld_alpha")
                    setattr(part_obj, "ld_alpha", ld_alpha)
                    ld_color: int = getattr(part_obj, "ld_color")
                    setattr(part_obj, "ld_color", ld_color)

                elif part_type == LightType.LED.value:
                    ld_alpha = getattr(part_obj, "ld_alpha")
                    setattr(part_obj, "ld_alpha", ld_alpha)
                    ld_effect: int = getattr(part_obj, "ld_effect")
                    setattr(part_obj, "ld_effect", ld_effect)
                    if ld_effect == 0:
                        for bulb in part_obj.children:
                            ld_alpha: int = getattr(bulb, "ld_alpha")
                            setattr(bulb, "ld_alpha", ld_alpha)
                            ld_color: int = getattr(bulb, "ld_color")
                            setattr(bulb, "ld_color", ld_color)


# ---------------------------------------------------------------------------
#  Add
# ---------------------------------------------------------------------------


async def add_control_frame():
    """Add a new control frame with all parts set to 'no effect' defaults.

    FIBER parts: color_id of first available color, alpha=0 (off)
    LED parts: effect_id=-1 (no-change), alpha=0 (off)
    None is reserved for partial-load skip (dancer not loaded).
    """
    if not bpy.context:
        return
    start = bpy.context.scene.frame_current

    # Pick a fallback color_id (first available, or 0)
    fallback_color_id = next(iter(state.color_map), 0)

    # Build status: every part = CtrlData with "no effect" values
    ctrl_stat: ControlMapStatus_MODIFIED = {}
    for dancer_name in state.dancer_names:
        ctrl_stat[dancer_name] = {}
        for part in next(d for d in state.dancers_array if d.name == dancer_name).parts:
            if part.type == PartType.LED:
                ctrl_stat[dancer_name][part.name] = CtrlData(
                    part_data=LEDData(effect_id=-1, alpha=0),
                    bulb_data=[],
                    fade=False,
                )
            else:
                ctrl_stat[dancer_name][part.name] = CtrlData(
                    part_data=FiberData(color_id=fallback_color_id, alpha=0),
                    bulb_data=[],
                    fade=False,
                )

    # Allocate next ID
    next_id = (max(state.control_record) + 1) if state.control_record else 1

    new_frame = ControlMapElement_MODIFIED(
        start=start,
        fade_for_new_status=False,
        rev=Revision(meta=0, data=0),
        status=ctrl_stat,
    )

    try:
        add_control(next_id, new_frame)
        if state.control_map_pending:
            apply_control_map_updates()
        notify("INFO", f"Added control frame at {start}")
        redraw_area({"VIEW_3D", "DOPESHEET_EDITOR"})
    except Exception:
        logger.exception("Failed to add control frame")
        notify("WARNING", "Cannot add control frame")


# ---------------------------------------------------------------------------
#  Helpers – read dancer status from existing frame or Blender model
# ---------------------------------------------------------------------------


def _read_ctrl_status_from_frame(
    dancer_name: str, frame: object
) -> dict[str, CtrlData | None]:
    """Read a dancer's status from an existing control frame.

    Handles both old table (ControlMapElement) and new table
    (ControlMapElement_MODIFIED).
    """
    result: dict[str, CtrlData | None] = {}
    dancer_status = frame.status.get(dancer_name, {})  # type: ignore

    if hasattr(frame, "led_status"):
        # Old table (ControlMapElement): convert PartData → CtrlData
        dancer_led_status = frame.led_status.get(dancer_name, {})  # type: ignore
        frame_fade: bool = frame.fade  # type: ignore
        for part_name in state.dancers[dancer_name]:
            part_data = dancer_status.get(part_name)
            if part_data is None:
                result[part_name] = None
            else:
                bulb_data = dancer_led_status.get(part_name, [])
                result[part_name] = CtrlData(
                    part_data=part_data, bulb_data=bulb_data, fade=frame_fade
                )
    else:
        # New table (ControlMapElement_MODIFIED): already CtrlData | None
        for part_name in state.dancers[dancer_name]:
            result[part_name] = dancer_status.get(part_name)

    return result


def _read_ctrl_status_from_model(
    dancer_name: str, default_color: ColorID
) -> dict[str, CtrlData | None]:
    """Read a dancer's status from Blender objects (for displayed dancers).

    Returns CtrlData for each part, or None if the part object is missing.
    """
    result: dict[str, CtrlData | None] = {}
    fade: bool = getattr(bpy.context.window_manager, "ld_fade", False)
    obj: bpy.types.Object | None = bpy.data.objects.get(dancer_name)

    if obj is not None:
        part_objs: list[bpy.types.Object] = getattr(obj, "children")
        part_obj_names: list[str] = [getattr(o, "ld_part_name") for o in part_objs]

        for part_name in state.dancers[dancer_name]:
            part_type = state.part_type_map[part_name]

            if part_name not in part_obj_names:
                # Part not found in Blender → default values
                if part_type == PartType.FIBER:
                    result[part_name] = CtrlData(
                        part_data=FiberData(color_id=default_color, alpha=0),
                        bulb_data=[],
                        fade=fade,
                    )
                elif part_type == PartType.LED:
                    result[part_name] = CtrlData(
                        part_data=LEDData(effect_id=-1, alpha=0),
                        bulb_data=[],
                        fade=fade,
                    )
                continue

            part_index = part_obj_names.index(part_name)
            part_obj = part_objs[part_index]

            if part_type == PartType.FIBER:
                color_id = part_obj["ld_color"]
                ld_alpha: int = getattr(part_obj, "ld_alpha")
                result[part_name] = CtrlData(
                    part_data=FiberData(color_id=color_id, alpha=ld_alpha),
                    bulb_data=[],
                    fade=fade,
                )
            elif part_type == PartType.LED:
                effect_id = part_obj["ld_effect"]
                ld_alpha: int = getattr(part_obj, "ld_alpha")
                bulb_data: list[LEDBulbData] = []
                if effect_id == 0:
                    bulb_objs: list[bpy.types.Object] = sorted(
                        list(getattr(part_obj, "children")),
                        key=lambda _obj: getattr(_obj, "ld_led_pos"),
                    )
                    bulb_data = [
                        LEDBulbData(
                            color_id=b["ld_color"],
                            alpha=getattr(b, "ld_alpha"),
                        )
                        for b in bulb_objs
                    ]
                result[part_name] = CtrlData(
                    part_data=LEDData(effect_id=effect_id, alpha=ld_alpha),
                    bulb_data=bulb_data,
                    fade=fade,
                )
    else:
        # Dancer object not found in Blender → all None
        for part_name in state.dancers[dancer_name]:
            result[part_name] = None

    return result


# ---------------------------------------------------------------------------
#  Save
# ---------------------------------------------------------------------------


async def save_control_frame(start: int | None = None):
    """Save the current editing control frame with new table format."""
    if not bpy.context:
        return
    id = state.editing_data.frame_id

    fade_for_new_status: bool = getattr(bpy.context.window_manager, "ld_fade", False)
    default_color = list(state.color_map.keys())[0] if state.color_map else 0

    show_dancer_dict = dict(zip(state.dancer_names, state.show_dancers))

    # Build ControlMapStatus_MODIFIED
    ctrl_stat: ControlMapStatus_MODIFIED = {}
    for dancer_name in state.dancer_names:
        if show_dancer_dict.get(dancer_name, False):
            # Displayed dancer: read current state from Blender objects
            ctrl_stat[dancer_name] = _read_ctrl_status_from_model(
                dancer_name, default_color
            )
        else:
            # Hidden dancer: preserve existing status from current frame
            frame = state.control_map.get(id)
            if frame is not None:
                ctrl_stat[dancer_name] = _read_ctrl_status_from_frame(
                    dancer_name, frame
                )
            else:
                ctrl_stat[dancer_name] = {p: None for p in state.dancers[dancer_name]}

    # Enforce fade consistency: all parts of the same dancer share the same
    # fade value (firmware limitation).
    for dancer_name, parts in ctrl_stat.items():
        for data in parts.values():
            if data is not None:
                data.fade = fade_for_new_status

    # Determine frame start time
    save_start = start
    if save_start is None:
        frame = state.control_map.get(id)
        if frame is not None:
            save_start = frame.start
        else:
            save_start = bpy.context.scene.frame_current

    new_frame = ControlMapElement_MODIFIED(
        start=save_start,
        fade_for_new_status=fade_for_new_status,
        rev=Revision(meta=0, data=0),
        status=ctrl_stat,
    )

    try:
        update_control(id, new_frame)

        # Exit editing
        state.current_editing_frame = -1
        state.current_editing_detached = False
        state.current_editing_frame_synced = False
        state.edit_state = EditMode.IDLE

        if state.local_view:
            execute_operator("view3d.localview")
            state.local_view = False
        set_outliner_filter("")

        if state.control_map_pending:
            apply_control_map_updates()

        notify("INFO", f"Saved control frame: {id}")
        redraw_area({"VIEW_3D", "DOPESHEET_EDITOR"})
    except Exception:
        logger.exception("Failed to save control frame")
        notify("WARNING", "Cannot save control frame")


# ---------------------------------------------------------------------------
#  Delete (partial load logic)
# ---------------------------------------------------------------------------


async def delete_control_frame():
    """Delete a control frame with partial load logic.

    If non-displayed (hidden) dancers have non-None status (i.e. they have
    actual effects), we only clear displayed dancers' parts to None.
    If ALL hidden parts are already None, the frame is fully deleted.
    """
    from .current_status import calculate_current_status_index

    # Recalculate to ensure we target the correct frame
    state.current_control_index = calculate_current_status_index()
    index = state.current_control_index

    if index < 0 or index >= len(state.control_record):
        notify("WARNING", "No control frame to delete")
        return

    id = state.control_record[index]

    frame = state.control_map.get(id)
    if frame is None:
        notify("WARNING", "Frame not found")
        return

    show_dancer_dict = dict(zip(state.dancer_names, state.show_dancers))
    logger.info(
        f"[delete_control_frame] id={id}, start={frame.start}, "
        f"frame_current={bpy.context.scene.frame_current}, index={index}, "
        f"show_dancers={state.show_dancers}, "
        f"has_hidden={any(not v for v in show_dancer_dict.values())}"
    )

    # Check: do non-displayed (hidden) dancers have any non-None status?
    has_hidden_effect = False
    for dancer_name in state.dancer_names:
        if show_dancer_dict.get(dancer_name, False):
            continue  # skip displayed dancers

        dancer_status = frame.status.get(dancer_name, {})  # type: ignore

        if hasattr(frame, "led_status"):
            # Old table: every part always has data → treat as having effects
            if dancer_status:
                has_hidden_effect = True
                break
        else:
            # New table: check for non-None parts
            for ctrl_data in dancer_status.values():
                if ctrl_data is not None:
                    has_hidden_effect = True
                    break
        if has_hidden_effect:
            break

    if has_hidden_effect:
        # Partial delete: only clear displayed dancers' parts to None,
        # keep hidden dancers' status untouched.
        new_status: ControlMapStatus_MODIFIED = {}
        for dancer_name in state.dancer_names:
            if show_dancer_dict.get(dancer_name, False):
                # Displayed dancer → set all parts to None (no effect)
                new_status[dancer_name] = {p: None for p in state.dancers[dancer_name]}
            else:
                # Hidden dancer → preserve existing status
                new_status[dancer_name] = _read_ctrl_status_from_frame(
                    dancer_name, frame
                )

        updated_frame = ControlMapElement_MODIFIED(
            start=frame.start,
            fade_for_new_status=getattr(
                frame, "fade_for_new_status", getattr(frame, "fade", False)
            ),
            rev=getattr(frame, "rev", Revision(meta=0, data=0)),
            status=new_status,
        )
        update_control(id, updated_frame)
        notify("INFO", f"Cleared displayed parts of frame: {id}")
    else:
        # Full delete: all hidden parts are None → safe to remove entirely
        delete_control(id)
        notify("INFO", f"Deleted control frame: {id}")

    if state.control_map_pending:
        apply_control_map_updates()
    redraw_area({"VIEW_3D", "DOPESHEET_EDITOR"})


# ---------------------------------------------------------------------------
#  Edit mode (mock – no backend lock needed)
# ---------------------------------------------------------------------------


async def request_edit_control() -> bool:
    """Enter editing mode for the nearest control frame at current time."""
    from .current_status import calculate_current_status_index

    # Recalculate to ensure we lock onto the correct frame
    state.current_control_index = calculate_current_status_index()
    index = state.current_control_index

    if index < 0 or index >= len(state.control_record):
        notify("WARNING", "No control frame selected")
        return False

    control_id = state.control_record[index]
    control_frame = state.control_map.get(control_id)
    if control_frame is None:
        notify("WARNING", "Control frame not found")
        return False

    # Set editing state directly (no server lock needed)
    state.current_editing_frame = control_frame.start
    state.editing_data = EditingData(
        start=control_frame.start, frame_id=control_id, index=index
    )
    state.edit_state = EditMode.EDITING

    attach_editing_control_frame()
    update_current_status_by_index()

    redraw_area({"VIEW_3D", "DOPESHEET_EDITOR"})
    return True


async def cancel_edit_control():
    """Cancel editing mode and revert to saved state."""
    # Revert to saved state
    update_current_status_by_index()

    # Reset editing state
    state.current_editing_frame = -1
    state.current_editing_detached = False
    state.current_editing_frame_synced = False
    state.edit_state = EditMode.IDLE

    if state.local_view:
        execute_operator("view3d.localview")
        state.local_view = False
    set_outliner_filter("")

    redraw_area({"VIEW_3D", "DOPESHEET_EDITOR"})


# ---------------------------------------------------------------------------
#  Selection mode toggles
# ---------------------------------------------------------------------------


def toggle_dancer_mode():
    bpy.context.view_layer.objects.active = None  # type: ignore
    state.selected_obj_type = None
    clear_selection()
    state.selection_mode = SelectMode.DANCER_MODE
    redraw_area({"VIEW_3D", "DOPESHEET_EDITOR"})


def toggle_part_mode():
    bpy.context.view_layer.objects.active = None  # type: ignore
    state.selected_obj_type = None
    clear_selection()
    state.selection_mode = SelectMode.PART_MODE
    redraw_area({"VIEW_3D", "DOPESHEET_EDITOR"})


def toggle_led_focus(obj: bpy.types.Object):
    toggle_part_mode()
    if not state.local_view:
        bpy.ops.object.select_all(action="DESELECT")
        for bulb in obj.children:
            bulb.select_set(True)
        execute_operator("view3d.localview")
        set_outliner_filter(obj.name + ".")
        state.local_view = True
    else:
        bpy.ops.object.select_all(action="DESELECT")
        execute_operator("view3d.localview")
        set_outliner_filter("")
        state.local_view = False
